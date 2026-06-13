import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import notify


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """Reset channels and cooldowns; capture HTTP posts instead of sending."""
    monkeypatch.setattr(config, "NTFY_TOPIC", "")
    monkeypatch.setattr(config, "PUSHOVER_TOKEN", "")
    monkeypatch.setattr(config, "PUSHOVER_USER", "")
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    notify._last_pushed.clear()
    posts = []
    monkeypatch.setattr(notify, "_post", lambda url, data, headers: posts.append(
        {"url": url, "data": data, "headers": headers}))
    yield posts
    notify._last_pushed.clear()


def buy_result(ticker="AAPL", score=85, confidence="STRONG"):
    return {
        "ticker": ticker,
        "signal": "BUY",
        "score": score,
        "confidence": confidence,
        "risk": "MEDIUM",
        "reasons": ["Supertrend BULLISH", "MACD bullish crossover"],
        "indicators": {"price": 200.0, "atr": 4.0},
    }


class TestTradePlan:
    def test_buy_plan_uses_2_atr_stop(self):
        plan = notify.build_trade_plan(price=200.0, atr=4.0, signal="BUY")
        assert plan["stop"] == pytest.approx(192.0)
        assert plan["target"] == pytest.approx(216.0)  # 2:1 reward:risk

    def test_sell_plan_is_mirrored(self):
        plan = notify.build_trade_plan(price=200.0, atr=4.0, signal="SELL")
        assert plan["stop"] == pytest.approx(208.0)
        assert plan["target"] == pytest.approx(184.0)

    def test_falls_back_to_pct_stop_without_atr(self):
        plan = notify.build_trade_plan(price=100.0, atr=0.0, signal="BUY")
        assert plan["stop"] == pytest.approx(95.0)

    def test_shares_risk_configured_fraction(self, monkeypatch):
        monkeypatch.setattr(config, "ACCOUNT_EQUITY", 10_000.0)
        monkeypatch.setattr(config, "RISK_PER_TRADE", 0.01)
        plan = notify.build_trade_plan(price=200.0, atr=4.0, signal="BUY")
        # $100 risk budget / $8 per-share risk = 12 shares
        assert plan["shares"] == 12

    def test_invalid_price_returns_none(self):
        assert notify.build_trade_plan(price=0, atr=1.0, signal="BUY") is None


class TestFormatting:
    def test_title_and_plan_in_body(self):
        title, body, urgent = notify.format_message(buy_result())
        assert "BUY AAPL" in title
        assert "85/100" in title
        assert urgent is True
        assert "stop 192" in body
        assert "Supertrend BULLISH" in body
        assert "Not financial advice" in body

    def test_moderate_is_not_urgent(self):
        _, _, urgent = notify.format_message(buy_result(confidence="MODERATE"))
        assert urgent is False

    def test_reads_flattened_dashboard_dict(self):
        flat = {"ticker": "TSLA", "signal": "SELL", "score": 20,
                "confidence": "STRONG", "risk": "HIGH", "reasons": [],
                "price": 300.0, "atr": 9.0}
        title, body, _ = notify.format_message(flat)
        assert "SELL TSLA" in title
        assert "exit/tighten stop to 318" in body


class TestDispatch:
    def test_no_channels_pushes_nothing(self, clean_state):
        assert notify.dispatch([buy_result()]) == 0
        assert clean_state == []

    def test_pushes_actionable_only(self, monkeypatch, clean_state):
        monkeypatch.setattr(config, "NTFY_TOPIC", "test-topic")
        results = [
            buy_result("AAPL", score=85),
            {**buy_result("HOLDCO"), "signal": "HOLD", "score": 50},
            {**buy_result("WEAK"), "score": 55},  # below MIN_SIGNAL_SCORE
            {**buy_result("SELLY"), "signal": "SELL", "score": 15},
        ]
        assert notify.dispatch(results) == 2
        urls = [p["url"] for p in clean_state]
        assert all(u == "https://ntfy.sh/test-topic" for u in urls)

    def test_cooldown_blocks_repeat_push(self, monkeypatch, clean_state):
        monkeypatch.setattr(config, "NTFY_TOPIC", "test-topic")
        assert notify.dispatch([buy_result()]) == 1
        assert notify.dispatch([buy_result()]) == 0  # still cooling down
        assert len(clean_state) == 1

    def test_multi_channel_fanout(self, monkeypatch, clean_state):
        monkeypatch.setattr(config, "NTFY_TOPIC", "t")
        monkeypatch.setattr(config, "PUSHOVER_TOKEN", "tok")
        monkeypatch.setattr(config, "PUSHOVER_USER", "usr")
        monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "bot")
        monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
        assert notify.dispatch([buy_result()]) == 1
        assert len(clean_state) == 3

    def test_urgent_priority_header_for_strong(self, monkeypatch, clean_state):
        monkeypatch.setattr(config, "NTFY_TOPIC", "t")
        notify.dispatch([buy_result(confidence="STRONG")])
        assert clean_state[0]["headers"]["Priority"] == "urgent"

    def test_channel_failure_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(config, "NTFY_TOPIC", "t")
        monkeypatch.setattr(notify, "_post", lambda *a: (_ for _ in ()).throw(OSError("down")))
        monkeypatch.setattr(notify, "_RETRIES", 0)
        assert notify.dispatch([buy_result()]) == 0  # failed but no exception


def test_send_test_reports_missing_config(capsys):
    assert notify.send_test() is False
    assert "No push channels configured" in capsys.readouterr().out
