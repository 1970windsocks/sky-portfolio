import os
from datetime import datetime, timedelta, timezone

import psycopg

import audit


def test_system_failure_counts_counts_only_system_actions():
    audit.log_action(None, "email_send_failed", detail="test@example.com: timeout")
    audit.log_action(None, "uptime_summary_failed", detail="HTTP 500")
    audit.log_action(None, "uptime_summary_failed", detail="HTTP 500")
    # ユーザーの入力ミス(パスワード間違い)はシステム障害ではないので含めない
    audit.log_action("someone", "login_failed")

    counts = audit.system_failure_counts()

    assert counts == {"email_send_failed": 1, "uptime_summary_failed": 2}


def test_system_failure_counts_excludes_entries_outside_window():
    database_url = os.environ["DATABASE_URL"]
    audit.log_action(None, "email_send_failed", detail="old")
    old_time = datetime.now(timezone.utc) - timedelta(days=2)
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("UPDATE audit_log SET created_at = %s WHERE action = 'email_send_failed'", (old_time,))

    counts = audit.system_failure_counts(window_minutes=60)

    assert counts == {"email_send_failed": 0, "uptime_summary_failed": 0}


def test_system_failure_counts_is_zero_when_no_failures():
    audit.log_action("someone", "signup")

    counts = audit.system_failure_counts()

    assert counts == {"email_send_failed": 0, "uptime_summary_failed": 0}
