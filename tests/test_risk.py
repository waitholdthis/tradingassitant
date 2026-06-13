import pytest

from trading_assistant.risk import (
    TrailingStop,
    atr_bracket,
    atr_position_size,
    bracket,
    fixed_fractional_size,
    kelly_fraction,
    max_drawdown,
)


class TestFixedFractional:
    def test_with_stop_distance(self):
        # Risk $1000 (2% of 50k) at $5/share stop distance -> 200 shares
        assert fixed_fractional_size(50_000, 100.0, 0.02, stop_distance=5.0) == 200

    def test_capped_by_buying_power(self):
        # Tiny stop would imply more shares than equity can buy
        shares = fixed_fractional_size(10_000, 100.0, 0.02, stop_distance=0.01)
        assert shares == 100  # 10_000 / 100

    def test_no_stop_uses_full_price(self):
        assert fixed_fractional_size(100_000, 50.0, 0.02) == 40

    def test_validates_inputs(self):
        with pytest.raises(ValueError):
            fixed_fractional_size(-1, 100.0)
        with pytest.raises(ValueError):
            fixed_fractional_size(1000, 100.0, risk_fraction=0)


class TestAtrSizing:
    def test_matches_fixed_fractional(self):
        assert atr_position_size(50_000, 100.0, atr_value=2.5, risk_fraction=0.01) == \
            fixed_fractional_size(50_000, 100.0, 0.01, stop_distance=5.0)


class TestKelly:
    def test_positive_edge(self):
        # 60% win rate, 1:1 payoff -> kelly = 0.2
        assert kelly_fraction(0.6, 100, 100, cap=1.0) == pytest.approx(0.2)

    def test_capped(self):
        assert kelly_fraction(0.9, 200, 100, cap=0.25) == 0.25

    def test_negative_edge_returns_zero(self):
        assert kelly_fraction(0.3, 100, 100) == 0.0

    def test_invalid_win_rate(self):
        with pytest.raises(ValueError):
            kelly_fraction(1.5, 100, 100)


class TestBrackets:
    def test_reward_risk_ratio(self):
        levels = bracket(100.0, stop_pct=0.05, reward_risk=3.0)
        assert levels.stop_loss == pytest.approx(95.0)
        assert levels.take_profit == pytest.approx(115.0)

    def test_atr_bracket(self):
        levels = atr_bracket(100.0, atr_value=2.0, stop_mult=2.0, reward_risk=2.0)
        assert levels.stop_loss == pytest.approx(96.0)
        assert levels.take_profit == pytest.approx(108.0)


class TestTrailingStop:
    def test_ratchets_up_and_triggers(self):
        ts = TrailingStop(entry=100.0, trail_pct=0.10)
        assert not ts.update(105.0)
        assert not ts.update(120.0)
        assert ts.stop == pytest.approx(108.0)
        assert not ts.update(110.0)
        assert ts.stop == pytest.approx(108.0)  # never moves down
        assert ts.update(107.0)


class TestMaxDrawdown:
    def test_known_curve(self):
        assert max_drawdown([100, 120, 90, 110]) == pytest.approx(0.25)

    def test_monotonic_has_no_drawdown(self):
        assert max_drawdown([1, 2, 3, 4]) == 0.0

    def test_empty(self):
        assert max_drawdown([]) == 0.0
