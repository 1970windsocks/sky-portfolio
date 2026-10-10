"""
第61課題(データエンジニアリング): audit_logの生ログを、日ごと・action種別ごとの
件数に集計してdaily_action_statsに貯めるバッチパイプライン。

  ① 集める  : 対象日のaudit_logを全件取得
  ② 整える  : action種別ごとにgroup byして件数に集約(username/detailなど
              個別の中身は捨て、「日付・action・件数」の3列だけに正規化する)
  ③ 貯める  : daily_action_statsにUPSERT(同じ日に2回実行しても壊れない)

対象日を指定しなければ「昨日」を集計する(1日分のログが出揃っている保証がある日)。
UTCの日付境界で区切る(audit_log.created_atがTIMESTAMPTZ、DBの日付関数もUTC基準のため)。

実行方法:
    railway ssh --service <サービス名> -- python scripts/aggregate_daily_stats.py
    railway ssh --service <サービス名> -- python scripts/aggregate_daily_stats.py 2026-10-08  # 日付を指定
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402


def aggregate_daily_stats(database_url, target_date):
    """target_date(UTC基準)1日分のaudit_logを集計し、daily_action_statsにUPSERTする。
    戻り値: [{"action": ..., "count": ...}, ...] (保存した内容、確認用)"""
    with psycopg.connect(database_url) as conn:
        # ① 集める + ② 整える: action種別ごとのcountに集約してから取り出す
        #    (生のaudit_log行を1件ずつPythonに持ってくるのではなく、
        #    SQL側で集約してから結果だけ受け取ることで、転送量も処理も最小限にする)
        rows = conn.execute(
            """
            SELECT action, count(*) AS count
            FROM audit_log
            WHERE created_at >= %s AND created_at < %s
            GROUP BY action
            ORDER BY action
            """,
            (target_date, target_date + timedelta(days=1)),
        ).fetchall()

        # ③ 貯める: 同じ日に再実行されても結果が変わらないよう、UPSERTにしておく
        for action, count in rows:
            conn.execute(
                """
                INSERT INTO daily_action_stats (stat_date, action, count, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (stat_date, action)
                DO UPDATE SET count = EXCLUDED.count, updated_at = now()
                """,
                (target_date, action, count),
            )

    return [{"action": action, "count": count} for action, count in rows]


def main():
    database_url = os.environ["DATABASE_URL"]
    if len(sys.argv) > 1:
        target_date = date.fromisoformat(sys.argv[1])
    else:
        target_date = date.today() - timedelta(days=1)

    result = aggregate_daily_stats(database_url, target_date)

    print(f"{target_date} のaudit_logを集計し、daily_action_statsに保存しました。")
    if not result:
        print("  (対象日の記録はありませんでした)")
    for item in result:
        print(f"  {item['action']}: {item['count']}件")


if __name__ == "__main__":
    main()
