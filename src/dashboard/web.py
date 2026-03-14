import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from src.dashboard.service import DashboardService

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


def create_app(settings=None, db_path: str = "bot.db") -> FastAPI:
    service = DashboardService(settings=settings, db_path=db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await service.shutdown()

    app = FastAPI(title="Polymarket Bot Dashboard", lifespan=lifespan)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR)) if TEMPLATES_DIR.exists() else None

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        if templates:
            return templates.TemplateResponse("index.html", {"request": request})
        return HTMLResponse("<h1>Polymarket Bot Dashboard</h1><p>Templates not found.</p>")

    @app.get("/api/stats")
    async def api_stats():
        return await asyncio.to_thread(service.get_stats)

    @app.get("/api/trades")
    async def api_trades():
        return await asyncio.to_thread(service.get_recent_trades)

    @app.get("/api/markets")
    async def api_markets():
        markets = service.get_flagged_markets()
        return [m.model_dump() for m in markets] if markets else []

    @app.get("/api/pnl-history")
    async def api_pnl_history():
        return await asyncio.to_thread(service.get_pnl_history)

    @app.get("/api/lessons")
    async def api_lessons():
        return await asyncio.to_thread(service.get_lessons)

    @app.get("/api/status")
    async def api_status():
        return service.get_bot_status()

    @app.get("/api/logs")
    async def api_logs():
        return service.get_recent_logs()

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
