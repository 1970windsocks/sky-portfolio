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
