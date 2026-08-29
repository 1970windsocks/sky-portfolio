import os

import psycopg
from psycopg.rows import dict_row


def _connect():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def list_memos(owner):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, owner, text, category, date, is_favorite FROM memos WHERE owner = %s ORDER BY id",
            (owner,),
        ).fetchall()
    return [dict(row) for row in rows]


def set_favorite(memo_id, owner, is_favorite):
    # ownerも一致条件に含めることで、他人のメモIDを指定されても操作できないようにする(テナント越境ゼロ)
    with _connect() as conn:
        conn.execute(
            "UPDATE memos SET is_favorite = %s WHERE id = %s AND owner = %s",
            (is_favorite, memo_id, owner),
        )


def insert_memo(owner, text, category="", date=""):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO memos (owner, text, category, date) VALUES (%s, %s, %s, %s)",
            (owner, text, category, date),
        )


def update_memo(memo_id, owner, text, category=None):
    # ownerも一致条件に含めることで、他人のメモIDを指定されても操作できないようにする(テナント越境ゼロ)
    with _connect() as conn:
        if category is None:
            conn.execute(
                "UPDATE memos SET text = %s WHERE id = %s AND owner = %s", (text, memo_id, owner)
            )
        else:
            conn.execute(
                "UPDATE memos SET text = %s, category = %s WHERE id = %s AND owner = %s",
                (text, category, memo_id, owner),
            )


def delete_memo(memo_id, owner):
    # ownerも一致条件に含めることで、他人のメモIDを指定されても削除できないようにする(テナント越境ゼロ)
    with _connect() as conn:
        conn.execute("DELETE FROM memos WHERE id = %s AND owner = %s", (memo_id, owner))
