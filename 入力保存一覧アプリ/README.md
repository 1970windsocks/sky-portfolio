# 入力保存一覧アプリ

メモを保存・検索・整理できる、Stripe課金付きの会員制Webアプリ。
Python初心者がClaude Codeと57日かけて、設計からセキュリティ・運用まで一通り経験しながら作った個人開発のSaaSです。

**本番URL**: https://charismatic-abundance-production-cae0.up.railway.app

---

## 何を作ったか

- メモの保存・検索・カテゴリ分け・お気に入り・CSVエクスポート(Pro限定)
- メール確認・パスワードリセット付きのアカウント登録/ログイン
- Stripeによる月額課金(Free: 月5件まで / Pro: 無制限)、Webhook経由の自動プラン反映
- 管理者ダッシュボード(顧客一覧・稼働率・監査ログ)
- 外部向けAPI(`/api/memos`、ユーザーごとのトークン認証)
- 利用規約・特定商取引法に基づく表記・プライバシーポリシー

## どう作っているか

| 項目 | 内容 |
|---|---|
| 言語・画面 | Python 3.12 / Streamlit |
| DB | Postgres(Railway) |
| 課金 | Stripe(Checkout + Webhook) |
| メール送信 | Resend |
| Webhook受信・外部API | Flask(別サービス) |
| ホスティング | Railway(Railpack / Dockerfile両対応) |
| CI | GitHub Actions(pytest、テスト約100件) |

## どう守っているか

- パスワードはbcryptでハッシュ化、SQLはすべてパラメータ化クエリ
- ログイン失敗・パスワードリセットにレート制限
- テナント越境ゼロ(他人のメモを操作できない設計)
- 通信はHTTPS(Let's Encrypt、Railwayが自動更新)
- 外部APIはユーザーごとのトークンで認証(過去に発見・修正した権限設計の欠陥あり。詳細は後述)

## どう運用しているか

- 死活監視(GitHub Actions、SLO目標99.5%)+失敗時メールアラート
- 障害発生時はポストモーテムを書く運用(`ポストモーテム_*.md`)
- バックアップ手順あり(`バックアップ手順.md`、現状はmemosテーブルのみ対応)

## ローカルで動かす

```bash
# 1. 専用の仮想環境を作る(パソコン全体の環境を汚さないため)
py -3.12 -m venv venv
source venv/Scripts/activate   # Windows(Git Bash)。Macは venv/bin/activate

# 2. 固定バージョンの依存をインストール
pip install -r requirements.txt

# 3. 必要な環境変数を設定(例: ローカルのPostgresを用意した場合)
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/test"
export APP_USERS='{"admin": {"password_hash": "...", "role": "admin"}}'

# 4. 起動
streamlit run app.py
```

**⚠️ テスト実行時の注意**: `tests/conftest.py`の`clean_db`はテストの度に`memos`・`users`・`audit_log`等を
`TRUNCATE`する(autouse、全テストで自動実行)。`DATABASE_URL`を本番や共有DBに向けたまま`pytest`を実行すると
実データが消える。必ずローカル専用の使い捨てDB(CIと同じ`postgres:16`コンテナ等)に向けること。

## 開発の記録

Claude Codeとの「クロードコード部」という日次講座形式で、SaaS本体の実装(全23回)→
仕組みの理解(DNS/HTTP/DB/HTTPS等、全12回)→独り立ち編(設計/アルゴリズム/CI-CD/
セキュリティ/見積りなど、全15回)の順に進めてきました。技術的な判断の記録は
`技術カルテ.md`・`見積り工程表_v2.md`・各種ポストモーテムに残しています。

## 既知の未対応事項

GitHubのIssueで管理している(第88課題より。現状とズレたらIssue側を正とする)。

- Stripeは本番Liveモード未設定(事業者審査・銀行口座登録待ち)
- 独自ドメイン未取得
- `app.py`が659行の単一ファイルになっており分割予定(`見積り工程表_v2.md`参照)
- RailwayのWait for CI(CI通過を待ってからデプロイする設定)が未設定
- `legal.py`の事業者情報がプレースホルダーのまま(`法務チェックリスト.md`参照)
- バックアップ対象が`memos`テーブルのみ(`users`・`auth_tokens`への拡張が未完了)
- 週次バックアップ自動化(`.github/workflows/backup.yml`)が下書きのまま未稼働
- 本番用Webhook受信サービスが未デプロイ(RailwayのFreeプラン上限、アップグレード待ち)
- 自動E2Eテストが無い(ブラウザでの動作確認はPlaywrightでの手動検証に依存)

## 何を・どこに残すか(残す文化)

- **Issue** = やること・バグ・要望。思いついたら頭の中に置かず、まずIssueに1件起票する
- **README(このファイル)** = 今のプロジェクトの全体像。概要・動かし方・現状の未対応事項を常に最新に保つ
- **コミットメッセージ・PR説明** = 変更履歴。「何を・なぜ変えたか」は`git log`そのものが記録になるよう、
  コミットメッセージに課題番号と理由を書く(このリポジトリの既存コミットが実例)
