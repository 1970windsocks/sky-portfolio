CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    username TEXT,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_action_created_at ON audit_log (action, created_at);
