import asyncio
import logging
from datetime import datetime, timezone
from src.config import Settings
from src.db import Database
from src.scanner.scanner import MarketScanner
from src.research.twitter import TwitterResearcher
from src.research.reddit import RedditResearcher
from src.research.rss import RSSResearcher
from src.research.sentiment import SentimentAnalyzer
from src.predictor.features import extract_features
from src.predictor.xgb_model import PredictionModel
from src.predictor.calibrator import Calibrator
from src.risk.risk_manager import RiskManager
from src.risk.executor import TradeExecutor
from src.postmortem.postmortem import PostmortemAnalyzer
from src.models import ResearchReport, SentimentResult, ScannedMarket

logger = logging.getLogger(__name__)

class Pipeline:
    def __init__(self, settings: Settings | None = None, db_path: str = "bot.db"):
        self.settings = settings or Settings()
        self.db = Database(db_path)
        self.db.init()
        self.scanner = MarketScanner(self.settings)
        self.sentiment = SentimentAnalyzer(use_transformer=True)
        self.xgb_model = PredictionModel()
        self.calibrator = Calibrator(settings=self.settings)
        self.risk_manager = RiskManager(self.settings)
        self.postmortem = PostmortemAnalyzer(settings=self.settings, db=self.db)

        self._twitter = None
        self._reddit = None
        self._rss = RSSResearcher()

    async def scan(self) -> list[ScannedMarket]:
        logger.info("=== STEP 1: Scanning markets ===")
        markets = await self.scanner.scan()
        logger.info(f"Found {len(markets)} markets passing filters")
        return markets

    async def research(self, market: ScannedMarket) -> ResearchReport:
        logger.info(f"=== STEP 2: Researching '{market.question[:60]}' ===")
        query = market.question

        twitter_task = self._search_twitter(query)
        reddit_task = self._search_reddit(query)
        rss_task = asyncio.to_thread(self._rss.search, query)

        twitter_results, reddit_results, rss_results = await asyncio.gather(
            twitter_task, reddit_task, rss_task, return_exceptions=True
        )

        if isinstance(twitter_results, Exception):
            logger.warning(f"Twitter research failed: {twitter_results}")
            twitter_results = []
        if isinstance(reddit_results, Exception):
            logger.warning(f"Reddit research failed: {reddit_results}")
            reddit_results = []
        if isinstance(rss_results, Exception):
            logger.warning(f"RSS research failed: {rss_results}")
            rss_results = []

        sentiments = []
        for source_name, results in [("twitter", twitter_results), ("reddit", reddit_results), ("rss", rss_results)]:
            if not results:
                continue
            texts = [r["text"] for r in results]
            analyzed = self.sentiment.analyze_batch(texts)
            agg = self.sentiment.aggregate(analyzed)
            sentiments.append(SentimentResult(
                source=source_name,
                query=query,
                positive_ratio=agg["positive_ratio"],
                negative_ratio=agg["negative_ratio"],
                neutral_ratio=agg["neutral_ratio"],
                sample_size=agg["sample_size"],
                avg_compound_score=agg["avg_score"],
                collected_at=datetime.now(timezone.utc),
            ))

        narrative = await self._generate_narrative(market, sentiments)

        return ResearchReport(
            market_id=market.condition_id,
            question=market.question,
            sentiments=sentiments,
            narrative_summary=narrative,
            narrative_vs_odds_alignment=self._calc_alignment(sentiments, market.yes_price),
            researched_at=datetime.now(timezone.utc),
        )

    async def predict(self, market: ScannedMarket, research: ResearchReport):
        logger.info(f"=== STEP 3: Predicting '{market.question[:60]}' ===")

        if research.sentiments:
            avg_pos = sum(s.positive_ratio for s in research.sentiments) / len(research.sentiments)
            avg_neg = sum(s.negative_ratio for s in research.sentiments) / len(research.sentiments)
            avg_neu = sum(s.neutral_ratio for s in research.sentiments) / len(research.sentiments)
            avg_score = sum(s.avg_compound_score for s in research.sentiments) / len(research.sentiments)
            total_samples = sum(s.sample_size for s in research.sentiments)
        else:
            avg_pos = avg_neg = avg_neu = avg_score = 0
            total_samples = 0

        sentiment_agg = {
            "positive_ratio": avg_pos,
            "negative_ratio": avg_neg,
            "neutral_ratio": avg_neu,
            "avg_score": avg_score,
            "sample_size": total_samples,
        }

        features = extract_features(market, sentiment_agg)
        xgb_prob = self.xgb_model.predict(features)
        prediction = await self.calibrator.calibrate(market, research, xgb_prob)

        logger.info(
            f"Prediction: {prediction.recommended_side} | "
            f"prob={prediction.predicted_probability:.2%} | "
            f"edge={prediction.edge:.2%} | conf={prediction.confidence:.2f}"
        )
        return prediction

    def evaluate_risk(self, prediction):
        logger.info(f"=== STEP 4: Risk evaluation ===")
        daily_pnl = self.db.get_daily_pnl()
        decision = self.risk_manager.evaluate(prediction, daily_pnl)

        if decision.approved:
            logger.info(f"APPROVED: ${decision.bet_size_usd:.2f} on {prediction.recommended_side}")
        else:
            logger.info(f"BLOCKED: {decision.rejection_reason}")
        return decision

    async def run_postmortem(self):
        logger.info("=== STEP 5: Running postmortem ===")
        reports = await self.postmortem.run_full_postmortem()
        for report in reports:
            logger.info(f"Postmortem: {report.get('category', 'unknown')} - {len(report.get('lessons', []))} lessons")
        return reports

    async def run_cycle(self, dry_run: bool = True):
        logger.info("========== STARTING PIPELINE CYCLE ==========")

        markets = await self.scan()
        if not markets:
            logger.info("No markets found, ending cycle")
            return

        flagged = [m for m in markets if m.flags]
        targets = flagged[:10] if flagged else markets[:5]

        for market in targets:
            try:
                research = await self.research(market)
                prediction = await self.predict(market, research)
                decision = self.evaluate_risk(prediction)

                if decision.approved and not dry_run:
                    logger.info(f"Would execute: {decision.bet_size_usd} on {prediction.recommended_side}")

                elif decision.approved and dry_run:
                    logger.info(f"[DRY RUN] Would bet ${decision.bet_size_usd:.2f} on {prediction.recommended_side}")

            except Exception as e:
                logger.error(f"Pipeline error for {market.question[:50]}: {e}")
                continue

        await self.run_postmortem()

        logger.info("========== CYCLE COMPLETE ==========")

    async def _search_twitter(self, query: str) -> list[dict]:
        if self._twitter is None:
            from twscrape import API
            self._twitter = TwitterResearcher(API())
        return await self._twitter.search(query, limit=50)

    async def _search_reddit(self, query: str) -> list[dict]:
        if self._reddit is None:
            self._reddit = RedditResearcher(settings=self.settings)
        return await asyncio.to_thread(self._reddit.search, query)

    async def _generate_narrative(self, market: ScannedMarket, sentiments: list[SentimentResult]) -> str:
        sentiment_text = "\n".join(
            f"- {s.source}: {s.positive_ratio:.0%} positive, {s.negative_ratio:.0%} negative (n={s.sample_size})"
            for s in sentiments
        )
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.settings.ANTHROPIC_API_KEY)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": (
                    f"Summarize the public sentiment and narrative for this prediction market in 2-3 sentences:\n"
                    f"Question: {market.question}\n"
                    f"Current YES price: {market.yes_price}\n"
                    f"Sentiment data:\n{sentiment_text or 'No data collected'}"
                )}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.warning(f"Narrative generation failed: {e}")
            return "Narrative generation unavailable."

    def _calc_alignment(self, sentiments: list[SentimentResult], yes_price: float) -> float:
        if not sentiments:
            return 0.0
        avg_pos = sum(s.positive_ratio for s in sentiments) / len(sentiments)
        return 2 * (1 - abs(avg_pos - yes_price)) - 1


async def main():
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    settings = Settings()
    pipeline = Pipeline(settings=settings)

    dry_run = "--live" not in sys.argv
    if dry_run:
        logger.info("Running in DRY RUN mode (use --live to execute trades)")

    await pipeline.run_cycle(dry_run=dry_run)

if __name__ == "__main__":
    asyncio.run(main())
