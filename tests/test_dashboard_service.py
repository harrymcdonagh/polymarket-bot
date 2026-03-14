from src.db import Database


def test_get_pnl_history_empty(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init()
    result = db.get_pnl_history()
    assert result == []


def test_get_pnl_history_cumulative_math(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init()
    db.save_trade("0x1", "YES", 50.0, 0.5, "o1")
    db.update_trade_status(1, "settled", 25.0)
    db.save_trade("0x2", "NO", 30.0, 0.6, "o2")
    db.update_trade_status(2, "settled", -10.0)
    history = db.get_pnl_history()
    assert len(history) >= 1
    assert "date" in history[0]
    assert "daily_pnl" in history[0]
    assert "cumulative_pnl" in history[0]
    running = 0.0
    for entry in history:
        running += entry["daily_pnl"]
        assert abs(entry["cumulative_pnl"] - round(running, 2)) < 0.01


def test_get_recent_trades_with_names(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init()
    db.save_trade("0xabc", "YES", 50.0, 0.5, "o1")
    from unittest.mock import MagicMock
    market = MagicMock()
    market.condition_id = "0xabc"
    market.question = "Will BTC hit 100k?"
    market.yes_price = 0.55
    market.no_price = 0.45
    market.spread = 0.02
    market.liquidity = 50000
    market.volume_24h = 10000
    market.days_to_resolution = 20
    market.flags = []
    market.scanned_at = None
    db.save_market_snapshots_batch([market])
    trades = db.get_recent_trades_with_names(limit=10)
    assert len(trades) == 1
    assert trades[0]["question"] == "Will BTC hit 100k?"


def test_get_recent_trades_with_names_no_snapshot(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init()
    db.save_trade("0xunknown", "YES", 50.0, 0.5, "o1")
    trades = db.get_recent_trades_with_names(limit=10)
    assert len(trades) == 1
    assert trades[0]["question"] is None


def test_db_thread_safe_connections(tmp_path):
    """Verify different threads get different connections."""
    import threading
    db = Database(str(tmp_path / "test.db"))
    db.init()
    main_conn = db._conn()
    thread_conn = [None]
    def get_conn():
        thread_conn[0] = db._conn()
    t = threading.Thread(target=get_conn)
    t.start()
    t.join()
    assert thread_conn[0] is not main_conn


import logging
from src.dashboard.log_handler import DashboardLogHandler


def test_log_handler_captures_messages():
    import collections
    buf = collections.deque(maxlen=100)
    handler = DashboardLogHandler(buf)
    logger = logging.getLogger("test.dashboard")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info("test message")
    assert len(buf) == 1
    assert "test message" in buf[0]
    logger.removeHandler(handler)


def test_log_handler_respects_maxlen():
    import collections
    buf = collections.deque(maxlen=5)
    handler = DashboardLogHandler(buf)
    logger = logging.getLogger("test.dashboard.overflow")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    for i in range(10):
        logger.info(f"msg {i}")
    assert len(buf) == 5
    assert "msg 9" in buf[-1]
    logger.removeHandler(handler)
