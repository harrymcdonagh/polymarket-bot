import logging
import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._consecutive_failures: int = 0

    @property
    def is_enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def send(self, text: str) -> None:
        if not self.is_enabled:
            return
        url = TELEGRAM_API.format(token=self.bot_token)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                })
                if resp.status_code != 200:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= 3:
                        logger.error(f"Telegram send failed {self._consecutive_failures} times in a row (status {resp.status_code}). Check bot token and chat ID.")
                    else:
                        logger.warning(f"Telegram send failed: {resp.status_code} {resp.text}")
                else:
                    self._consecutive_failures = 0
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                logger.error(f"Telegram send failed {self._consecutive_failures} times: {e}. Check network and bot config.")
            else:
                logger.warning(f"Telegram send error: {e}")

    def format_trade_alert(self, question: str, side: str, amount: float,
                           price: float, edge: float) -> str:
        return (
            f"*Dry-Run Trade*\n"
            f"Market: {question}\n"
            f"Side: {side} @ ${price:.2f}\n"
            f"Amount: ${amount:.2f}\n"
            f"Edge: {edge:.1%}"
        )

    def format_settlement_alert(self, question: str, outcome: str,
                                predicted_prob: float, price: float,
                                pnl: float) -> str:
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        return (
            f"*Market Resolved*\n"
            f"Market: {question}\n"
            f"Outcome: {outcome}\n"
            f"Prediction: {predicted_prob:.0%} @ ${price:.2f}\n"
            f"Hypothetical P&L: {pnl_str}"
        )

    def format_error_alert(self, error: str) -> str:
        return f"*Pipeline Error*\n{error}"

    def format_daily_summary(self, markets_scanned: int, trades_flagged: int,
                             top_edge: float, top_market: str) -> str:
        return (
            f"*Daily Summary*\n"
            f"Markets scanned: {markets_scanned}\n"
            f"Trades flagged: {trades_flagged}\n"
            f"Top edge: {top_edge:.1%} on {top_market}"
        )

    def format_startup(self) -> str:
        return "*Bot Started*\nPolymarket bot is online."
