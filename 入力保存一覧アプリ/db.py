import os

import psycopg
from psycopg.rows import dict_row


def _connect():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def list_memos(owner):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, owner, text, category, date FROM memos WHERE owner = %s ORDER BY id",
            (owner,),
        ).fetchall()
    return [dict(row) for row in rows]


def insert_memo(owner, text, category="", date=""):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO memos (owner, text, category, date) VALUES (%s, %s, %s, %s)",
            (owner, text, category, date),
        )


def update_memo(memo_id, text, category=None):
    with _connect() as conn:
        if category is None:
            conn.execute("UPDATE memos SET text = %s WHERE id = %s", (text, memo_id))
        else:
            conn.execute(
                "UPDATE memos SET text = %s, category = %s WHERE id = %s",
                (text, category, memo_id),
            )


def delete_memo(memo_id):
    with _connect() as conn:
        conn.execute("DELETE FROM memos WHERE id = %s", (memo_id,))
