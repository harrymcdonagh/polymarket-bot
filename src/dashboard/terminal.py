import asyncio
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static, RichLog, DataTable
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Input, Button, Label
from src.dashboard.service import DashboardService


class SettingsModal(ModalScreen):
    """Modal for editing bot settings."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, service: DashboardService):
        super().__init__()
        self.service = service

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Settings (in-memory only, restart resets)", id="settings-title"),
            *self._setting_rows(),
            Button("Close", id="close-btn"),
            id="settings-modal",
        )

    def _setting_rows(self):
        from src.dashboard.service import UPDATABLE_SETTINGS
        for key in sorted(UPDATABLE_SETTINGS):
            val = getattr(self.service.settings, key)
            yield Horizontal(
                Label(f"{key}:", classes="setting-label"),
                Input(str(val), id=f"setting-{key}", classes="setting-input"),
                classes="setting-row",
            )

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "close-btn":
            self.dismiss()

    def on_input_submitted(self, event: Input.Submitted):
        key = event.input.id.replace("setting-", "")
        try:
            value = float(event.value) if "." in event.value else int(event.value)
        except ValueError:
            value = event.value
        result = self.service.update_settings(key, value)
        if not result["ok"]:
            self.notify(f"Error: {result['error']}", severity="error")
        else:
            self.notify(f"{key} = {result['value']}")


class DashboardApp(App):
    """Polymarket bot terminal dashboard."""

    CSS = """
    #main { height: 1fr; }
    #left-col { width: 40; }
    #right-col { width: 1fr; }
    #performance { height: 8; border: solid green; padding: 1; }
    #trades-panel { height: 1fr; border: solid blue; }
    #log-panel { height: 1fr; border: solid yellow; }
    #markets-panel { height: 1fr; border: solid cyan; }
    .setting-row { height: 3; }
    .setting-label { width: 30; }
    .setting-input { width: 1fr; }
    #settings-modal { width: 60; height: 30; border: solid white; background: $surface; padding: 1; align: center middle; }
    #settings-title { text-style: bold; margin-bottom: 1; }
    """

    BINDINGS = [
        Binding("s", "scan", "Scan"),
        Binding("t", "train", "Train"),
        Binding("l", "loop", "Loop"),
        Binding("c", "config", "Config"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, service: DashboardService):
        super().__init__()
        self.service = service
        self._last_log_seen = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._status_text(), id="status-bar")
        with Horizontal(id="main"):
            with Vertical(id="left-col"):
                yield Static(self._perf_text(), id="performance")
                yield DataTable(id="trades-panel")
            with Vertical(id="right-col"):
                yield RichLog(id="log-panel", highlight=True, markup=True)
                yield DataTable(id="markets-panel")
        yield Footer()

    def on_mount(self):
        trades_table = self.query_one("#trades-panel", DataTable)
        trades_table.add_columns("Market", "Side", "Amount", "Status", "PnL")
        markets_table = self.query_one("#markets-panel", DataTable)
        markets_table.add_columns("Market", "Price", "Flags")
        self.set_interval(2, self._refresh)
        self._flush_logs()

    def _status_text(self) -> str:
        status = self.service.get_bot_status()
        mode = "LIVE" if not status["dry_run"] else "DRY RUN"
        loop = " | LOOP" if status["loop_active"] else ""
        scanning = " | SCANNING..." if status["scanning"] else ""
        return f"[{mode}] Cycle #{status['cycle_count']}{loop}{scanning}"

    def _perf_text(self) -> str:
        stats = self.service.get_stats()
        return (
            f"Performance\n"
            f"Win: {stats['win_rate']:.0%} ({stats['wins']}/{stats['total_trades']})\n"
            f"PnL: ${stats['total_pnl']:.2f}\n"
            f"Today: ${stats['today_pnl']:.2f}\n"
            f"Open: {stats['open_trades']} | Snapshots: {stats['snapshot_count']}"
        )

    def _refresh(self):
        self.query_one("#status-bar", Static).update(self._status_text())
        self.query_one("#performance", Static).update(self._perf_text())
        self._refresh_trades()
        self._refresh_markets()
        self._flush_logs()

    def _refresh_trades(self):
        table = self.query_one("#trades-panel", DataTable)
        table.clear()
        for t in self.service.get_recent_trades(limit=10):
            name = (t.get("question") or t["market_id"])[:25]
            pnl = f"${t['pnl']:.2f}" if t.get("pnl") is not None else "—"
            table.add_row(name, t["side"], f"${t['amount']:.0f}", t["status"], pnl)

    def _refresh_markets(self):
        table = self.query_one("#markets-panel", DataTable)
        table.clear()
        for m in self.service.get_flagged_markets()[:15]:
            flags = ", ".join(f.value for f in m.flags) if m.flags else "—"
            table.add_row(m.question[:30], f"{m.yes_price:.2f}", flags)

    def _flush_logs(self):
        log_widget = self.query_one("#log-panel", RichLog)
        current_logs = list(self.service._log_buffer)
        total_ever = len(current_logs)
        new_count = total_ever - self._last_log_seen
        if new_count < 0 or new_count > total_ever:
            new_count = total_ever
        for line in current_logs[-new_count:] if new_count > 0 else []:
            log_widget.write(line)
        self._last_log_seen = total_ever

    async def action_scan(self):
        result = await self.service.trigger_scan(dry_run=self.service.dry_run)
        self.notify(f"Scan: {result['status']}")

    async def action_train(self):
        result = await self.service.trigger_retrain()
        self.notify(f"Retrain: {result['status']}")

    async def action_loop(self):
        result = await self.service.toggle_loop()
        state = "ON" if result.get("loop") else "OFF"
        self.notify(f"Loop: {state}")

    def action_config(self):
        self.push_screen(SettingsModal(self.service))

    async def action_quit(self):
        await self.service.shutdown()
        self.exit()
