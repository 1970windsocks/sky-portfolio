import os
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row


def _connect():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def log_action(username, action, detail=""):
    """「誰が・いつ・何をしたか」を記録する。usernameは不明な場合Noneでよい。"""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO audit_log (username, action, detail) VALUES (%s, %s, %s)",
            (username, action, detail),
        )


def recent_count(action, minutes, username=None, detail=None):
    """直近minutes分に条件へ一致した監査ログの件数を返す(レート制限の判定に使う)。"""
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    conditions = ["action = %s", "created_at >= %s"]
    params = [action, since]
    if username is not None:
        conditions.append("username = %s")
        params.append(username)
    if detail is not None:
        conditions.append("detail = %s")
        params.append(detail)

    with _connect() as conn:
        row = conn.execute(
            f"SELECT count(*) AS c FROM audit_log WHERE {' AND '.join(conditions)}",
            params,
        ).fetchone()
    return row["c"]


def recent_entries(limit=20):
    """管理者ダッシュボード表示用。新しい順に返す。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT username, action, detail, created_at FROM audit_log ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
