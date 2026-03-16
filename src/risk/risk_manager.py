import logging
from datetime import datetime, timezone
from src.config import Settings
from src.models import Prediction, TradeDecision

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _kelly_fraction(self, edge: float, price: float) -> float:
        """Half-Kelly criterion for position sizing with fee adjustment.

        Full Kelly: f = (p*b - q) / b where b = (1/price - 1), p = prob, q = 1-p
        Simplified for binary markets: f = edge / (1 - price)
        We use half-Kelly for safety and subtract Polymarket fees from edge.
        """
        if price <= 0 or price >= 1:
            return 0.0
        # Subtract trading fees from effective edge
        effective_edge = edge - self.settings.POLYMARKET_FEE
        if effective_edge <= 0:
            return 0.0
        odds_against = 1.0 / price - 1.0
        if odds_against <= 0:
            return 0.0
        kelly = effective_edge / (1.0 - price)
        half_kelly = kelly / 2.0
        return max(0.0, half_kelly)

    def evaluate(self, prediction: Prediction, daily_pnl: float) -> TradeDecision:
        """Evaluate whether a trade should be placed and how much."""
        now = datetime.now(timezone.utc)

        # Check daily loss limit
        if daily_pnl <= -self.settings.MAX_DAILY_LOSS:
            return TradeDecision(
                market_id=prediction.market_id,
                prediction=prediction,
                approved=False,
                bet_size_usd=0,
                kelly_fraction=0,
                risk_score=1.0,
                rejection_reason=f"Daily loss limit reached (PnL: ${daily_pnl:.2f})",
                decided_at=now,
            )

        # Check minimum edge (after fees)
        effective_edge = abs(prediction.edge) - self.settings.POLYMARKET_FEE
        if effective_edge < self.settings.MIN_EDGE_THRESHOLD:
            return TradeDecision(
                market_id=prediction.market_id,
                prediction=prediction,
                approved=False,
                bet_size_usd=0,
                kelly_fraction=0,
                risk_score=0.3,
                rejection_reason=f"Edge after fees too small: {effective_edge:.2%} < {self.settings.MIN_EDGE_THRESHOLD:.2%}",
                decided_at=now,
            )

        # Hard reject only for very low confidence (likely LLM failure)
        if prediction.confidence < 0.2:
            return TradeDecision(
                market_id=prediction.market_id,
                prediction=prediction,
                approved=False,
                bet_size_usd=0,
                kelly_fraction=0,
                risk_score=0.5,
                rejection_reason=f"Confidence too low: {prediction.confidence:.2f} (likely calibration failure)",
                decided_at=now,
            )

        # Calculate position size — scale by confidence instead of binary reject
        price = prediction.market_yes_price if prediction.recommended_side == "YES" else (1 - prediction.market_yes_price)
        kelly = self._kelly_fraction(abs(prediction.edge), price)
        capped_fraction = min(kelly, self.settings.MAX_BET_FRACTION)

        # Scale bet size by confidence: high confidence = full Kelly, low = reduced
        confidence_scalar = min(1.0, prediction.confidence / self.settings.CONFIDENCE_THRESHOLD)
        adjusted_fraction = capped_fraction * confidence_scalar
        bet_size = self.settings.BANKROLL * adjusted_fraction

        # Risk score: higher when betting more of bankroll
        risk_score = adjusted_fraction / self.settings.MAX_BET_FRACTION if self.settings.MAX_BET_FRACTION > 0 else 0

        if bet_size < 1.0:
            return TradeDecision(
                market_id=prediction.market_id,
                prediction=prediction,
                approved=False,
                bet_size_usd=0,
                kelly_fraction=kelly,
                risk_score=risk_score,
                rejection_reason=f"Bet size below $1 minimum (${bet_size:.2f}, conf={prediction.confidence:.2f})",
                decided_at=now,
            )

        logger.info(
            f"APPROVED: {prediction.question[:50]} | {prediction.recommended_side} | "
            f"${bet_size:.2f} | edge={prediction.edge:.2%} (eff={effective_edge:.2%}) | "
            f"kelly={kelly:.4f} | conf_scale={confidence_scalar:.2f}"
        )

        return TradeDecision(
            market_id=prediction.market_id,
            prediction=prediction,
            approved=True,
            bet_size_usd=round(bet_size, 2),
            kelly_fraction=kelly,
            risk_score=risk_score,
            decided_at=now,
        )
