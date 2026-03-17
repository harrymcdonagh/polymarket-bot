def calc_unrealised_pnl(side: str, amount: float, entry_price: float,
                         current_yes_price: float, fee_rate: float = 0.02) -> float:
    """Calculate unrealised PnL for an open position at current market price.

    Uses the same logic as Settler.calc_hypothetical_pnl but with a live price
    instead of the binary $1/$0 resolved outcome.
    """
    if entry_price <= 0 or entry_price >= 1:
        return -amount

    fee = amount * fee_rate
    if side == "YES":
        shares = amount / entry_price
        return shares * current_yes_price - amount - fee
    else:  # NO
        no_share_price = 1.0 - entry_price
        shares = amount / no_share_price
        current_no_price = 1.0 - current_yes_price
        return shares * current_no_price - amount - fee
