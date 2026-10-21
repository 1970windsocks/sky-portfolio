# オンボーディングガイド

第70課題で作成。「とりあえずREADMEを読んで」ではなく、実際に新しく参加する人が
つまずく場所を先回りして埋めた、最初の1歩の手順。

## ステップ0: 必要なもの

- Python 3.12
- Git
- (ローカルでテストを動かすなら)Docker — 無くてもコードを読んで理解することはできる

## ステップ1: clone して依存をインストール

```bash
git clone <このリポジトリ>
cd 入力保存一覧アプリ
pip install -r requirements.txt -r requirements-dev.txt
```

## ステップ2: 先に知っておく — このアプリが使う環境変数

| 変数名 | 必須度 | 用途 |
|---|---|---|
| `DATABASE_URL` | 必須 | Postgres接続文字列(無いとテストもアプリ起動もできない) |
| `STRIPE_SECRET_KEY` | 課金機能を触るなら必須 | Stripe API |
| `STRIPE_WEBHOOK_SECRET` | Webhookを触るなら必須 | Stripe Webhook署名検証 |
| `STRIPE_PRICE_ID` | 課金機能を触るなら必須 | Proプランの価格ID |
| `RESEND_API_KEY` | メール送信を試すなら必須 | サインアップ確認メール等 |
| `RESEND_FROM` | 任意(省略時デフォルト値あり) | 送信元アドレス |
| `APP_BASE_URL` | 任意(省略可) | メール内のリンクに使うドメイン |
| `ANTHROPIC_API_KEY` | AI機能(カテゴリー提案・RAG・エージェント)を試すなら必須 | Claude API |
| `PORT` | 任意(Railwayが自動設定) | Flaskサーバーの待受ポート |

## ステップ3: テスト用DBを用意する

**先に言っておく、実際につまずいた点**: 何も準備せずに`pytest`を実行すると、
以下のような分かりにくいエラーで止まる。

```
E       KeyError: 'DATABASE_URL'
tests\conftest.py:19: KeyError
```

これは「`DATABASE_URL`という環境変数が無い」という意味で、イコール
「テスト用のPostgresをまだ用意していない」ということ。CI(`.github/workflows/test.yml`)
が実際に使っている設定と同じものを、Dockerでローカルに立てれば解決する。

```bash
docker run --rm -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=test postgres:16
```

別のターミナルで環境変数を設定する(このDBは使い捨て用で、本番とは完全に別物):

```bash
# PowerShell
$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/test"

# bash
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/test"
```

**⚠️ 絶対にやってはいけないこと**: `DATABASE_URL`を本番(Railway上のPostgres)に
向けたままテストを実行しないこと。テストは`conftest.py`の`clean_db`フィクスチャで、
テスト開始のたびに`memos`・`users`・`audit_log`等を**丸ごと消す**。本番に向けたまま
実行すると、本番のデータが全部消える。

## ステップ4: テストを実行する

```bash
pytest -v
```

ここまでの手順通りに進めていれば、現時点で100件以上のテストが全部通るはず。
通らない場合は、`DATABASE_URL`が正しいか(ステップ3)を先に疑う。

## ステップ5: ローカルでアプリを動かしてみる

```bash
streamlit run app.py
```

`DATABASE_URL`さえあれば画面は起動して見られる。ただし、サインアップ時の
確認メール送信には`RESEND_API_KEY`も必要 — 無い状態でサインアップを試すと、
画面上は「確認メールを送信しました」と出るが、実際には裏の非同期キュー
(第60課題)で送信が失敗し、`email_send_failed`として記録されるだけで止まる
(アプリ自体はクラッシュしない)。「メールが届かない」と思ったら、まず
`RESEND_API_KEY`が設定されているか確認する。

## 次に読むべきドキュメント(この順番がおすすめ)

1. `README.md` — 全体像・何を作ったか
2. `ARCHITECTURE.md` — システム構成図
3. `CODING_STANDARDS.md` — このプロジェクトの書き方の約束事
4. `docs/adr/` — これまでの設計判断とその理由
5. `THREAT_MODEL.md` / `SRE_RUNBOOK.md` — セキュリティ・運用の考え方

## このガイド自体を実際に試した記録

想定初心者として、この手順を公開する前に実際に辿ってみた。

1. 依存関係のインポート(`streamlit`・`psycopg`・`bcrypt`・`flask`)を確認 → 問題なし
2. 何も環境変数を設定しない状態で`pytest`を実行 → `KeyError: 'DATABASE_URL'`で停止。
   メッセージだけ見ると「何のテストが悪いのか」が分かりにくく、初めて見る人は
   戸惑うだろうと判断。
3. 上記2の結果を受けて、ステップ3に「先に言っておく、実際につまずいた点」として
   このエラーメッセージそのものを載せ、原因(テスト用DB未設定)と対処(Dockerで
   CIと同じ構成を立てる)を先回りして書くよう改訂した。

つまずいた箇所をそのまま載せたのは、「エラーに出会うこと自体は失敗ではなく、
エラーメッセージを読んで原因にたどり着く練習になる」という考え方による
(上の「伴走の言葉」の姿勢と同じ)。

## 詰まったときの考え方

- まずエラーメッセージをそのまま読む。`KeyError: 'DATABASE_URL'`のように、
  Pythonのエラーは「何が無いか」を正確に教えてくれていることが多い。
- 次に`docs/adr/`を見る。「なぜこうなっているか」の答えが大体そこにある。
- それでも分からなければ、具体的に「何を試して、何が起きたか」を書き出してから聞く。
  「動きません」だけでは、聞かれた側も何を見ればいいか分からない。
