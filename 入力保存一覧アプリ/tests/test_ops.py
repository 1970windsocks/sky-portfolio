import json
from unittest.mock import MagicMock

import ops


def _fake_response(payload):
    body = json.dumps(payload).encode("utf-8")
    response = MagicMock()
    response.read.return_value = body
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def test_uptime_summary_calculates_percentage(monkeypatch):
    payload = {
        "workflow_runs": [
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "failure"},
            {"status": "in_progress", "conclusion": None},  # 未完了は集計対象外
        ]
    }
    monkeypatch.setattr(
        ops.urllib.request, "urlopen", lambda request, timeout=10: _fake_response(payload)
    )

    summary = ops.uptime_summary()

    assert summary["total"] == 4
    assert summary["success"] == 3
    assert summary["percentage"] == 75.0
    assert summary["slo_target"] == ops.SLO_TARGET
    assert summary["meets_slo"] is False


def test_uptime_summary_meets_slo_when_all_success(monkeypatch):
    payload = {"workflow_runs": [{"status": "completed", "conclusion": "success"}] * 10}
    monkeypatch.setattr(
        ops.urllib.request, "urlopen", lambda request, timeout=10: _fake_response(payload)
    )

    summary = ops.uptime_summary()

    assert summary["percentage"] == 100.0
    assert summary["meets_slo"] is True


def test_uptime_summary_returns_none_when_no_completed_runs(monkeypatch):
    payload = {"workflow_runs": []}
    monkeypatch.setattr(
        ops.urllib.request, "urlopen", lambda request, timeout=10: _fake_response(payload)
    )

    assert ops.uptime_summary() is None
