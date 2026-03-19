import asyncio
import json
import logging
from datetime import datetime, timezone
from src.config import Settings
from src.activity import write_activity
from src.db import Database
from src.scanner.scanner import MarketScanner
from src.research.pipeline import ResearchPipeline
from src.research.newsapi import NewsAPISource
from src.research.twitter import TwitterSource
from src.research.reddit import RedditSource
from src.research.rss import RSSSource
from src.research.google_trends import GoogleTrendsSource
from src.research.metaculus import MetaculusSource
from src.research.predictit import PredictItSource
from src.research.wikipedia import WikipediaSource
from src.research.structured_pipeline import StructuredDataPipeline
from src.research.clob import CLOBSource
from src.research.coingecko import CoinGeckoSource
from src.research.fred import FREDSource
from src.research.team_extractor import TeamExtractor
from src.research.sports_data import SportsDataSource
from src.research.odds_data import OddsDataSource
from src.research.sentiment import SentimentAnalyzer
from src.predictor.features import extract_features
from src.predictor.xgb_model import PredictionModel
from src.predictor.calibrator import Calibrator
from src.risk.risk_manager import RiskManager
from src.risk.executor import TradeExecutor
from src.postmortem.postmortem import PostmortemAnalyzer
from src.models import ResearchReport, SentimentResult, ScannedMarket
from src.notifications.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

