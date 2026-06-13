import pytest

from trading_assistant.cli import main


def test_analyze_demo(capsys):
    assert main(["analyze", "--demo"]) == 0
    out = capsys.readouterr().out
    assert "DEMO" in out
    assert "Trend:" in out
    assert "RSI(14)" in out


def test_backtest_demo(capsys):
    assert main(["backtest", "--demo", "--strategy", "sma"]) == 0
    out = capsys.readouterr().out
    assert "Sharpe:" in out
    assert "buy & hold" in out


def test_backtest_ensemble(capsys):
    assert main(["backtest", "--demo", "--strategy", "ensemble"]) == 0
    assert "ensemble" in capsys.readouterr().out


def test_compare_demo(capsys):
    assert main(["compare", "--demo"]) == 0
    out = capsys.readouterr().out
    for name in ["sma", "rsi", "macd", "bollinger", "donchian", "ensemble", "buy_and_hold"]:
        assert name in out


def test_size_with_atr(capsys):
    assert main(["size", "--equity", "50000", "--price", "100", "--atr", "2.5"]) == 0
    out = capsys.readouterr().out
    assert "Shares:      100" in out  # 1% of 50k = 500 risk / (2.5 * 2) stop
    assert "Stop loss:   95.00" in out


def test_size_with_pct_stop(capsys):
    assert main(["size", "--equity", "50000", "--price", "100", "--stop-pct", "0.05"]) == 0
    assert "Take profit: 110.00" in capsys.readouterr().out


def test_missing_data_source_errors():
    with pytest.raises(SystemExit):
        main(["analyze"])


def test_bad_csv_path_reports_error(capsys):
    assert main(["analyze", "--csv", "/nonexistent/file.csv"]) == 1
    assert "error:" in capsys.readouterr().err


def test_analyze_from_csv(tmp_path, capsys):
    rows = ["Date,Open,High,Low,Close,Volume"]
    from datetime import date, timedelta

    d = date(2024, 1, 1)
    price = 100.0
    for i in range(120):
        if d.weekday() < 5:
            rows.append(f"{d},{price},{price * 1.01},{price * 0.99},{price * 1.002},10000")
            price *= 1.002
        d += timedelta(days=1)
    csv_path = tmp_path / "UP.csv"
    csv_path.write_text("\n".join(rows) + "\n")

    assert main(["analyze", "--csv", str(csv_path)]) == 0
    out = capsys.readouterr().out
    assert "UP" in out
    assert "uptrend" in out
