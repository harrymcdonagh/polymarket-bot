import asyncio
import base64
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from src.dashboard.service import DashboardService
from src.config import Settings

DASHBOARD_DIR = Path(__file__).parent
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
STATIC_DIR = DASHBOARD_DIR / "static"


class SettingsRequest(BaseModel):
    key: str
    value: float | int | str


class LoopRequest(BaseModel):
    interval: int | None = None


class ScanRequest(BaseModel):
    dry_run: bool | None = None


_MOBILE_UA_RE = re.compile(r"iPhone|Android|Mobile|webOS|iPod|BlackBerry", re.IGNORECASE)

def is_mobile_ua(request: Request) -> bool:
    ua = request.headers.get("user-agent", "")
    return bool(_MOBILE_UA_RE.search(ua))


def create_app(settings=None, db_path: str | None = None) -> FastAPI:
    settings = settings or Settings()
    service = DashboardService(settings=settings, db_path=db_path or settings.DB_PATH)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await service.shutdown()

    app = FastAPI(title="Polymarket Bot Dashboard", lifespan=lifespan)

    password = settings.DASHBOARD_PASSWORD if settings else ""

    if password:
        @app.middleware("http")
        async def basic_auth(request: Request, call_next):
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Basic "):
                try:
                    decoded = base64.b64decode(auth[6:]).decode()
                    _, pwd = decoded.split(":", 1)
                    if secrets.compare_digest(pwd, password):
                        return await call_next(request)
                except Exception:
                    pass
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": "Basic realm=\"Polymarket Bot\""},
                content="Unauthorized",
            )

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR)) if TEMPLATES_DIR.exists() else None

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        if templates:
            template = "mobile.html" if is_mobile_ua(request) else "index.html"
            return templates.TemplateResponse(template, {"request": request})
        return HTMLResponse("<h1>Polymarket Bot Dashboard</h1><p>Templates not found.</p>")

    @app.get("/mobile", response_class=HTMLResponse)
    async def mobile(request: Request):
        if templates:
            return templates.TemplateResponse("mobile.html", {"request": request})
        return HTMLResponse("<h1>Polymarket Bot Dashboard</h1><p>Templates not found.</p>")

    @app.get("/desktop", response_class=HTMLResponse)
    async def desktop(request: Request):
        if templates:
            return templates.TemplateResponse("index.html", {"request": request})
        return HTMLResponse("<h1>Polymarket Bot Dashboard</h1><p>Templates not found.</p>")

    @app.get("/api/stats")
    async def api_stats():
        return await asyncio.to_thread(service.get_stats)

    @app.get("/api/trades")
    async def api_trades(page: int = 1, per_page: int = 10):
        all_trades = await asyncio.to_thread(service.get_recent_trades, 200)
        total = len(all_trades)
        start = (page - 1) * per_page
        return {"items": all_trades[start:start + per_page], "total": total, "page": page, "per_page": per_page}

    @app.get("/api/markets")
    async def api_markets(page: int = 1, per_page: int = 10):
        markets = service.get_flagged_markets()
        if not markets:
            return {"items": [], "total": 0, "page": page, "per_page": per_page}
        all_items = [m.model_dump() if hasattr(m, 'model_dump') else m for m in markets]
        total = len(all_items)
        start = (page - 1) * per_page
        return {"items": all_items[start:start + per_page], "total": total, "page": page, "per_page": per_page}

    @app.get("/api/pnl-history")
    async def api_pnl_history():
        return await asyncio.to_thread(service.get_pnl_history)

    @app.get("/api/positions")
    async def api_positions():
        return await asyncio.to_thread(service.get_open_positions)

    @app.get("/api/lessons")
    async def api_lessons():
        return await asyncio.to_thread(service.get_lessons)

    @app.get("/api/feature-suggestions")
    async def api_feature_suggestions():
        return await asyncio.to_thread(service.get_feature_suggestions)

    @app.get("/api/status")
    async def api_status():
        return service.get_bot_status()

    @app.get("/api/activity", response_class=HTMLResponse)
    async def api_activity():
        from datetime import datetime, timezone
        from html import escape
        import json as _json

        now = datetime.now(timezone.utc)

        def _countdown(next_at_str):
            """Return countdown string from an ISO timestamp, or None."""
            if not next_at_str:
                return None
            try:
                next_dt = datetime.fromisoformat(next_at_str)
                if next_dt.tzinfo is None:
                    next_dt = next_dt.replace(tzinfo=timezone.utc)
                remaining = (next_dt - now).total_seconds()
                if remaining <= 0:
                    return None
                if remaining < 120:
                    return f"{int(remaining)}s"
                elif remaining < 7200:
                    return f"{int(remaining // 60)}m {int(remaining % 60):02d}s"
                else:
                    return f"{int(remaining // 3600)}h {int((remaining % 3600) // 60)}m"
            except (ValueError, TypeError):
                return None

        def _read_json(path):
            try:
                with open(path, "r") as f:
                    return _json.load(f)
            except (FileNotFoundError, _json.JSONDecodeError):
                return {}

        def _render_bar(name, stage, detail, countdown):
            is_active = stage != "idle"
            dot = "activity-dot active" if is_active else "activity-dot"
            if is_active and detail:
                info = f'<span class="activity-detail">{escape(detail)}</span>'
            elif countdown:
                info = f'<span class="activity-detail">{countdown}</span>'
            else:
                info = ''
            return (
                f'<div style="display:flex;align-items:center;gap:0.5rem;flex:1;min-width:0">'
                f'<div class="{dot}"></div>'
                f'<span class="activity-label">{escape(name)}</span>'
                f'{info}'
                f'</div>'
            )

        # Bot activity (from pipeline's write_activity)
        bot_activity = service.get_activity()
        bot_stage = bot_activity.get("stage", "idle")
        bot_detail = bot_activity.get("detail", "")
        bot_next = _read_json("data/bot_activity.json")
        bot_countdown = _countdown(bot_next.get("next_at"))
        if bot_stage == "idle" and bot_countdown:
            bot_detail_str = bot_countdown
        elif bot_stage == "idle":
            bot_detail_str = ""
        else:
            bot_detail_str = bot_detail

        # Settler activity
        settler = _read_json("data/settler_activity.json")
        settler_stage = settler.get("stage", "idle")
        settler_detail = settler.get("detail", "")
        settler_countdown = _countdown(settler.get("next_at"))
        if settler_stage == "idle" and settler_countdown:
            settler_detail_str = settler_countdown
        elif settler_stage == "idle":
            settler_detail_str = ""
        else:
            settler_detail_str = settler_detail

        bot_label = {
            "idle": "Bot: Idle",
            "checking": "Bot: Checking Trades",
            "scanning": "Bot: Scanning",
            "researching": "Bot: Researching",
            "predicting": "Bot: Predicting",
            "evaluating": "Bot: Evaluating",
        }.get(bot_stage, f"Bot: {bot_stage}")

        settler_label = {
            "idle": "Settler: Idle",
            "settling": "Settler: Running",
        }.get(settler_stage, f"Settler: {settler_stage}")

        return HTMLResponse(
            _render_bar(bot_label, bot_stage, bot_detail_str, bot_countdown)
            + _render_bar(settler_label, settler_stage, settler_detail_str, settler_countdown)
        )

    @app.get("/api/logs")
    async def api_logs():
        return service.get_recent_logs(limit=200)

    @app.post("/api/scan", status_code=202)
    async def api_scan(body: ScanRequest | None = None):
        dry_run = body.dry_run if body and body.dry_run is not None else service.dry_run
        result = await service.trigger_scan(dry_run=dry_run)
        if result["status"] == "already_running":
            return JSONResponse(result, status_code=409)
        if result["status"] == "error":
            return JSONResponse(result, status_code=500)
        return result

    @app.post("/api/retrain", status_code=202)
    async def api_retrain():
        result = await service.trigger_retrain()
        if result["status"] == "already_running":
            return JSONResponse(result, status_code=409)
        return result

    @app.post("/api/loop")
    async def api_loop(body: LoopRequest | None = None):
        interval = body.interval if body else None
        return await service.toggle_loop(interval=interval)

    @app.post("/api/settings")
    async def api_settings(body: SettingsRequest):
        result = service.update_settings(body.key, body.value)
        if not result["ok"]:
            return JSONResponse(result, status_code=400)
        return result

    @app.get("/crypto", response_class=HTMLResponse)
    async def crypto_page(request: Request):
        if templates:
            return templates.TemplateResponse("crypto.html", {"request": request})
        return HTMLResponse("<h1>Crypto Dashboard</h1><p>Template not found.</p>")

    @app.get("/api/crypto/stats")
    async def api_crypto_stats():
        stats = await asyncio.to_thread(service.db.get_crypto_trade_stats)
        daily_pnl = await asyncio.to_thread(service.db.get_crypto_daily_pnl)
        stats["today_pnl"] = round(daily_pnl, 2)
        stats["bankroll"] = getattr(service.settings, 'CRYPTO_BANKROLL', 100.0)
        return stats

    @app.get("/api/crypto/trades")
    async def api_crypto_trades(page: int = 1, per_page: int = 20):
        all_trades = await asyncio.to_thread(service.db.get_recent_crypto_trades, 200)
        total = len(all_trades)
        start = (page - 1) * per_page
        return {"items": all_trades[start:start + per_page], "total": total, "page": page}

    @app.get("/api/crypto/pnl-history")
    async def api_crypto_pnl_history():
        return await asyncio.to_thread(service.db.get_crypto_pnl_history)

    @app.get("/api/crypto/strategies")
    async def api_crypto_strategies():
        return await asyncio.to_thread(service.db.get_crypto_strategy_stats)

    @app.get("/api/crypto/incubation")
    async def api_crypto_incubation():
        return await asyncio.to_thread(service.db.get_all_incubations)

    @app.get("/api/crypto/backtests")
    async def api_crypto_backtests():
        import math
        results = await asyncio.to_thread(service.db.get_top_crypto_backtests, 5)
        for r in results:
            for k, v in r.items():
                if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
                    r[k] = None
        return results

    # ── Crypto bot control endpoints ──

    _backtest_running = False

    @app.post("/api/crypto/run-backtest")
    async def api_crypto_run_backtest(request: Request):
        nonlocal _backtest_running
        if _backtest_running:
            return JSONResponse({"status": "already_running"}, status_code=409)
        body = await request.json()
        candles = int(body.get("candles", 5000))
        candles = max(100, min(candles, 10000))

        import subprocess, os
        crypto_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "crypto")
        # Try crypto venv first, fall back to system python
        venv_python = os.path.join(crypto_dir, "venv", "bin", "python")
        if not os.path.exists(venv_python):
            venv_python = os.path.join(crypto_dir, "venv", "Scripts", "python.exe")
        if not os.path.exists(venv_python):
            return JSONResponse({"status": "error", "message": "Crypto venv not found"}, status_code=500)

        # Update candle count in .env
        env_path = os.path.join(crypto_dir, ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()
            with open(env_path, "w") as f:
                for line in lines:
                    if line.startswith("CRYPTO_CANDLE_WINDOW="):
                        f.write(f"CRYPTO_CANDLE_WINDOW={candles}\n")
                    else:
                        f.write(line)

        async def run_backtest():
            nonlocal _backtest_running
            _backtest_running = True
            try:
                # Clear old backtests first
                service.db._conn().execute("DELETE FROM crypto_backtests")
                service.db._conn().commit()
                proc = await asyncio.create_subprocess_exec(
                    venv_python, "run.py", "--backtest",
                    cwd=crypto_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()
            finally:
                _backtest_running = False

        asyncio.create_task(run_backtest())
        return {"status": "started", "candles": candles}

    @app.get("/api/crypto/backtest-status")
    async def api_crypto_backtest_status():
        return {"running": _backtest_running}

    @app.get("/api/crypto/current-config")
    async def api_crypto_current_config():
        """Read current strategy from crypto .env file."""
        import os
        crypto_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "crypto")
        env_path = os.path.join(crypto_dir, ".env")
        config = {"strategy": "macd_hist", "params": "{}", "candles": 5000}
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("CRYPTO_STRATEGY="):
                        config["strategy"] = line.split("=", 1)[1]
                    elif line.startswith("CRYPTO_STRATEGY_PARAMS="):
                        config["params"] = line.split("=", 1)[1]
                    elif line.startswith("CRYPTO_CANDLE_WINDOW="):
                        config["candles"] = int(line.split("=", 1)[1])
        return config

    @app.post("/api/crypto/set-strategy")
    async def api_crypto_set_strategy(request: Request):
        """Update strategy in crypto .env and restart the bot service."""
        body = await request.json()
        strategy = body.get("strategy", "")
        params = body.get("params", "")
        if not strategy or not params:
            return JSONResponse({"status": "error", "message": "strategy and params required"}, status_code=400)

        import os
        crypto_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "crypto")
        env_path = os.path.join(crypto_dir, ".env")
        if not os.path.exists(env_path):
            return JSONResponse({"status": "error", "message": ".env not found"}, status_code=500)

        with open(env_path, "r") as f:
            lines = f.readlines()
        with open(env_path, "w") as f:
            for line in lines:
                if line.startswith("CRYPTO_STRATEGY="):
                    f.write(f"CRYPTO_STRATEGY={strategy}\n")
                elif line.startswith("CRYPTO_STRATEGY_PARAMS="):
                    f.write(f"CRYPTO_STRATEGY_PARAMS={params}\n")
                else:
                    f.write(line)

        # Try to restart the bot service
        restarted = False
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "systemctl", "restart", "polymarket-crypto-bot",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.wait(), timeout=10)
            restarted = proc.returncode == 0
        except Exception:
            pass

        return {"status": "ok", "strategy": strategy, "params": params, "restarted": restarted}

    app.state.service = service
    return app
