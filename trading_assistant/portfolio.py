"""Portfolio tracking: positions, cash, and P&L, with JSON persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class Position:
    symbol: str
    shares: float
    avg_cost: float

    @property
    def cost_basis(self) -> float:
        return self.shares * self.avg_cost

    def market_value(self, price: float) -> float:
        return self.shares * price

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.avg_cost) * self.shares


@dataclass
class Portfolio:
    cash: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    history: list[dict] = field(default_factory=list)

    def buy(self, symbol: str, shares: float, price: float, when: date | None = None) -> None:
        if shares <= 0 or price <= 0:
            raise ValueError("shares and price must be positive")
        cost = shares * price
        if cost > self.cash + 1e-9:
            raise ValueError(f"insufficient cash: need ${cost:,.2f}, have ${self.cash:,.2f}")
        self.cash -= cost
        symbol = symbol.upper()
        pos = self.positions.get(symbol)
        if pos:
            total_shares = pos.shares + shares
            pos.avg_cost = (pos.cost_basis + cost) / total_shares
            pos.shares = total_shares
        else:
            self.positions[symbol] = Position(symbol, shares, price)
        self._log("buy", symbol, shares, price, when)

    def sell(self, symbol: str, shares: float, price: float, when: date | None = None) -> float:
        if shares <= 0 or price <= 0:
            raise ValueError("shares and price must be positive")
        symbol = symbol.upper()
        pos = self.positions.get(symbol)
        if pos is None or pos.shares < shares - 1e-9:
            held = pos.shares if pos else 0
            raise ValueError(f"cannot sell {shares} {symbol}: hold {held}")
        proceeds = shares * price
        pnl = (price - pos.avg_cost) * shares
        self.cash += proceeds
        self.realized_pnl += pnl
        pos.shares -= shares
        if pos.shares < 1e-9:
            del self.positions[symbol]
        self._log("sell", symbol, shares, price, when)
        return pnl

    def deposit(self, amount: float) -> None:
        if amount <= 0:
            raise ValueError("deposit must be positive")
        self.cash += amount
        self._log("deposit", "", 0, amount, None)

    def total_value(self, prices: dict[str, float]) -> float:
        value = self.cash
        for symbol, pos in self.positions.items():
            if symbol not in prices:
                raise KeyError(f"no price provided for held position {symbol}")
            value += pos.market_value(prices[symbol])
        return value

    def unrealized_pnl(self, prices: dict[str, float]) -> float:
        return sum(
            pos.unrealized_pnl(prices[sym]) for sym, pos in self.positions.items() if sym in prices
        )

    def weights(self, prices: dict[str, float]) -> dict[str, float]:
        """Allocation by market value, including cash under the key ``CASH``."""
        total = self.total_value(prices)
        if total <= 0:
            return {}
        w = {sym: pos.market_value(prices[sym]) / total for sym, pos in self.positions.items()}
        w["CASH"] = self.cash / total
        return w

    def _log(self, action: str, symbol: str, shares: float, price: float, when: date | None) -> None:
        self.history.append(
            {
                "date": (when or date.today()).isoformat(),
                "action": action,
                "symbol": symbol,
                "shares": shares,
                "price": price,
            }
        )

    # --- persistence ---

    def save(self, path: str | Path) -> None:
        payload = {
            "cash": self.cash,
            "realized_pnl": self.realized_pnl,
            "positions": [
                {"symbol": p.symbol, "shares": p.shares, "avg_cost": p.avg_cost}
                for p in self.positions.values()
            ],
            "history": self.history,
        }
        Path(path).write_text(json.dumps(payload, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "Portfolio":
        payload = json.loads(Path(path).read_text())
        pf = cls(
            cash=payload["cash"],
            realized_pnl=payload.get("realized_pnl", 0.0),
            history=payload.get("history", []),
        )
        for p in payload.get("positions", []):
            pf.positions[p["symbol"]] = Position(p["symbol"], p["shares"], p["avg_cost"])
        return pf
