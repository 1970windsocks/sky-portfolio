import os
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR / "scripts"))

import audit  # noqa: E402
from aggregate_daily_stats import aggregate_daily_stats  # noqa: E402


def test_aggregate_daily_stats_groups_by_action_for_target_date():
    database_url = os.environ["DATABASE_URL"]
    target_date = date(2026, 1, 15)
    other_date = target_date - timedelta(days=1)

    audit.log_action("alice", "signup")
    audit.log_action("bob", "signup")
    audit.log_action("alice", "login_success")

    # 対象日以外のログは今回の集計に混ざってはいけない
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE audit_log SET created_at = %s WHERE action = 'login_success'",
            (other_date,),
        )
        conn.execute(
            "UPDATE audit_log SET created_at = %s WHERE action = 'signup'",
            (target_date,),
        )

    result = aggregate_daily_stats(database_url, target_date)

    counts = {item["action"]: item["count"] for item in result}
    assert counts == {"signup": 2}

    with psycopg.connect(database_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT action, count FROM daily_action_stats WHERE stat_date = %s",
            (target_date,),
        ).fetchall()
    assert dict(rows) == {"signup": 2}


def test_aggregate_daily_stats_is_idempotent_on_rerun():
    database_url = os.environ["DATABASE_URL"]
    target_date = date(2026, 1, 15)

    audit.log_action("alice", "signup")
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("UPDATE audit_log SET created_at = %s", (target_date,))

    aggregate_daily_stats(database_url, target_date)
    aggregate_daily_stats(database_url, target_date)

    with psycopg.connect(database_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT count FROM daily_action_stats WHERE stat_date = %s AND action = 'signup'",
            (target_date,),
        ).fetchall()
    # audit_logには1件しかないので、2回実行しても行が増えず件数も1のまま
    # (再実行のたびに加算されてしまうバグ=1件が2件になる、を防げていることの確認)
    assert rows == [(1,)]
