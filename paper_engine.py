from datetime import datetime
import config

class PaperTradingEngine:
    def __init__(self, initial_capital: float = 1000.0, max_concurrent: int = 3):
        self.cash_balance = initial_capital
        self.initial_capital = initial_capital
        self.max_concurrent = max_concurrent
        self.leverage = getattr(config, "LEVERAGE", 5)
        # Positions dict: {"SOL/USDC": {...}, ...}
        self.positions = {}
        self.realized_pnl = 0.0
        self.day_start_balance = initial_capital

    @property
    def active_position(self):
        if self.positions:
            return next(iter(self.positions.values()))
        return None

    def calculate_position_size(self) -> float:
        """Returns 2% of current total equity as isolated margin collateral."""
        current_equity = self.cash_balance + sum(p.get("margin", 0.0) for p in self.positions.values())
        margin_size = current_equity * config.POSITION_MARGIN_PERCENT
        return max(5.0, round(margin_size, 2))

    def is_circuit_breaker_triggered(self) -> bool:
        """Triggers if daily net loss hits 10% of day-start capital."""
        current_equity = self.cash_balance + sum(p.get("margin", 0.0) for p in self.positions.values())
        loss = self.day_start_balance - current_equity
        max_allowed_loss = self.day_start_balance * config.DAILY_LOSS_LIMIT_PERCENT
        return loss >= max_allowed_loss

    def can_open_position(self, symbol: str) -> bool:
        if len(self.positions) >= self.max_concurrent:
            return False
        if symbol in self.positions:
            return False
        if self.is_circuit_breaker_triggered():
            return False
        return True

    def execute_order(self, symbol: str, side: str, margin: float, price: float):
        """
        Executes a 5x Leveraged Long or Short order using isolated margin.
        side: 'LONG' (or 'BUY') / 'SHORT' (or 'SELL')
        """
        side = "LONG" if side in ["LONG", "BUY"] else "SHORT"

        if not self.can_open_position(symbol):
            return False

        if self.cash_balance < margin:
            return False

        # Deduct margin from cash balance
        self.cash_balance -= margin
        leveraged_size = margin * self.leverage
        
        # Deduct opening taker fee on total leveraged notional size
        open_fee = leveraged_size * config.FUTURES_TAKER_FEE
        self.cash_balance -= open_fee

        # Calculate TP, SL, and Liquidation Prices based on direction
        if side == "LONG":
            tp_price = price * (1.0 + config.TAKE_PROFIT_PERCENT)
            sl_price = price * (1.0 - config.STOP_LOSS_PERCENT)
            # Long Liquidation: Price drops ~18.5%
            liq_price = price * (1.0 - (1.0 / self.leverage - config.MAINTENANCE_MARGIN_PERCENT))
            extreme_price = price
        else:  # SHORT
            tp_price = price * (1.0 - config.TAKE_PROFIT_PERCENT)
            sl_price = price * (1.0 + config.STOP_LOSS_PERCENT)
            # Short Liquidation: Price rises ~18.5%
            liq_price = price * (1.0 + (1.0 / self.leverage - config.MAINTENANCE_MARGIN_PERCENT))
            extreme_price = price

        self.positions[symbol] = {
            "symbol": symbol,
            "side": side,
            "margin": margin,
            "leveraged_size": leveraged_size,
            "entry_price": price,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "liq_price": liq_price,
            "extreme_price": extreme_price,  # Highest for Long, Lowest for Short
            "open_fee": open_fee
        }
        return True

    def check_exit_conditions_for_token(self, symbol: str, current_price: float):
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]
        side = pos["side"]
        reason = None

        # 1. Update Trailing Stop-Loss
        if side == "LONG":
            if current_price > pos["extreme_price"]:
                pos["extreme_price"] = current_price
                new_sl = current_price * (1.0 - config.TRAILING_STOP_PERCENT)
                if new_sl > pos["sl_price"]:
                    pos["sl_price"] = new_sl

            # Check Exit Triggers for LONG
            if current_price <= pos["liq_price"]:
                reason = "💥 LIQUIDATION HIT"
            elif current_price >= pos["tp_price"]:
                reason = "Take-Profit Hit 🎯 (+15% ROE)"
            elif current_price <= pos["sl_price"]:
                reason = "Stop-Loss / Trailing SL Hit 🛑"

        else:  # SHORT
            if current_price < pos["extreme_price"]:
                pos["extreme_price"] = current_price
                new_sl = current_price * (1.0 + config.TRAILING_STOP_PERCENT)
                if new_sl < pos["sl_price"]:
                    pos["sl_price"] = new_sl

            # Check Exit Triggers for SHORT
            if current_price >= pos["liq_price"]:
                reason = "💥 LIQUIDATION HIT"
            elif current_price <= pos["tp_price"]:
                reason = "Take-Profit Hit 🎯 (+15% ROE)"
            elif current_price >= pos["sl_price"]:
                reason = "Stop-Loss / Trailing SL Hit 🛑"

        if reason:
            return self._close_token_position(symbol, reason, current_price)

        return None

    def _close_token_position(self, symbol: str, reason: str, exit_price: float):
        pos = self.positions.pop(symbol, None)
        if not pos:
            return None

        side = pos["side"]
        leveraged_size = pos["leveraged_size"]
        entry_price = pos["entry_price"]
        margin = pos["margin"]

        # Calculate Gross PnL
        if "LIQUIDATION" in reason:
            pnl = -margin  # Isolated margin is completely wiped out
            close_fee = 0.0
        else:
            if side == "LONG":
                pnl = leveraged_size * ((exit_price - entry_price) / entry_price)
            else:  # SHORT
                pnl = leveraged_size * ((entry_price - exit_price) / entry_price)
            
            # Deduct closing taker fee
            close_fee = leveraged_size * config.FUTURES_TAKER_FEE
            pnl -= close_fee

        return_capital = max(0.0, margin + pnl)
        self.cash_balance += return_capital
        self.realized_pnl += pnl

        return {
            "symbol": symbol,
            "side": side,
            "reason": reason,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "margin": margin,
            "leveraged_size": leveraged_size,
            "pnl": round(pnl, 2),
            "wallet_cash": round(self.cash_balance, 2)
        }
