"""
既存の data.json を Postgres の memos テーブルへ1回だけ取り込むスクリプト。

使い方 (Railway上のPostgresに向けて実行する場合):
    railway run python scripts/import_data_json.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402

import migrate  # noqa: E402

DATA_FILE = Path(__file__).resolve().parent.parent / "data.json"


def main():
    database_url = os.environ["DATABASE_URL"]
    migrate.run_pending_migrations(database_url)

    if not DATA_FILE.exists():
        print(f"{DATA_FILE} が見つかりません。何も取り込みません。")
        return

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        items = json.load(f)

    if not items:
        print("取り込むデータがありません。")
        return

    # 直す前: db.insert_memo()をitemの数だけ呼ぶと、その回数だけ接続を開き直していた
    # (N+1と同じ落とし穴。1件ごとに接続・INSERT・切断を繰り返すため件数に比例して遅くなる)。
    # 直した後: 接続を1回だけ開き、全件を1本のINSERT文にまとめて取り込む。
    rows = [
        (
            item.get("owner", ""),
            item.get("text", ""),
            item.get("category", ""),
            item.get("date", ""),
        )
        for item in items
    ]
    placeholders = ", ".join(["(%s, %s, %s, %s)"] * len(rows))
    flat_params = [value for row in rows for value in row]

    with psycopg.connect(database_url) as conn:
        conn.execute(
            f"INSERT INTO memos (owner, text, category, date) VALUES {placeholders}",
            flat_params,
        )

    print(f"{len(items)} 件を取り込みました。(接続1回・INSERT1回)")


if __name__ == "__main__":
    main()
