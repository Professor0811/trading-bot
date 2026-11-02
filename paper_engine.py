class PaperTradingEngine:
    def __init__(self, initial_capital: float = 50.0):
        self.cash_balance = initial_capital
        self.initial_capital = initial_capital
        self.active_position = None
        self.realized_pnl = 0.0

    def calculate_position_size(self) -> float:
        """Calculates 2% position sizing based on current capital ($1.00 for $50)."""
        return self.cash_balance * 0.02

    def execute_order(self, symbol: str, side: str, amount: float, price: float):
        """Executes a virtual paper trade with initial Take-Profit and Stop-Loss levels."""
        if side == "BUY":
            if self.cash_balance < amount:
                print("Paper Engine [REJECTED]: Insufficient cash balance.")
                return False
            
            self.cash_balance -= amount
            # 5% Take-Profit, 3% Initial Stop-Loss
            tp_price = price * 1.05
            sl_price = price * 0.97
            
            self.active_position = {
                "symbol": symbol,
                "amount": amount,
                "entry_price": price,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "highest_price": price # Tracks highest price for Trailing Stop-Loss
            }
            print(f"Paper Engine [BUY]: Bought ${amount:.2f} of {symbol} at ${price:.4f} | TP: ${tp_price:.4f}, SL: ${sl_price:.4f} (Trailing Active)")
            return True
        return False

    def check_exit_conditions(self, current_price: float):
        """Checks exit conditions including Dynamic Trailing Stop-Loss and Take-Profit."""
        if not self.active_position:
            return None

        pos = self.active_position
        
        # Update Trailing Stop-Loss if price makes a new high
        if current_price > pos["highest_price"]:
            pos["highest_price"] = current_price
            # Trail stop-loss 2% below the new high watermark to lock in profits
            new_sl = current_price * 0.98
            if new_sl > pos["sl_price"]:
                pos["sl_price"] = new_sl
                print(f"Trailing SL Updated -> New SL: ${pos['sl_price']:.4f} (Price peaked at ${current_price:.4f})")

        reason = None
        pnl = 0.0

        if current_price >= pos["tp_price"]:
            reason = "Take-Profit Hit"
            profit_ratio = (pos["tp_price"] - pos["entry_price"]) / pos["entry_price"]
            pnl = pos["amount"] * profit_ratio
        elif current_price <= pos["sl_price"]:
            reason = "Stop-Loss / Trailing SL Hit"
            loss_ratio = (pos["sl_price"] - pos["entry_price"]) / pos["entry_price"]
            pnl = pos["amount"] * loss_ratio

        if reason:
            return self._close_position(pnl, reason, current_price)
        
        return None

    def _close_position(self, pnl: float, reason: str, exit_price: float):
        pos = self.active_position
        return_amount = pos["amount"] + pnl
        self.cash_balance += return_amount
        self.realized_pnl += pnl
        
        closed_data = {
            "symbol": pos["symbol"],
            "reason": reason,
            "exit_price": exit_price,
            "pnl": pnl,
            "wallet_cash": self.cash_balance
        }
        self.active_position = None
        return closed_data