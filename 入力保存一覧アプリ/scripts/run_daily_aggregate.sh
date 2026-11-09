#!/bin/sh
# 第81課題: 毎日手で打っていた
#   railway ssh -- python scripts/aggregate_daily_stats.py
# を1本にまとめた。失敗したら即止まるようにし(set -e)、
# 開始・終了をログに残す。
set -e

echo "=== 日次集計を開始: $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
python scripts/aggregate_daily_stats.py
echo "=== 日次集計を終了: $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
