import pytest

from trading_assistant.portfolio import Portfolio


@pytest.fixture
def pf():
    p = Portfolio(cash=10_000.0)
    return p


def test_buy_reduces_cash_and_opens_position(pf):
    pf.buy("aapl", 10, 150.0)
    assert pf.cash == pytest.approx(8_500.0)
    assert pf.positions["AAPL"].shares == 10
    assert pf.positions["AAPL"].avg_cost == 150.0


def test_buy_averages_cost(pf):
    pf.buy("AAPL", 10, 100.0)
    pf.buy("AAPL", 10, 200.0)
    assert pf.positions["AAPL"].avg_cost == pytest.approx(150.0)
    assert pf.positions["AAPL"].shares == 20


def test_insufficient_cash_rejected(pf):
    with pytest.raises(ValueError, match="insufficient cash"):
        pf.buy("AAPL", 1000, 150.0)


def test_sell_realizes_pnl(pf):
    pf.buy("AAPL", 10, 100.0)
    pnl = pf.sell("AAPL", 10, 120.0)
    assert pnl == pytest.approx(200.0)
    assert pf.realized_pnl == pytest.approx(200.0)
    assert "AAPL" not in pf.positions
    assert pf.cash == pytest.approx(10_200.0)


def test_cannot_oversell(pf):
    pf.buy("AAPL", 5, 100.0)
    with pytest.raises(ValueError, match="cannot sell"):
        pf.sell("AAPL", 10, 100.0)


def test_total_value_and_weights(pf):
    pf.buy("AAPL", 10, 100.0)  # cash now 9000
    prices = {"AAPL": 110.0}
    assert pf.total_value(prices) == pytest.approx(10_100.0)
    w = pf.weights(prices)
    assert w["AAPL"] == pytest.approx(1_100.0 / 10_100.0)
    assert w["CASH"] == pytest.approx(9_000.0 / 10_100.0)
    assert sum(w.values()) == pytest.approx(1.0)


def test_total_value_requires_prices_for_held(pf):
    pf.buy("AAPL", 1, 100.0)
    with pytest.raises(KeyError):
        pf.total_value({})


def test_save_and_load_roundtrip(pf, tmp_path):
    pf.buy("AAPL", 10, 100.0)
    pf.sell("AAPL", 5, 120.0)
    path = tmp_path / "portfolio.json"
    pf.save(path)
    loaded = Portfolio.load(path)
    assert loaded.cash == pf.cash
    assert loaded.realized_pnl == pf.realized_pnl
    assert loaded.positions["AAPL"].shares == 5
    assert len(loaded.history) == len(pf.history)
