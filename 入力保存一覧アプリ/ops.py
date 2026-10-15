import json
import urllib.request

# リポジトリはPublicなので、GitHub Actionsの実行履歴は認証無しで取得できる。
# 新しいDBテーブルや公開DBプロキシを用意せずに、直近の死活監視結果から
# 稼働率(SLO達成状況)を計算するために利用する。
WORKFLOW_RUNS_URL = (
    "https://api.github.com/repos/1970windsocks/sky-portfolio/actions/workflows/uptime.yml/runs"
)
SLO_TARGET = 99.5  # 目標稼働率(%)


def uptime_summary(per_page=100):
    """直近の死活監視ワークフロー実行結果から、稼働率とSLO達成状況を計算する。

    戻り値: {"total", "success", "percentage", "slo_target", "meets_slo"}
    取得できなかった場合はNoneを返す(呼び出し側で表示をスキップする)。
    """
    request = urllib.request.Request(
        f"{WORKFLOW_RUNS_URL}?per_page={per_page}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "input-save-app/1.0"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read())

    runs = [r for r in data.get("workflow_runs", []) if r.get("status") == "completed"]
    total = len(runs)
    if total == 0:
        return None

    success = len([r for r in runs if r.get("conclusion") == "success"])
    percentage = success / total * 100
    return {
        "total": total,
        "success": success,
        "percentage": percentage,
        "slo_target": SLO_TARGET,
        "meets_slo": percentage >= SLO_TARGET,
    }


CHECK_INTERVAL_MINUTES = 15  # uptime.ymlのcron間隔と合わせる


def error_budget_minutes(slo_target=SLO_TARGET, window_days=30):
    """第66課題: SLOから、window_days日間で許容されるダウンタイム(分)を計算する
    (エラーバジェット)。「なるべく落ちないように」ではなく、具体的に何分まで
    落ちてよいかを数字で決めるのがSREの考え方。"""
    total_minutes = window_days * 24 * 60
    return round(total_minutes * (1 - slo_target / 100), 1)


def error_budget_status(summary, window_days=30):
    """uptime_summary()の結果から、エラーバジェットの消費状況を見積もる。

    死活監視はCHECK_INTERVAL_MINUTES(15分)おきなので、1回の失敗は
    その間ずっと落ちていたとは限らないが、安全側に倒して
    「1回の失敗 ≈ 15分のダウンタイム」とみなす簡易な見積もり。
    summaryがNoneなら(稼働状況を取得できていない)Noneを返す。
    """
    if summary is None:
        return None
    failed = summary["total"] - summary["success"]
    used_minutes = failed * CHECK_INTERVAL_MINUTES
    budget_minutes = error_budget_minutes(summary["slo_target"], window_days)
    return {
        "window_days": window_days,
        "budget_minutes": budget_minutes,
        "used_minutes": used_minutes,
        "remaining_minutes": round(budget_minutes - used_minutes, 1),
        "over_budget": used_minutes > budget_minutes,
    }
