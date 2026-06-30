import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


DELETE_RANGE_CONFIRMATION = "DELETE MY POSTS"
DELETE_ALL_CONFIRMATION = "DELETE ALL MY POSTS"
DEFAULT_MAX_SCAN = 1_000
MAX_SCAN_LIMIT = 100_000
DAILY_DELETE_LIMIT = 3
USAGE_FILE = Path("delete_usage.json")
LOCAL_TIMEZONE = ZoneInfo("Asia/Tokyo")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("delete-my-posts-bot")


@dataclass(frozen=True)
class DeletePlan:
    scanned: int
    matched: list[discord.Message]


class DeleteMyPostsBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.delete_locks: set[tuple[int, int]] = set()
        self.usage_store = DailyUsageStore(USAGE_FILE)
        self.guild_id = _read_optional_int("DISCORD_GUILD_ID")

    async def setup_hook(self) -> None:
        self.tree.add_command(delete_my_posts)
        if self.guild_id is not None:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Synced slash commands to guild %s", self.guild_id)
        else:
            await self.tree.sync()
            logger.info("Synced global slash commands")


def _read_optional_int(name: str) -> Optional[int]:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer when set") from exc


class DailyUsageStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._counts = self._load()

    def get_count(self, user_id: int, day: date) -> int:
        return int(self._counts.get(day.isoformat(), {}).get(str(user_id), 0))

    def remaining(self, user_id: int, day: date) -> int:
        return max(0, DAILY_DELETE_LIMIT - self.get_count(user_id, day))

    def increment(self, user_id: int, day: date) -> int:
        day_key = day.isoformat()
        user_key = str(user_id)
        self._counts.setdefault(day_key, {})
        self._counts[day_key][user_key] = self.get_count(user_id, day) + 1
        self._prune_before(day - timedelta(days=7))
        self._save()
        return self._counts[day_key][user_key]

    def _load(self) -> dict[str, dict[str, int]]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise RuntimeError(f"{self.path} must contain a JSON object")
        return {
            str(day): {
                str(user_id): int(count)
                for user_id, count in counts.items()
                if isinstance(counts, dict)
            }
            for day, counts in data.items()
            if isinstance(counts, dict)
        }

    def _save(self) -> None:
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(self._counts, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")

    def _prune_before(self, cutoff: date) -> None:
        self._counts = {
            day_key: counts
            for day_key, counts in self._counts.items()
            if _parse_date_key(day_key) >= cutoff
        }


def _parse_date_key(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return date.min


def _today_local() -> date:
    return datetime.now(LOCAL_TIMEZONE).date()


def _normalize_datetime_range(
    start_datetime: Optional[str],
    end_datetime: Optional[str],
) -> tuple[Optional[datetime], Optional[datetime]]:
    start_at = _parse_local_datetime(start_datetime, "start_datetime", is_end=False)
    end_at = _parse_local_datetime(end_datetime, "end_datetime", is_end=True)
    if start_at is not None and end_at is not None and start_at > end_at:
        start_at, end_at = end_at, start_at
    return start_at, end_at


def _parse_local_datetime(
    value: Optional[str],
    field_name: str,
    is_end: bool,
) -> Optional[datetime]:
    if value is None or value.strip() == "":
        return None
    value = value.strip()
    has_date_only = len(value) == 10
    has_minute_precision = len(value) == 16
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} は `YYYY-MM-DD`、`YYYY-MM-DD HH:MM`、"
            "`YYYY-MM-DD HH:MM:SS` のいずれかの形式で入力してください。"
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    if is_end and has_date_only:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif is_end and has_minute_precision:
        parsed = parsed.replace(second=59, microsecond=999999)
    return parsed.astimezone(timezone.utc)


def _is_in_datetime_range(
    created_at: datetime,
    start_at: Optional[datetime],
    end_at: Optional[datetime],
) -> bool:
    created_at = created_at.astimezone(timezone.utc)
    if start_at is not None and created_at < start_at:
        return False
    if end_at is not None and created_at > end_at:
        return False
    return True


async def _build_delete_plan(
    channel: discord.abc.Messageable,
    user_id: int,
    start_at: Optional[datetime],
    end_at: Optional[datetime],
    max_scan: Optional[int],
    include_pinned: bool,
) -> DeletePlan:
    matched: list[discord.Message] = []
    scanned = 0

    async for message in channel.history(
        limit=max_scan,
        after=start_at,
        before=end_at + timedelta(microseconds=1) if end_at is not None else None,
        oldest_first=False,
    ):
        scanned += 1
        if not _is_in_datetime_range(message.created_at, start_at, end_at):
            continue
        if message.author.id != user_id:
            continue
        if message.pinned and not include_pinned:
            continue
        matched.append(message)

    return DeletePlan(scanned=scanned, matched=matched)


def _required_confirmation(start_at: Optional[datetime], end_at: Optional[datetime]) -> str:
    if start_at is None and end_at is None:
        return DELETE_ALL_CONFIRMATION
    return DELETE_RANGE_CONFIRMATION


async def _delete_messages_safely(
    messages: list[discord.Message],
    user_id: int,
) -> tuple[int, int]:
    deleted = 0
    failed = 0

    for message in messages:
        # This is the final guard against deleting another user's post.
        if message.author.id != user_id:
            logger.error(
                "Refusing to delete message %s: author %s != requester %s",
                message.id,
                message.author.id,
                user_id,
            )
            failed += 1
            continue

        try:
            await message.delete()
            deleted += 1
            await asyncio.sleep(0.35)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            logger.exception("Failed to delete message %s", message.id)
            failed += 1

    return deleted, failed


@app_commands.command(
    name="delete_my_posts",
    description="指定した範囲にある自分の投稿だけを削除します",
)
@app_commands.describe(
    start_datetime="削除範囲の開始日時。例: 2026-06-30 09:00。空なら取得できる最古側まで対象",
    end_datetime="削除範囲の終了日時。例: 2026-06-30 18:30。空なら最新側まで対象",
    max_scan="最大で確認するメッセージ数。全削除したい場合は大きめに指定",
    include_pinned="ピン留め済みの自分の投稿も削除する",
    confirm="削除実行時の確認文字列。まず空のまま実行して件数確認してください",
)
async def delete_my_posts(
    interaction: discord.Interaction,
    start_datetime: Optional[str] = None,
    end_datetime: Optional[str] = None,
    max_scan: app_commands.Range[int, 0, MAX_SCAN_LIMIT] = DEFAULT_MAX_SCAN,
    include_pinned: bool = False,
    confirm: Optional[str] = None,
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message(
            "このコマンドはサーバー内のチャンネルでのみ使用できます。",
            ephemeral=True,
        )
        return

    channel = interaction.channel
    if channel is None or not isinstance(channel, discord.abc.Messageable):
        await interaction.response.send_message(
            "このチャンネルではメッセージ履歴を取得できません。",
            ephemeral=True,
        )
        return

    try:
        start_at, end_at = _normalize_datetime_range(start_datetime, end_datetime)
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return

    lock_key = (interaction.channel_id or 0, interaction.user.id)
    bot = interaction.client
    if not isinstance(bot, DeleteMyPostsBot):
        await interaction.response.send_message("bot の内部状態が不正です。", ephemeral=True)
        return
    if lock_key in bot.delete_locks:
        await interaction.response.send_message(
            "同じチャンネルであなたの削除処理がすでに実行中です。",
            ephemeral=True,
        )
        return

    required_confirmation = _required_confirmation(start_at, end_at)
    delete_requested = (confirm or "").strip() == required_confirmation
    today = _today_local()
    remaining_deletes = bot.usage_store.remaining(interaction.user.id, today)
    if delete_requested and remaining_deletes <= 0:
        await interaction.response.send_message(
            "本日の削除実行回数は上限の3回に達しています。明日以降に再実行してください。",
            ephemeral=True,
        )
        return

    bot.delete_locks.add(lock_key)
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        plan = await _build_delete_plan(
            channel=channel,
            user_id=interaction.user.id,
            start_at=start_at,
            end_at=end_at,
            max_scan=None if max_scan == 0 else max_scan,
            include_pinned=include_pinned,
        )

        if not delete_requested:
            await interaction.followup.send(
                "\n".join(
                    [
                        "削除はまだ実行していません。",
                        f"確認した投稿数: {plan.scanned}",
                        f"削除候補になったあなたの投稿数: {len(plan.matched)}",
                        f"本日の削除実行可能回数: {remaining_deletes}",
                        f"削除するには `confirm` に `{required_confirmation}` を指定して再実行してください。",
                    ]
                ),
                ephemeral=True,
            )
            return

        deleted, failed = await _delete_messages_safely(
            messages=plan.matched,
            user_id=interaction.user.id,
        )
        used_count = bot.usage_store.increment(interaction.user.id, today)
        await interaction.followup.send(
            "\n".join(
                [
                    "削除処理が完了しました。",
                    f"確認した投稿数: {plan.scanned}",
                    f"削除対象だったあなたの投稿数: {len(plan.matched)}",
                    f"削除成功: {deleted}",
                    f"削除失敗: {failed}",
                    f"本日の削除実行回数: {used_count}/{DAILY_DELETE_LIMIT}",
                ]
            ),
            ephemeral=True,
        )
    finally:
        bot.delete_locks.discard(lock_key)


def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set")

    bot = DeleteMyPostsBot()
    bot.run(token)


if __name__ == "__main__":
    main()
