import pytest
from unittest.mock import AsyncMock, patch
from src.notifications.telegram import TelegramNotifier


@pytest.fixture
def notifier():
    return TelegramNotifier(bot_token="test-token", chat_id="12345")


@pytest.fixture
def disabled_notifier():
    return TelegramNotifier(bot_token="", chat_id="")


def test_is_enabled(notifier):
    assert notifier.is_enabled is True


def test_is_disabled_when_no_token(disabled_notifier):
    assert disabled_notifier.is_enabled is False


def test_format_trade_alert(notifier):
    msg = notifier.format_trade_alert(
        question="Will X happen?",
        side="YES",
        amount=10.0,
        price=0.42,
        edge=0.12,
    )
    assert "Will X happen?" in msg
    assert "YES" in msg
    assert "$10.00" in msg
    assert "12.0%" in msg


def test_format_settlement_alert(notifier):
    msg = notifier.format_settlement_alert(
        question="Will X happen?",
        outcome="YES",
        predicted_prob=0.72,
        price=0.42,
        pnl=5.0,
    )
    assert "Will X happen?" in msg
    assert "YES" in msg
    assert "+$5.00" in msg


def test_format_error_alert(notifier):
    msg = notifier.format_error_alert("Research pipeline failed: timeout")
    assert "timeout" in msg


def test_format_daily_summary(notifier):
    msg = notifier.format_daily_summary(
        markets_scanned=50,
        trades_flagged=3,
        top_edge=0.15,
        top_market="Will Y happen?",
    )
    assert "50" in msg
    assert "3" in msg


@pytest.mark.asyncio
async def test_send_skips_when_disabled(disabled_notifier):
    await disabled_notifier.send("test message")


@pytest.mark.asyncio
async def test_send_calls_telegram_api(notifier):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await notifier.send("Hello world")
        mock_client.post.assert_called_once()
        call_url = mock_client.post.call_args[0][0]
        assert "test-token" in call_url
        assert "sendMessage" in call_url


def test_format_positions_update(notifier):
    positions = [
        {"question": "Will X?", "side": "YES", "price": 0.45,
         "current_price": 0.52, "unrealised_pnl": 3.11},
        {"question": "Will Y?", "side": "NO", "price": 0.70,
         "current_price": 0.65, "unrealised_pnl": 1.42},
    ]
    msg = notifier.format_positions_update(positions, total_unrealised=4.53)
    assert "Open Positions (2)" in msg
    assert "Will X?" in msg
    assert "YES" in msg
    assert "$0.45" in msg
    assert "$0.52" in msg
    assert "+$3.11" in msg
    assert "+$4.53" in msg


def test_format_positions_update_negative_total(notifier):
    positions = [
        {"question": "Will X?", "side": "YES", "price": 0.60,
         "current_price": 0.40, "unrealised_pnl": -3.53},
    ]
    msg = notifier.format_positions_update(positions, total_unrealised=-3.53)
    assert "-$3.53" in msg
