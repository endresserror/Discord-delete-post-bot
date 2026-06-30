# Discord Delete Post Bot

自分の投稿だけを指定範囲で削除する Discord bot です。コマンド実行者以外の投稿は、削除候補収集時と削除直前の両方で除外します。

## セットアップ

1. Python 3.10 以上を用意します。
2. 依存関係をインストールします。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. `.env.example` を参考に `.env` を作成します。

```bash
cp .env.example .env
```

4. Discord Developer Portal で bot を作成し、`.env` の `DISCORD_TOKEN` に bot token を設定します。

5. bot をサーバーへ招待します。必要な権限は次の通りです。

Discord Developer Portal の OAuth2 URL Generator で `bot` と `applications.commands` を選び、Bot Permissions では以下だけを ON にしてください。

一般権限:

- `チャンネルを表示` / `View Channels`

テキストの権限:

- `メッセージを送る` / `Send Messages`
- `メッセージを管理` / `Manage Messages`
- `メッセージ履歴を読む` / `Read Message History`
- `スラッシュコマンドを使用` / `Use Application Commands`

`管理者`、`サーバー管理`、`チャンネルの管理`、`ロールの管理` は不要です。

6. 起動します。

```bash
python bot.py
```

## コマンド

`/delete_my_posts`

指定したチャンネル内で、コマンドを実行した本人の投稿だけを削除します。

主な引数:

- `start_datetime`: 削除範囲の開始日時。例: `2026-06-30 09:00`。省略すると取得できる最古側まで対象です。
- `end_datetime`: 削除範囲の終了日時。例: `2026-06-30 18:30`。省略すると最新側まで対象です。
- `target_channel`: 削除対象のチャンネル。省略するとコマンドを実行したチャンネルが対象です。
- `all_channels`: `true` にすると、サーバー内で bot が閲覧できる全テキストチャンネルを対象にします。
- `max_scan`: 最大で確認するメッセージ数。初期値は `1000`、`0` にすると取得可能な履歴を上限なしで確認します。
- `include_pinned`: ピン留め済みの自分の投稿も削除するか。初期値は `false` です。
- `confirm`: 削除確認文字列。空のまま実行すると件数確認だけを行います。

日時はタイムゾーンを書かない場合、日本時間として扱います。日付だけを指定した場合は `2026-06-30 00:00:00` として扱いますが、`end_datetime` の日付だけ指定はその日の終わりまで含めます。

削除実行は1ユーザーにつき1日3回までです。`confirm` を空にした件数確認だけの実行は回数に含めません。回数は `delete_usage.json` に保存されます。

## 安全な使い方

まず `confirm` を空にして実行し、削除候補数を確認してください。

範囲指定ありで削除する場合:

```text
confirm = DELETE MY POSTS
```

日時範囲を指定して削除する例:

```text
start_datetime = 2026-06-30 09:00
end_datetime = 2026-06-30 18:30
target_channel = #general
confirm = DELETE MY POSTS
```

`start_datetime` と `end_datetime` の両方を省略して、取得範囲内の自分の投稿を全削除する場合:

```text
confirm = DELETE ALL MY POSTS
```

チャンネル内の取得可能な履歴をすべて対象にしたい場合は、`start_datetime` と `end_datetime` を空にし、`max_scan` を `0` にしてください。まずは `confirm` を空にして候補数を確認してください。

全テキストチャンネルを対象にして日時範囲で削除する場合:

```text
all_channels = true
start_datetime = 2026-06-30 09:00
end_datetime = 2026-06-30 18:30
confirm = DELETE MY POSTS IN ALL CHANNELS
```

全テキストチャンネルを対象にして取得可能な自分の投稿を全削除する場合:

```text
all_channels = true
start_datetime =
end_datetime =
max_scan = 0
confirm = DELETE ALL MY POSTS IN ALL CHANNELS
```

`all_channels = true` と `target_channel` は同時に指定できません。全チャンネル対象の場合、`max_scan` は各チャンネルごとの確認上限として扱われます。

## 注意

- Discord API の制約上、bot から見て他ユーザーの投稿削除になるため `Manage Messages` 権限が必要です。
- `all_channels = true` の場合も、削除されるのはコマンド実行者本人の投稿だけです。
- `max_scan` を大きくすると処理に時間がかかります。
- 投稿削除は取り消せませんので自己責任で行ってください。

## 免責

このプログラムの使用によって発生するいかなる損害も製作者は責任を追いません。
各自自己責任でプログラムを実行、改造をして使用してもらって構いません。
