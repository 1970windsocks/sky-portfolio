import json
from unittest.mock import MagicMock

import pytest

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


def test_error_budget_minutes_matches_hand_calculation():
    # SLO 99.5%・30日間なら、許容ダウンタイムは 30*24*60*0.005 = 216分
    assert ops.error_budget_minutes(slo_target=99.5, window_days=30) == 216.0
    # SLO 99.9%ならもっと厳しくなる(許容分数は減る)
    assert ops.error_budget_minutes(slo_target=99.9, window_days=30) == pytest.approx(43.2)


def test_error_budget_status_returns_none_without_summary():
    assert ops.error_budget_status(None) is None


def test_error_budget_status_computes_remaining_budget():
    # 実測(2026-10-15時点の本番): 直近100回の死活監視のうち1回失敗、稼働率99.00%
    summary = {
        "total": 100,
        "success": 99,
        "percentage": 99.0,
        "slo_target": 99.5,
        "meets_slo": False,
    }

    status = ops.error_budget_status(summary)

    assert status["budget_minutes"] == 216.0
    assert status["used_minutes"] == ops.CHECK_INTERVAL_MINUTES  # 失敗1回分
    assert status["remaining_minutes"] == 216.0 - ops.CHECK_INTERVAL_MINUTES
    assert status["over_budget"] is False


def test_error_budget_status_flags_over_budget_when_too_many_failures():
    summary = {
        "total": 100,
        "success": 50,  # 50回失敗 = 750分相当のダウンタイム、216分の予算を大幅に超える
        "percentage": 50.0,
        "slo_target": 99.5,
        "meets_slo": False,
    }

    status = ops.error_budget_status(summary)

    assert status["over_budget"] is True
    assert status["remaining_minutes"] < 0
