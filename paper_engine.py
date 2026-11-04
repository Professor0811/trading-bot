import config


class PaperTradingEngine:
    def __init__(self, initial_capital=1000.0, max_concurrent=5):
        self.initial_capital = initial_capital
        self.cash_balance = initial_capital
        self.realized_pnl = 0.0
        self.max_concurrent = max_concurrent
        self.leverage = getattr(config, "LEVERAGE", 10)
        self.positions = {}
        self.daily_starting_capital = initial_capital

    def calculate_position_size(self) -> float:
        """2% isolated margin per trade."""
        total_equity = self.get_total_equity()
        margin = total_equity * config.POSITION_MARGIN_PERCENT
        return min(margin, self.cash_balance)

    def can_open_position(self, symbol: str) -> bool:
        if symbol in self.positions:
            return False
        if len(self.positions) >= self.max_concurrent:
            return False
        if self.cash_balance < (self.get_total_equity() * config.POSITION_MARGIN_PERCENT * 0.8):
            return False
        return True

    def execute_order(self, symbol: str, side: str, margin: float, entry_price: float, custom_atr: float = None) -> bool:
        if not self.can_open_position(symbol) or margin <= 0 or entry_price <= 0:
            return False

        leveraged_size = margin * self.leverage
        fee = leveraged_size * config.FUTURES_TAKER_FEE
        self.cash_balance -= (margin + fee)

        # Dynamic ATR Targets: SL = 1.5x ATR, TP = 3.0x ATR (1:2 R:R)
        if custom_atr and custom_atr > 0:
            sl_dist = custom_atr * 1.5
            tp_dist = custom_atr * 3.0
        else:
            sl_dist = entry_price * config.STOP_LOSS_PERCENT
            tp_dist = entry_price * config.TAKE_PROFIT_PERCENT

        # Safe liquidation distance (approx 8.5% at 10x)
        liq_distance = entry_price * ((1.0 / self.leverage) - config.MAINTENANCE_MARGIN_PERCENT)

        if side == "LONG":
            tp_price = entry_price + tp_dist
            sl_price = max(entry_price - sl_dist, entry_price - liq_distance * 0.95)
            liq_price = entry_price - liq_distance
        else:
            tp_price = max(0.00000001, entry_price - tp_dist)
            sl_price = min(entry_price + sl_dist, entry_price + liq_distance * 0.95)
            liq_price = entry_price + liq_distance

        self.positions[symbol] = {
            "side": side,
            "margin": margin,
            "leveraged_size": leveraged_size,
            "entry_price": entry_price,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "liq_price": liq_price,
            "peak_price": entry_price,
            "trailing_active": False,
            "atr_used": custom_atr or (entry_price * 0.01)
        }
        return True

    def check_exit_conditions_for_token(self, symbol: str, current_price: float):
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]
        side = pos["side"]
        entry = pos["entry_price"]
        tp = pos["tp_price"]
        sl = pos["sl_price"]
        liq = pos["liq_price"]
        trail_pct = config.TRAILING_STOP_PERCENT

        # 1. Liquidation Check
        if (side == "LONG" and current_price <= liq) or (side == "SHORT" and current_price >= liq):
            return self._close_token_position(symbol, "Liquidation", liq)

        # 2. Hard Stop-Loss Check
        if (side == "LONG" and current_price <= sl) or (side == "SHORT" and current_price >= sl):
            return self._close_token_position(symbol, "Dynamic ATR Stop-Loss", current_price)

        # 3. Take-Profit & Trailing Stop Activation
        if side == "LONG":
            if current_price >= tp:
                pos["trailing_active"] = True
            if current_price > pos["peak_price"]:
                pos["peak_price"] = current_price
            if pos["trailing_active"]:
                trail_price = pos["peak_price"] * (1.0 - trail_pct)
                if current_price <= trail_price:
                    return self._close_token_position(symbol, "Trailing Take-Profit", current_price)
        else:
            if current_price <= tp:
                pos["trailing_active"] = True
            if current_price < pos["peak_price"]:
                pos["peak_price"] = current_price
            if pos["trailing_active"]:
                trail_price = pos["peak_price"] * (1.0 + trail_pct)
                if current_price >= trail_price:
                    return self._close_token_position(symbol, "Trailing Take-Profit", current_price)

        return None

    def _close_token_position(self, symbol: str, reason: str, exit_price: float):
        pos = self.positions.pop(symbol, None)
        if not pos:
            return None

        side = pos["side"]
        entry = pos["entry_price"]
        margin = pos["margin"]
        exposure = pos["leveraged_size"]

        if reason == "Liquidation":
            pnl = -margin
        else:
            if side == "LONG":
                pnl = (exit_price - entry) / entry * exposure
            else:
                pnl = (entry - exit_price) / entry * exposure

        close_fee = exposure * config.FUTURES_TAKER_FEE
        net_pnl = pnl - close_fee
        returned_cash = max(0.0, margin + net_pnl)

        self.cash_balance += returned_cash
        self.realized_pnl += net_pnl

        return {
            "symbol": symbol,
            "side": side,
            "margin": margin,
            "entry_price": entry,
            "exit_price": exit_price,
            "pnl": net_pnl,
            "reason": reason
        }

    def get_total_equity(self) -> float:
        return self.cash_balance + sum(p["margin"] for p in self.positions.values())

    def is_circuit_breaker_triggered(self) -> bool:
        total_equity = self.get_total_equity()
        drawdown = (self.daily_starting_capital - total_equity) / self.daily_starting_capital
        return drawdown >= config.DAILY_LOSS_LIMIT_PERCENT
