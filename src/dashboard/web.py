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
        a = service.get_activity()
        stage = a.get("stage", "idle")
        detail = a.get("detail", "")
        updated_at = a.get("updated_at")

        labels = {
            "idle": "Idle",
            "checking": "Step 0: Checking Open Trades",
            "scanning": "Step 1: Scanning Markets",
            "researching": "Step 2: Researching",
            "predicting": "Step 3: Predicting",
            "evaluating": "Step 4: Evaluating Risk",
            "postmortem": "Step 5: Running Postmortem",
        }
        label = labels.get(stage, stage)
        is_active = stage != "idle"
        dot_cls = "activity-dot active" if is_active else "activity-dot"

        detail_html = ""
        if is_active and detail:
            from html import escape
            detail_html = f'<span class="activity-detail">{escape(detail)}</span>'
        elif stage == "idle" and updated_at:
            # Show time since last activity update
            try:
                last = datetime.fromisoformat(updated_at)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                ago = (datetime.now(timezone.utc) - last).total_seconds()
                if ago < 120:
                    ago_str = f"{int(ago)}s ago"
                elif ago < 7200:
                    ago_str = f"{int(ago / 60)}m ago"
                else:
                    ago_str = f"{int(ago / 3600)}h ago"
                detail_html = f'<span class="activity-detail">Last cycle {ago_str}</span>'
            except (ValueError, TypeError):
                pass

        # Next settler countdown
        settler_html = ""
        next_settler = a.get("next_settler_at")
        if next_settler:
            try:
                next_dt = datetime.fromisoformat(next_settler)
                if next_dt.tzinfo is None:
                    next_dt = next_dt.replace(tzinfo=timezone.utc)
                remaining = (next_dt - datetime.now(timezone.utc)).total_seconds()
                if remaining > 0:
                    mins = int(remaining // 60)
                    secs = int(remaining % 60)
                    settler_html = f'<span class="activity-detail" style="margin-left:auto">Next settlement: {mins}m {secs:02d}s</span>'
                else:
                    settler_html = '<span class="activity-detail" style="margin-left:auto">Settlement running...</span>'
            except (ValueError, TypeError):
                pass

        return HTMLResponse(
            f'<div class="{dot_cls}"></div>'
            f'<span class="activity-label">{label}</span>'
            f'{detail_html}'
            f'{settler_html}'
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

    app.state.service = service
    return app