class Pipeline:
    def __init__(self, settings: Settings | None = None, db_path: str | None = None,
                 status_callback=None):
        self.settings = settings or Settings()
        self._status_callback = status_callback
        self.db = Database(db_path or self.settings.DB_PATH)
        self.db.init()
        self.scanner = MarketScanner(self.settings)
        self.sentiment = SentimentAnalyzer(
            use_llm=self.settings.SENTIMENT_USE_LLM,
            llm_threshold=self.settings.SENTIMENT_LLM_THRESHOLD,
            sentiment_model=self.settings.SENTIMENT_MODEL,
        )
        self.xgb_model = PredictionModel()
        self._load_model()
        self.calibrator = Calibrator(settings=self.settings)
        self.risk_manager = RiskManager(self.settings)
        self.postmortem = PostmortemAnalyzer(settings=self.settings, db=self.db)
        self.executor = self._init_executor()

        self.research_pipeline = ResearchPipeline(
            sources=[
                NewsAPISource(
                    api_key=self.settings.NEWSAPI_KEY,
                    weight=self.settings.SOURCE_WEIGHT_NEWSAPI,
                ),
                RSSSource(
                    entry_limit=self.settings.RSS_ENTRY_LIMIT,
                    weight_google=self.settings.SOURCE_WEIGHT_RSS_GOOGLE,
                    weight_major=self.settings.SOURCE_WEIGHT_RSS_MAJOR,
                    weight_prediction=self.settings.SOURCE_WEIGHT_RSS_PREDICTION,
                ),
                TwitterSource(weight=self.settings.SOURCE_WEIGHT_TWITTER),
                RedditSource(
                    settings=self.settings,
                    weight=self.settings.SOURCE_WEIGHT_REDDIT,
                ),
                GoogleTrendsSource(weight=self.settings.SOURCE_WEIGHT_GOOGLE_TRENDS),
                MetaculusSource(weight=self.settings.SOURCE_WEIGHT_METACULUS, api_token=self.settings.METACULUS_API_TOKEN),
                PredictItSource(weight=self.settings.SOURCE_WEIGHT_PREDICTIT),
                WikipediaSource(weight=self.settings.SOURCE_WEIGHT_WIKIPEDIA),
            ],
            timeout=self.settings.RESEARCH_TIMEOUT,
            sentiment_analyzer=self.sentiment,
        )
        self.team_extractor = TeamExtractor(
            anthropic_key=self.settings.ANTHROPIC_API_KEY,
            model=self.settings.SENTIMENT_MODEL,
        )
        self.structured_pipeline = StructuredDataPipeline(
            sources=[
                CLOBSource(),
                CoinGeckoSource(),
                FREDSource(api_key=self.settings.FRED_API_KEY),
                SportsDataSource(
                    api_key=self.settings.BALLDONTLIE_API_KEY,
                    team_extractor=self.team_extractor,
                ),
                OddsDataSource(
                    api_key=self.settings.ODDSPAPI_API_KEY,
                    team_extractor=self.team_extractor,
                ),
            ],
            timeout=self.settings.RESEARCH_TIMEOUT,
        )
        self._settlement_tasks: list[asyncio.Task] = []
        self.last_flagged_markets: list[ScannedMarket] = []
        self.dry_run_trades: list[dict] = []
        self.notifier = TelegramNotifier(
            bot_token=self.settings.TELEGRAM_BOT_TOKEN,
            chat_id=self.settings.TELEGRAM_CHAT_ID,
        )

    def _set_activity(self, stage: str, detail: str = ""):
        if self._status_callback:
            self._status_callback(stage, detail)
        write_activity(stage, detail)

    def _init_executor(self) -> TradeExecutor | None:
        if not self.settings.POLYMARKET_PRIVATE_KEY:
            logger.info("No POLYMARKET_PRIVATE_KEY — executor disabled")
            return None
        try:
            from py_clob_client.client import ClobClient
            clob = ClobClient(
                self.settings.POLYMARKET_CLOB_URL,
                key=self.settings.POLYMARKET_PRIVATE_KEY,
                chain_id=137,  # Polygon mainnet
            )
            return TradeExecutor(clob, self.db)
        except Exception as e:
            logger.warning(f"Failed to init CLOB client: {e}")
            return None

    def _load_model(self, path: str = "model_xgb.json"):
        import os
        if os.path.exists(path):
            self.xgb_model.load(path)
            logger.info(f"Loaded trained XGBoost model from {path}")
        else:
            logger.warning("No trained model found — predictions will use market price as baseline")

    async def scan(self) -> list[ScannedMarket]:
        logger.info("=== STEP 1: Scanning markets ===")
        markets = await self.scanner.scan()
        logger.info(f"Found {len(markets)} markets passing filters")
        return markets

    async def research(self, market: ScannedMarket) -> ResearchReport:
        logger.info(f"=== STEP 2: Researching '{market.question[:60]}' ===")
        query = market.question

        weighted_result = await self.research_pipeline.search_and_analyze(query)

        # Convert to SentimentResult objects for backward compat
        sentiments = []
        for source_name, breakdown in weighted_result["source_breakdown"].items():
            sentiments.append(SentimentResult(
                source=source_name,
                query=query,
                positive_ratio=breakdown.get("positive_ratio", 0),
                negative_ratio=breakdown.get("negative_ratio", 0),
                neutral_ratio=breakdown.get("neutral_ratio", 0),
                sample_size=breakdown["count"],
                avg_compound_score=breakdown["avg_score"],
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

    async def predict(self, market: ScannedMarket, research: ResearchReport, structured_data: dict | None = None):
        logger.info(f"=== STEP 3: Predicting '{market.question[:60]}' ===")

        if research.sentiments:
            total_samples = sum(s.sample_size for s in research.sentiments)
            # Weight sentiment by sample size so high-sample sources dominate
            if total_samples > 0:
                avg_pos = sum(s.positive_ratio * s.sample_size for s in research.sentiments) / total_samples
                avg_neg = sum(s.negative_ratio * s.sample_size for s in research.sentiments) / total_samples
                avg_neu = sum(s.neutral_ratio * s.sample_size for s in research.sentiments) / total_samples
                avg_score = sum(s.avg_compound_score * s.sample_size for s in research.sentiments) / total_samples
            else:
                avg_pos = sum(s.positive_ratio for s in research.sentiments) / len(research.sentiments)
                avg_neg = sum(s.negative_ratio for s in research.sentiments) / len(research.sentiments)
                avg_neu = sum(s.neutral_ratio for s in research.sentiments) / len(research.sentiments)
                avg_score = sum(s.avg_compound_score for s in research.sentiments) / len(research.sentiments)
            source_scores = [s.avg_compound_score for s in research.sentiments]
        else:
            avg_pos = avg_neg = avg_neu = avg_score = 0
            total_samples = 0
            source_scores = []

        sentiment_agg = {
            "positive_ratio": avg_pos,
            "negative_ratio": avg_neg,
            "neutral_ratio": avg_neu,
            "avg_score": avg_score,
            "sample_size": total_samples,
            "source_scores": source_scores,
            "narrative_alignment": research.narrative_vs_odds_alignment,
        }

        # Initial feature extraction (edge/prob unknown yet, will update after calibration)
        band_obs = self.db.count_calibration_band_obs(market.yes_price)
        prediction_context = {
            "edge": 0.0,
            "predicted_prob": market.yes_price,
            "calibration_band_obs": band_obs,
        }
        features = extract_features(market, sentiment_agg, structured_data=structured_data,
                                    prediction_context=prediction_context)
        xgb_prob = self.xgb_model.predict(features)

        # Feed consolidated rules (or fallback to raw lessons) into calibrator
        rules = self.db.get_latest_rules()
        if rules:
            lessons_for_calibrator = rules["ruleset"]
        else:
            lessons_for_calibrator = "\n".join(f"- {l['lesson']}" for l in self.db.get_lessons()[-10:])
        prediction = await self.calibrator.calibrate(
            market, research, xgb_prob, lessons=lessons_for_calibrator,
        )

        # Update lesson-derived features with actual prediction values
        from src.predictor.features import _edge_anomaly_flag
        features["edge_anomaly_flag"] = _edge_anomaly_flag(
            prediction.edge, prediction.predicted_probability
        )
        band_obs_actual = self.db.count_calibration_band_obs(prediction.predicted_probability)
        features["calibration_band_obs"] = band_obs_actual

        # Store CLV diagnostic (not an XGBoost input — for future training data)
        sharp_prob = (structured_data or {}).get("sharp_implied_prob", 0.0)
        if sharp_prob > 0:
            features["closing_line_value_delta"] = prediction.predicted_probability - sharp_prob
        else:
            features["closing_line_value_delta"] = 0.0

        # Stash features for saving with prediction
        prediction._features = features

        # Log new feature summary
        from src.predictor.features import classify_market_type, classify_data_quality_tier
        tier_names = {1:'T1-Major',2:'T2-Mid',3:'T3-Low',4:'T4-NoBet'}
        type_names = {0:'Moneyline',1:'Totals',2:'Spread',3:'Political',4:'Crypto',5:'Social',6:'Esports'}
        mt = features.get("market_type", -1)
        dt = features.get("data_quality_tier", 0)
        sports = "yes" if features.get("sports_is_relevant", 0) > 0 else "no"
        rest = features.get("rest_days_differential", 0)
        standings = features.get("standings_pct_delta", 0)
        clv = features.get("closing_line_value_delta", 0)
        edge_flag = "ANOMALY" if features.get("edge_anomaly_flag", 0) else "ok"
        band_obs = features.get("calibration_band_obs", 0)

        logger.info(
            f"Prediction: {prediction.recommended_side} | "
            f"prob={prediction.predicted_probability:.2%} | "
            f"edge={prediction.edge:.2%} | conf={prediction.confidence:.2f}"
        )
        logger.info(
            f"  Features: type={type_names.get(mt,'?')} tier={tier_names.get(dt,'?')} "
            f"sports={sports} rest={rest:.0f} standings={standings:.2f} "
            f"clv={clv:.3f} edge_check={edge_flag} band_obs={band_obs}"
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

    async def check_open_trades(self):
        """Check settlement status of any open trades."""
        open_trades = self.db.get_open_trades()
        if not open_trades:
            return
        logger.info(f"Checking {len(open_trades)} open trades for settlement")
        for trade in open_trades:
            # Check if already being watched
            if any(not t.done() for t in self._settlement_tasks):
                continue
            if self.executor:
                task = asyncio.create_task(
                    self.executor.watch_settlement(trade["id"], trade.get("market_id", ""))
                )
                self._settlement_tasks.append(task)
        # Clean up completed tasks
        self._settlement_tasks = [t for t in self._settlement_tasks if not t.done()]

    async def run_postmortem(self):
        logger.info("=== STEP 5: Running postmortem ===")
        reports = await self.postmortem.run_full_postmortem()
        for report in reports:
            logger.info(f"Postmortem: {report.get('category', 'unknown')} - {len(report.get('lessons', []))} lessons")
        return reports

    async def run_cycle(self, dry_run: bool = True):
        logger.info("========== STARTING PIPELINE CYCLE ==========")
        self._set_activity("checking", "Open trades")

        await self.check_open_trades()

        self._set_activity("scanning", "Fetching markets")
        markets = await self.scan()
        if not markets:
            logger.info("No markets found, ending cycle")
            self._set_activity("idle")
            return

        # Save snapshots for historical data collection
        saved = self.db.save_market_snapshots_batch(markets)
        logger.info(f"Saved {saved} market snapshots to database")

        flagged = [m for m in markets if m.flags]
        self.last_flagged_markets = flagged

        # Skip markets we've already traded
        traded_ids = self.db.get_traded_market_ids()
        candidates = [m for m in (flagged if flagged else markets) if m.condition_id not in traded_ids]
        if len(candidates) < len(flagged if flagged else markets):
            skipped = (len(flagged) if flagged else len(markets)) - len(candidates)
            logger.info(f"Skipped {skipped} already-traded markets")
        targets = candidates[:20] if flagged else candidates[:10]

        # Parallelize BOTH tracks with concurrency limit to avoid overwhelming network
        self._set_activity("researching", f"Researching {len(targets)} markets (concurrency={self.settings.RESEARCH_CONCURRENCY})")
        sem = asyncio.Semaphore(self.settings.RESEARCH_CONCURRENCY)

        async def _guarded_research(m):
            async with sem:
                return await self.research(m)

        async def _guarded_structured(m):
            async with sem:
                return await self.structured_pipeline.fetch(m)

        research_tasks = [_guarded_research(m) for m in targets]
        structured_tasks = [_guarded_structured(m) for m in targets]
        all_results = await asyncio.gather(
            asyncio.gather(*research_tasks, return_exceptions=True),
            asyncio.gather(*structured_tasks, return_exceptions=True),
        )
        research_results, structured_results = all_results

        for i, market in enumerate(targets):
            try:
                # Use pre-fetched research result
                research = research_results[i]
                if isinstance(research, Exception):
                    logger.error(f"Research failed for {market.question[:50]}: {research}")
                    continue

                # Get structured data for this market
                struct_data = structured_results[i]
                if isinstance(struct_data, Exception):
                    logger.warning(f"Structured data failed for {market.question[:50]}: {struct_data}")
                    struct_data = None

                self._set_activity("predicting", f"[{i+1}/{len(targets)}] {market.question}")
                prediction = await self.predict(market, research, structured_data=struct_data)
                self._set_activity("evaluating", f"[{i+1}/{len(targets)}] {market.question}")
                decision = self.evaluate_risk(prediction)

                # Save every prediction for accuracy tracking
                self.db.save_prediction(
                    market_id=market.condition_id,
                    question=market.question,
                    market_yes_price=market.yes_price,
                    predicted_prob=prediction.predicted_probability,
                    xgb_prob=prediction.xgb_probability,
                    llm_prob=prediction.llm_probability,
                    edge=prediction.edge,
                    confidence=prediction.confidence,
                    recommended_side=prediction.recommended_side,
                    approved=decision.approved,
                    rejection_reason=decision.rejection_reason,
                    bet_size=decision.bet_size_usd,
                    features_json=json.dumps(getattr(prediction, '_features', {})),
                )

                if not decision.approved:
                    logger.info(
                        f"[BLOCKED] {market.question[:50]} | "
                        f"{prediction.recommended_side} | edge={prediction.edge:.2%} | "
                        f"conf={prediction.confidence:.2f} | reason: {decision.rejection_reason}"
                    )

                # Check daily trade limit before placing
                if decision.approved and self.settings.MAX_DAILY_TRADES > 0:
                    daily_count = self.db.get_daily_trade_count()
                    if daily_count >= self.settings.MAX_DAILY_TRADES:
                        logger.info(f"[DAILY LIMIT] {daily_count}/{self.settings.MAX_DAILY_TRADES} trades today — skipping")
                        continue

                # Check concentration limit (max trades per market type)
                if decision.approved and self.settings.MAX_TRADES_PER_MARKET_TYPE > 0:
                    feat = getattr(prediction, '_features', {})
                    mtype = feat.get("market_type", 0)
                    type_count = self.db.count_open_trades_by_market_type(mtype)
                    if type_count >= self.settings.MAX_TRADES_PER_MARKET_TYPE:
                        type_names = {0:'Moneyline',1:'Totals',2:'Spread',3:'Political',4:'Crypto',5:'Social',6:'Esports'}
                        logger.info(f"[CONCENTRATION LIMIT] {type_count}/{self.settings.MAX_TRADES_PER_MARKET_TYPE} open {type_names.get(mtype,'unknown')} trades — skipping")
                        continue

                if decision.approved and not dry_run:
                    if self.executor is None:
                        logger.error("Trade approved but executor not initialized — missing private key")
                        continue
                    token_id = market.token_yes_id if prediction.recommended_side == "YES" else market.token_no_id
                    execution = self.executor.execute(decision, token_id)
                    logger.info(f"Executed: {execution.status} | order={execution.order_id}")
                    if execution.status == "pending":
                        # Get the trade ID from the most recent trade
                        trades = self.db.get_open_trades()
                        if trades:
                            trade_id = trades[-1]["id"]
                            self._settlement_tasks.append(
                                asyncio.create_task(self.executor.watch_settlement(trade_id, token_id))
                            )

                elif decision.approved and dry_run:
                    logger.info(f"[DRY RUN] Would bet ${decision.bet_size_usd:.2f} on {prediction.recommended_side}")
                    self.db.save_trade(
                        market_id=market.condition_id,
                        side=prediction.recommended_side,
                        amount=decision.bet_size_usd,
                        price=market.yes_price,
                        order_id=None,
                        status="dry_run",
                        predicted_prob=prediction.predicted_probability,
                    )
                    self.dry_run_trades.append({
                        "market_id": market.condition_id,
                        "question": market.question,
                        "side": prediction.recommended_side,
                        "amount": decision.bet_size_usd,
                        "price": market.yes_price,
                        "status": "dry_run",
                        "pnl": None,
                        "executed_at": datetime.now(timezone.utc).isoformat(),
                    })
                    if self.notifier.is_enabled:
                        msg = self.notifier.format_trade_alert(
                            question=market.question,
                            side=prediction.recommended_side,
                            amount=decision.bet_size_usd,
                            price=market.yes_price,
                            edge=prediction.edge,
                        )
                        await self.notifier.send(msg)

            except Exception as e:
                logger.error(f"Pipeline error for {market.question[:50]}: {e}")
                if self.notifier.is_enabled:
                    await self.notifier.send(
                        self.notifier.format_error_alert(f"{market.question[:50]}: {e}")
                    )
                continue

        self._log_cycle_stats(len(markets), len(targets))

        self._set_activity("idle")
        logger.info("========== CYCLE COMPLETE ==========")

    def _log_cycle_stats(self, total_scanned: int, targets_evaluated: int):
        """Log end-of-cycle performance metrics."""
        stats = self.db.get_trade_stats()
        daily_pnl = self.db.get_daily_pnl()
        snapshots = self.db.get_snapshot_count()
        open_trades = len(self.db.get_open_trades())

        logger.info(
            f"--- Cycle Stats ---\n"
            f"  Markets scanned: {total_scanned} | Evaluated: {targets_evaluated}\n"
            f"  Open trades: {open_trades}\n"
            f"  Settled: {stats['total_trades']} | Wins: {stats['wins']} | "
            f"Win rate: {stats['win_rate']:.0%}\n"
            f"  Total PnL: ${stats['total_pnl']:.2f} | Today: ${daily_pnl:.2f}\n"
            f"  Snapshots in DB: {snapshots}"
        )

    async def _generate_narrative(self, market: ScannedMarket, sentiments: list[SentimentResult]) -> str:
        sentiment_text = "\n".join(
            f"- {s.source}: {s.positive_ratio:.0%} positive, {s.negative_ratio:.0%} negative (n={s.sample_size})"
            for s in sentiments
        )
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.settings.ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=self.settings.NARRATIVE_MODEL,
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
        """Calculate how well sentiment aligns with market price.

        Returns -1 (strong contradiction) to +1 (strong agreement).
        Uses sentiment polarity (positive - negative) compared to price deviation from 0.5.
        """
        if not sentiments:
            return 0.0
        avg_pos = sum(s.positive_ratio for s in sentiments) / len(sentiments)
        avg_neg = sum(s.negative_ratio for s in sentiments) / len(sentiments)
        # Sentiment direction: positive means YES-leaning, negative means NO-leaning
        sentiment_direction = avg_pos - avg_neg  # -1 to +1
        # Price direction: >0.5 means market leans YES, <0.5 means NO
        price_direction = (yes_price - 0.5) * 2  # -1 to +1
        # Agreement: both point same direction = positive alignment
        return sentiment_direction * price_direction


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
