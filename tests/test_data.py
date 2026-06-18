from datetime import date

import pytest

from trading_assistant.data import Bar, OHLCV, load_csv, returns, synthetic_series


def test_bar_validates_ohlc_consistency():
    with pytest.raises(ValueError):
        Bar(date(2025, 1, 1), open=100, high=99, low=101, close=100)
    with pytest.raises(ValueError):
        Bar(date(2025, 1, 1), open=200, high=110, low=90, close=100)


def test_synthetic_series_is_reproducible():
    a = synthetic_series(days=100, seed=5)
    b = synthetic_series(days=100, seed=5)
    assert a.closes == b.closes
    assert len(a) == 100


def test_synthetic_series_skips_weekends():
    s = synthetic_series(days=50, seed=1)
    assert all(d.weekday() < 5 for d in s.dates)


def test_slice_by_date():
    s = synthetic_series(days=100, seed=1)
    mid = s.dates[50]
    sliced = s.slice(start=mid)
    assert sliced.dates[0] == mid
    assert len(sliced) == 50


def test_validate_rejects_unordered():
    bars = [
        Bar(date(2025, 1, 2), 1, 1, 1, 1),
        Bar(date(2025, 1, 1), 1, 1, 1, 1),
    ]
    with pytest.raises(ValueError, match="strictly increasing"):
        OHLCV("X", bars).validate()


def test_returns():
    assert returns([100, 110, 99]) == [pytest.approx(0.1), pytest.approx(-0.1)]


def test_load_csv(tmp_path):
    csv_path = tmp_path / "TEST.csv"
    csv_path.write_text(
        "Date,Open,High,Low,Close,Volume\n"
        "2025-01-03,101,103,100,102,2000\n"
        "2025-01-02,100,102,99,101,1000\n"  # out of order on purpose
    )
    s = load_csv(str(csv_path))
    assert s.symbol == "TEST"
    assert len(s) == 2
    assert s.dates == [date(2025, 1, 2), date(2025, 1, 3)]  # sorted
    assert s.closes == [101.0, 102.0]


def test_load_csv_prefers_adj_close(tmp_path):
    csv_path = tmp_path / "adj.csv"
    csv_path.write_text(
        "Date,Open,High,Low,Close,Adj Close,Volume\n"
        "2025-01-02,100,110,90,105,100,1000\n"
    )
    s = load_csv(str(csv_path), symbol="ADJ")
    assert s.closes == [100.0]


def test_load_csv_missing_columns(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("Date,Price\n2025-01-02,100\n")
    with pytest.raises(ValueError, match="missing columns"):
        load_csv(str(csv_path))
