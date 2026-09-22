-- 第45課題(データベースを一段深く): ログイン失敗回数のチェック(auth.authenticate)は
-- ログイン試行のたびに実行される最も頻度の高いクエリだが、既存の索引
-- idx_audit_log_action_created_at は (action, created_at) までしかカバーしておらず、
-- username の一致は索引ヒット後の追加フィルターになっていた(本番でEXPLAINして確認済み)。
-- action・username・created_at をまとめてカバーする索引を追加する。
CREATE INDEX IF NOT EXISTS idx_audit_log_action_username_created_at
    ON audit_log (action, username, created_at);
