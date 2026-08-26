"""
memosテーブルの内容をJSONファイルにバックアップする。

実行方法(本番/staging問わず、対象のサービスに対して):
    railway ssh --service <サービス名> -- python scripts/backup_db.py

保存先はコンテナ内の一時領域なので、この後 `railway ssh -- cat <パス>` などで
中身を取り出し、手元のパソコンにも保存しておくこと。
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402


def main():
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute("SELECT * FROM memos ORDER BY id").fetchall()

    data = [dict(row) for row in rows]
    for item in data:
        for key, value in item.items():
            if hasattr(value, "isoformat"):
                item[key] = value.isoformat()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(f"/tmp/memos_backup_{timestamp}.json")
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{len(data)} 件を {out_path} に保存しました。")
    print("--- 内容(このJSONをコピーして手元にも保存しておく) ---")
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
