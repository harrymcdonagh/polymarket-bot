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
