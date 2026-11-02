from datetime import datetime

class PaperTradingEngine:
    def __init__(self, initial_capital: float = 1000.0, max_concurrent: int = 3):
        self.cash_balance = initial_capital
        self.initial_capital = initial_capital
        self.max_concurrent = max_concurrent
        # Track active positions per token symbol: {"SOL/USDC": {...}, ...}
        self.positions = {}
        self.realized_pnl = 0.0
        self.day_start_balance = initial_capital

    @property
    def active_position(self):
        """Backward compatibility helper returning the first active position or None."""
        if self.positions:
            return next(iter(self.positions.values()))
        return None

    def calculate_position_size(self) -> float:
        """Calculates exactly 2% of the real-time balance for the next trade."""
        current_equity = self.cash_balance + sum(p.get("amount", 0.0) for p in self.positions.values())
        size = current_equity * 0.02
        return max(5.0, round(size, 2))

    def is_circuit_breaker_triggered(self) -> bool:
        """Triggers if daily net loss reaches or exceeds 10% of day-start capital."""
        loss = self.day_start_balance - (self.cash_balance + sum(p.get("amount", 0.0) for p in self.positions.values()))
        max_allowed_loss = self.day_start_balance * 0.10
        return loss >= max_allowed_loss

    def can_open_position(self, symbol: str) -> bool:
        """Ensure we don't exceed max 3 concurrent positions and don't duplicate on same symbol."""
        if len(self.positions) >= self.max_concurrent:
            return False
        if symbol in self.positions:
            return False
        if self.is_circuit_breaker_triggered():
            return False
        return True

    def execute_order(self, symbol: str, side: str, amount: float, price: float):
        if side == "BUY":
            if not self.can_open_position(symbol):
                return False
            
            if self.cash_balance < amount:
                return False

            self.cash_balance -= amount
            # 6% Take-Profit, 2.5% Stop-Loss (with Trailing logic)
            tp_price = price * 1.06
            sl_price = price * 0.975

            self.positions[symbol] = {
                "symbol": symbol,
                "amount": amount,
                "entry_price": price,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "highest_price": price
            }
            return True
        return False

    def check_exit_conditions_for_token(self, symbol: str, current_price: float):
        """Checks exit rules including Trailing Stop-Loss and Take-Profit for a specific token."""
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]

        # Trailing Stop-Loss update
        if current_price > pos["highest_price"]:
            pos["highest_price"] = current_price
            new_sl = current_price * 0.98
            if new_sl > pos["sl_price"]:
                pos["sl_price"] = new_sl

        reason = None
        pnl = 0.0

        if current_price >= pos["tp_price"]:
            reason = "Take-Profit Hit 🎯"
            pnl = pos["amount"] * ((pos["tp_price"] - pos["entry_price"]) / pos["entry_price"])
        elif current_price <= pos["sl_price"]:
            reason = "Stop-Loss / Trailing SL Hit 🛑"
            pnl = pos["amount"] * ((pos["sl_price"] - pos["entry_price"]) / pos["entry_price"])

        if reason:
            return self._close_token_position(symbol, pnl, reason, current_price)

        return None

    def check_exit_conditions(self, current_price: float):
        """Backward compatibility check for the first active position."""
        if not self.positions:
            return None
        sym = next(iter(self.positions))
        return self.check_exit_conditions_for_token(sym, current_price)

    def _close_token_position(self, symbol: str, pnl: float, reason: str, exit_price: float):
        pos = self.positions.pop(symbol, None)
        if not pos:
            return None

        return_amount = pos["amount"] + pnl
        self.cash_balance += return_amount
        self.realized_pnl += pnl

        return {
            "symbol": symbol,
            "reason": reason,
            "entry_price": pos["entry_price"],
            "amount": pos["amount"],
            "exit_price": exit_price,
            "pnl": pnl,
            "wallet_cash": self.cash_balance
        }
