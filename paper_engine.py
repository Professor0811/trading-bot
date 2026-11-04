import config


class PaperTradingEngine:
    def __init__(self, initial_capital=1000.0, max_concurrent=5, max_same_side=3):
        self.initial_capital = initial_capital
        self.cash_balance = initial_capital
        self.realized_pnl = 0.0
        self.max_concurrent = max_concurrent
        self.max_same_side = max_same_side  # Maximum 3 LONGs or 3 SHORTs concurrently
        self.leverage = getattr(config, "LEVERAGE", 10)
        self.positions = {}
        self.daily_starting_capital = initial_capital

    def calculate_position_size(self) -> float:
        """2% isolated margin per trade."""
        total_equity = self.get_total_equity()
        margin = total_equity * config.POSITION_MARGIN_PERCENT
        return min(margin, self.cash_balance)

    def can_open_position(self, symbol: str, side: str = None) -> bool:
        if symbol in self.positions:
            return False
        if len(self.positions) >= self.max_concurrent:
            return False
        if self.cash_balance < (self.get_total_equity() * config.POSITION_MARGIN_PERCENT * 0.8):
            return False

        # Directional Exposure Cap: Limit concurrent positions on the same side
        if side:
            current_side_count = sum(1 for p in self.positions.values() if p.get("side") == side)
            if current_side_count >= self.max_same_side:
                return False

        return True

    def execute_order(self, symbol: str, side: str, margin: float, entry_price: float, custom_atr: float = None) -> bool:
        if not self.can_open_position(symbol, side=side) or margin <= 0 or entry_price <= 0:
            return False

        leveraged_size = margin * self.leverage
        fee = leveraged_size * config.FUTURES_TAKER_FEE
        self.cash_balance -= (margin + fee)

        # Dynamic ATR Targets: Partial TP = 1.5x ATR, Full TP = 3.0x ATR, SL = 1.5x ATR
        if custom_atr and custom_atr > 0:
            sl_dist = custom_atr * 1.5
            partial_tp_dist = custom_atr * 1.5
            tp_dist = custom_atr * 3.0
        else:
            sl_dist = entry_price * config.STOP_LOSS_PERCENT
            partial_tp_dist = entry_price * (config.TAKE_PROFIT_PERCENT * 0.5)
            tp_dist = entry_price * config.TAKE_PROFIT_PERCENT

        liq_distance = entry_price * ((1.0 / self.leverage) - config.MAINTENANCE_MARGIN_PERCENT)

        if side == "LONG":
            partial_tp_price = entry_price + partial_tp_dist
            tp_price = entry_price + tp_dist
            sl_price = max(entry_price - sl_dist, entry_price - liq_distance * 0.95)
            liq_price = entry_price - liq_distance
        else:
            partial_tp_price = max(0.00000001, entry_price - partial_tp_dist)
            tp_price = max(0.00000001, entry_price - tp_dist)
            sl_price = min(entry_price + sl_dist, entry_price + liq_distance * 0.95)
            liq_price = entry_price + liq_distance

        self.positions[symbol] = {
            "side": side,
            "margin": margin,
            "leveraged_size": leveraged_size,
            "entry_price": entry_price,
            "partial_tp_price": partial_tp_price,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "liq_price": liq_price,
            "peak_price": entry_price,
            "trailing_active": False,
            "partial_tp_done": False,
            "atr_used": custom_atr or (entry_price * 0.01)
        }
        return True

    def check_exit_conditions_for_token(self, symbol: str, current_price: float):
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]
        side = pos["side"]
        entry = pos["entry_price"]
        partial_tp = pos.get("partial_tp_price", pos["tp_price"])
        tp = pos["tp_price"]
        sl = pos["sl_price"]
        liq = pos["liq_price"]
        trail_pct = config.TRAILING_STOP_PERCENT

        # 1. Liquidation Check
        if (side == "LONG" and current_price <= liq) or (side == "SHORT" and current_price >= liq):
            return self._close_token_position(symbol, "Liquidation", liq)

        # 2. Hard Stop-Loss / Break-Even Stop Check
        if (side == "LONG" and current_price <= sl) or (side == "SHORT" and current_price >= sl):
            reason_label = "Break-Even Stop (Risk-Free)" if pos.get("partial_tp_done") else "Dynamic ATR Stop-Loss"
            return self._close_token_position(symbol, reason_label, current_price)

        # 3. Auto Break-Even & 50% Partial Take-Profit at +1.5x ATR
        if not pos.get("partial_tp_done", False):
            if (side == "LONG" and current_price >= partial_tp) or (side == "SHORT" and current_price <= partial_tp):
                return self._scale_out_half_position(symbol, current_price)

        # 4. Full Take-Profit (3.0x ATR) & Trailing Stop Activation
        if side == "LONG":
            if current_price >= tp:
                pos["trailing_active"] = True
            if current_price > pos["peak_price"]:
                pos["peak_price"] = current_price
            if pos["trailing_active"]:
                trail_price = pos["peak_price"] * (1.0 - trail_pct)
                if current_price <= trail_price:
                    return self._close_token_position(symbol, "Trailing Full Take-Profit", current_price)
        else:
            if current_price <= tp:
                pos["trailing_active"] = True
            if current_price < pos["peak_price"]:
                pos["peak_price"] = current_price
            if pos["trailing_active"]:
                trail_price = pos["peak_price"] * (1.0 + trail_pct)
                if current_price >= trail_price:
                    return self._close_token_position(symbol, "Trailing Full Take-Profit", current_price)

        return None

    def _scale_out_half_position(self, symbol: str, current_price: float):
        pos = self.positions.get(symbol)
        if not pos:
            return None

        side = pos["side"]
        entry = pos["entry_price"]
        half_margin = pos["margin"] * 0.5
        half_exposure = pos["leveraged_size"] * 0.5

        if side == "LONG":
            pnl = (current_price - entry) / entry * half_exposure
            new_be_sl = entry * 1.0012
        else:
            pnl = (entry - current_price) / entry * half_exposure
            new_be_sl = entry * 0.9988

        close_fee = half_exposure * config.FUTURES_TAKER_FEE
        net_pnl = pnl - close_fee
        returned_cash = max(0.0, half_margin + net_pnl)

        self.cash_balance += returned_cash
        self.realized_pnl += net_pnl

        pos["margin"] -= half_margin
        pos["leveraged_size"] -= half_exposure
        pos["sl_price"] = new_be_sl
        pos["partial_tp_done"] = True

        return {
            "event_type": "PARTIAL",
            "symbol": symbol,
            "side": side,
            "closed_margin": half_margin,
            "remaining_margin": pos["margin"],
            "entry_price": entry,
            "exit_price": current_price,
            "new_sl_price": new_be_sl,
            "pnl": net_pnl,
            "reason": "50% Partial TP (1.5x ATR) + Auto Break-Even"
        }

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
            "event_type": "FULL",
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
