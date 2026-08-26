"""
backup_db.py で作ったJSONファイルから memos テーブルを復元する。

安全のため、デフォルトでは既存データは消さずに追記する。
既存データを全部消してから復元したい場合だけ --replace を付ける。

実行方法:
    railway ssh --service <サービス名> -- python scripts/restore_db.py /tmp/memos_backup_xxxx.json
    railway ssh --service <サービス名> -- python scripts/restore_db.py /tmp/memos_backup_xxxx.json --replace
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("使い方: python restore_db.py <バックアップJSONのパス> [--replace]")
        sys.exit(1)

    backup_path = Path(sys.argv[1])
    replace = "--replace" in sys.argv[2:]

    data = json.loads(backup_path.read_text(encoding="utf-8"))
    database_url = os.environ["DATABASE_URL"]

    with psycopg.connect(database_url, autocommit=True) as conn:
        if replace:
            conn.execute("TRUNCATE memos RESTART IDENTITY")
            print("既存データを全て削除しました(--replace指定)。")

        for item in data:
            # id列は自動採番に任せるため、バックアップ側の値は使わない
            columns = [k for k in item if k != "id"]
            placeholders = ", ".join(f"%({c})s" for c in columns)
            conn.execute(
                f"INSERT INTO memos ({', '.join(columns)}) VALUES ({placeholders})",
                item,
            )

    print(f"{len(data)} 件を復元しました。")


if __name__ == "__main__":
    main()
