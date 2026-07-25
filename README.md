# 幕張 共用施設(ビューラウンジ&ゲスト)空き状況監視

毎週土日の空き状況をチェックし、新たに「空き」になった日をメールで通知します。

## 確認済みの仕様

Chrome経由でログイン状態を実際に確認し、以下を反映済みです。

- ログインフォームは `email` / `password` という name 属性の入力欄
- カレンダーは月表示で、日付ごとに `available` / `available-lottery` /
  `available-busy` / `reserved` / `unavailable` のCSSクラスが付いており、
  日付を1つずつクリックする必要はない
- 「次月へ」ボタン(`id="after_month"`)で月を進められるが、この施設は
  **直近2ヶ月分**しか予約枠が開放されない仕様だった(それより先はボタンを
  押しても月が変わらない)。スクリプトはこれを検知して自動的に停止する
  ので、`WEEKS_AHEAD` は特に気にしなくても開放されている範囲は全てカバー
  されます

そのため `monitor.py` はこのまま動く想定です。もしサイトの構造が将来
変わってセレクタが効かなくなった場合は、末尾の「注意事項」の手順で
再確認してください。

## セットアップ

### 1. 依存パッケージ

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 環境変数

| 変数名 | 内容 |
|---|---|
| `MWPS_USER_ID` | サイトのユーザーID |
| `MWPS_PASSWORD` | サイトのパスワード |
| `GMAIL_ADDRESS` | 通知メール送信元のGmailアドレス |
| `GMAIL_APP_PASSWORD` | Googleの「アプリパスワード」(通常ログインパスワードは使えません) |
| `NOTIFY_TO_EMAIL` | 通知を受け取りたいメールアドレス(省略時は送信元と同じ) |
| `WEEKS_AHEAD` | 何週間先までチェックするか(デフォルト10) |

Googleアプリパスワードは https://myaccount.google.com/apppasswords から発行できます
(2段階認証を有効にする必要があります)。

### 3. 動作確認(ローカル)

```bash
export MWPS_USER_ID="..."
export MWPS_PASSWORD="..."
export GMAIL_ADDRESS="..."
export GMAIL_APP_PASSWORD="..."
export HEADLESS=false   # ブラウザの動きを目で確認できます
python monitor.py
```

## 定期実行方法(2択)

### A. GitHub Actions で自動実行(PCを起動しておく必要なし・おすすめ)

1. このフォルダ一式をGitHubの**プライベート**リポジトリにpush
   (ユーザーID/パスワードはコードに書かないので安全ですが、念のため必ずプライベートにしてください)
2. リポジトリの Settings → Secrets and variables → Actions で、上記の環境変数を
   同名の Secret として登録
   (`MWPS_USER_ID`, `MWPS_PASSWORD`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `NOTIFY_TO_EMAIL`)
3. `.github/workflows/monitor.yml` が自動的に1時間おきに実行されます
   (頻度を変えたい場合はyml内の `cron` を編集)
4. Actionsタブから手動実行(Run workflow)も可能

**無料枠について**: プライベートリポジトリは月2,000分まで無料です。1時間おき
(1日24回)実行だと、1回あたり2〜3分程度(ブラウザインストールはキャッシュ
される前提)として月あたり1,500〜2,000分程度になり、ギリギリ収まる想定です。
公開(public)リポジトリなら無料枠は無制限です。コードにはID/パスワードを
書かない(Secretsで管理)ので、公開しても資格情報が漏れることはありません
が、施設URLなど個人が特定されうる情報が含まれるので、迷う場合はprivateの
ままにして、頻度を2〜3時間おきに調整することをおすすめします。

### B. 自分のPC/NASで cron・タスクスケジューラ実行

- Mac/Linux: `crontab -e` で例えば毎時0分に実行
  ```
  0 * * * * cd /path/to/makuhari_monitor && /usr/bin/python3 monitor.py >> monitor.log 2>&1
  ```
- Windows: タスクスケジューラで「1時間ごと」のトリガーを作成し、
  プログラムに `python.exe`、引数に `monitor.py` のフルパスを指定
  (環境変数はタスクの「環境」設定 or 事前に `setx` で登録)

## 注意事項

- 土日以外の日付はチェック対象外です(`monitor.py`の`get_target_dates()`で判定)
- 前回チェック時から状態が変わった日のみメール通知します(毎回全件通知はしません)
- サイト構造が変わるとセレクタが効かなくなる可能性があります。その場合は
  上記のcodegen手順で再取得してください
