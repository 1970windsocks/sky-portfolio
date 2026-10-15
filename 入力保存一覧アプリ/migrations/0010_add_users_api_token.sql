-- 第54課題(セキュリティ設計): /api/memos が、たった1つの共有トークンと
-- クライアントが自由に指定できるownerパラメータで動いていた。
-- トークンが1つでも漏れると「全ユーザー」のメモを読めてしまう権限設計の欠陥だった。
-- ユーザーごとのAPIトークン(ハッシュ化して保存)に切り替え、
-- トークン自体が「誰の代わりに動いているか」を決めるようにする。
ALTER TABLE users ADD COLUMN IF NOT EXISTS api_token_hash TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_api_token_hash
    ON users (api_token_hash)
    WHERE api_token_hash IS NOT NULL;
