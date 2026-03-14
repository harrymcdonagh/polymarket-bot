import asyncio
import sys
import logging
from src.pipeline import Pipeline
from src.config import Settings

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("polymarket-bot")

    settings = Settings()
    dry_run = "--live" not in sys.argv

    if dry_run:
        logger.info("=== DRY RUN MODE (pass --live to execute real trades) ===")
    else:
        logger.warning("=== LIVE MODE - REAL TRADES WILL BE PLACED ===")
        if not settings.POLYMARKET_PRIVATE_KEY:
            logger.error("POLYMARKET_PRIVATE_KEY not set. Cannot trade in live mode.")
            sys.exit(1)

    pipeline = Pipeline(settings=settings)
    asyncio.run(pipeline.run_cycle(dry_run=dry_run))

if __name__ == "__main__":
    main()
