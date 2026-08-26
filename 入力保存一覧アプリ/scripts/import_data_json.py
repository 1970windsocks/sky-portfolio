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

import db  # noqa: E402
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

    for item in items:
        db.insert_memo(
            owner=item.get("owner", ""),
            text=item.get("text", ""),
            category=item.get("category", ""),
            date=item.get("date", ""),
        )

    print(f"{len(items)} 件を取り込みました。")


if __name__ == "__main__":
    main()
