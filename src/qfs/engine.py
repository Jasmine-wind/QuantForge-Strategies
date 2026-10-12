"""One position, linear USDT account, chronological funding and 1m market fills."""
from dataclasses import dataclass

import pandas as pd

from .config import Config
from .data import MarketData
from .strategies import indicators, decision


TRADE_COLUMNS = ["direction", "quantity", "signed_quantity", "entry_time", "exit_time",
                 "entry_reference", "entry_fill", "exit_reference", "exit_fill",
                 "gross_pnl", "net_pnl", "entry_fee", "exit_fee", "fees",
                 "entry_slippage", "exit_slippage", "slippage", "funding",
                 "holding_hours", "exit_reason"]


@dataclass
class Account:
    wallet: float
    fee_rate: float
    slippage_rate: float
    position: dict | None = None

    @property
    def direction(self):
        return 0 if self.position is None else (1 if self.position["signed_quantity"] > 0 else -1)

    def equity(self, mark):
        return self.wallet + self.unrealized(mark)

    def unrealized(self, mark):
        if self.position is None:
            return 0.0
        return self.position["signed_quantity"] * (mark - self.position["entry_fill"])

    def fill(self, reference, side, quantity):
        price = reference * (1 + side * self.slippage_rate)
        return price, abs(quantity * price) * self.fee_rate, abs(quantity) * abs(price - reference)

    def open(self, time, reference, direction, fraction, mark):
        if self.position is not None:
            raise ValueError("account: cannot stack positions")
        notional = self.equity(mark) * fraction
        if notional <= 0:
            raise ValueError("account: non-positive entry equity")
        price = reference * (1 + direction * self.slippage_rate)
        quantity = notional / price
        price, fee, slip = self.fill(reference, direction, quantity)
        self.wallet -= fee
        self.position = {"direction": "long" if direction == 1 else "short", "quantity": quantity,
                         "signed_quantity": direction * quantity, "entry_time": time.isoformat(),
                         "entry_reference": reference, "entry_fill": price,
                         "entry_fee": fee, "entry_slippage": slip, "funding": 0.0}

    def settle(self, rate, mark):
        if self.position is None:
            return 0.0
        cash = -self.position["signed_quantity"] * mark * rate
        self.wallet += cash
        self.position["funding"] += cash
        return cash

    def close(self, time, reference, reason):
        if self.position is None:
            raise ValueError("account: cannot close a flat account")
        p = self.position
        price, fee, slip = self.fill(reference, -self.direction, p["quantity"])
        gross = p["signed_quantity"] * (price - p["entry_fill"])
        self.wallet += gross - fee
        trade = p | {"exit_time": time.isoformat(), "exit_reference": reference, "exit_fill": price,
                     "gross_pnl": gross, "net_pnl": gross - p["entry_fee"] - fee + p["funding"],
                     "exit_fee": fee, "fees": p["entry_fee"] + fee,
                     "exit_slippage": slip, "slippage": p["entry_slippage"] + slip,
                     "holding_hours": (time - pd.Timestamp(p["entry_time"])).total_seconds() / 3600,
                     "exit_reason": reason}
        self.position = None
        return trade


@dataclass(frozen=True)
class Result:
    trades: pd.DataFrame
    equity: pd.DataFrame
    invalid_time: str | None
    invalid_reason: str | None


def run_backtest(config: Config, data: MarketData):
    account = Account(config.initial_equity, config.taker_fee_rate, config.slippage_rate)
    benchmark = config.strategy["name"] in {"cash", "btc_perpetual_long_hold"}
    if benchmark:
        signal_rows = {}
    else:
        features = indicators(data.bars.close, config.strategy)
        signal_rows = {t + pd.Timedelta(hours=4): i for i, t in enumerate(features.index)
                       if config.start <= t + pd.Timedelta(hours=4) < config.end and i > 0}
    funding_rows = list(data.funding.itertuples())
    fund_i = 0
    target = 1 if config.strategy["name"] == "btc_perpetual_long_hold" else 0
    pending = None
    trades, curve = [], []
    invalid_time = invalid_reason = None

    def check_equity(time, mark):
        nonlocal invalid_time, invalid_reason
        if invalid_time is None and account.equity(mark) <= 0:
            invalid_time, invalid_reason = time.isoformat(), "non_positive_equity"

    def snapshot(time, mark, event):
        curve.append({"time": time.isoformat(), "wallet": account.wallet,
                      "unrealized_pnl": account.unrealized(mark), "equity": account.equity(mark),
                      "mark_price": mark, "event": event})
        check_equity(time, mark)

    snapshot(config.start, float(data.mark.iloc[0].mark_open), "initial")
    for trade_row, mark_row in zip(data.trade.itertuples(), data.mark.itertuples(), strict=True):
        time, mark = trade_row.Index, mark_row.mark_open
        minute_end = time + pd.Timedelta(minutes=1)
        # Funding exactly at T applies only to the pre-T position.
        while fund_i < len(funding_rows) and funding_rows[fund_i].Index == time:
            f = funding_rows[fund_i]
            account.settle(f.funding_rate, f.funding_mark_price)
            check_equity(f.Index, f.funding_mark_price)
            fund_i += 1
        check_equity(time, mark)
        if time in signal_rows:
            i = signal_rows[time]
            signal = decision(config.strategy["name"], features.iloc[i - 1], features.iloc[i], account.direction)
            if signal is not None:
                target = signal
        if account.direction and target != account.direction:
            trades.append(account.close(time, trade_row.open, "reverse_signal" if target else "strategy_exit"))
            check_equity(time, mark)
            pending = (minute_end, target) if target else None
        elif account.direction == 0:
            if pending is not None:
                due, direction = pending
                if time >= due:
                    if target == direction and invalid_time is None:
                        account.open(time, trade_row.open, direction, config.position_fraction, mark)
                    pending = None
            elif target and invalid_time is None:
                account.open(time, trade_row.open, target, config.position_fraction, mark)
        check_equity(time, mark)
        # Real settlement archives sometimes use millisecond timestamps inside a minute.
        while fund_i < len(funding_rows) and funding_rows[fund_i].Index < minute_end:
            f = funding_rows[fund_i]
            account.settle(f.funding_rate, f.funding_mark_price)
            check_equity(f.Index, f.funding_mark_price)
            fund_i += 1
        snapshot(minute_end, mark_row.mark_close, "mark_close")
    if account.position is not None:
        trades.append(account.close(config.end, float(data.trade.iloc[-1].close), "end_of_test"))
        snapshot(config.end, float(data.mark.iloc[-1].mark_close), "end_of_test")
    return Result(pd.DataFrame(trades, columns=TRADE_COLUMNS), pd.DataFrame(curve), invalid_time, invalid_reason)
