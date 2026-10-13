-- 第65課題(AIエージェントと評価): サポート回答ドラフト・エージェントが
-- 作った下書きを貯めるテーブル。エージェント自身はここへの書き込みしかできず、
-- 顧客に実際に送るかどうかは必ず人間(管理者)が判断する(安全ガード)。
CREATE TABLE IF NOT EXISTS support_drafts (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    sources TEXT NOT NULL,
    score INTEGER NOT NULL,
    passed BOOLEAN NOT NULL,
    reason TEXT NOT NULL,
    search_attempts INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
