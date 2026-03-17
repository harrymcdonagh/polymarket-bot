# Mobile Dashboard Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a phone-optimized dashboard served as a separate template, keeping the desktop dashboard completely untouched.

**Architecture:** Separate `mobile.html` template + `mobile.css` stylesheet served via user-agent detection or explicit `/mobile` route. Shares all existing `/api/*` endpoints. No changes to desktop files (`index.html`, `style.css`).

**Tech Stack:** FastAPI, Jinja2, HTMX 2.0.4, Chart.js 4.4.0, vanilla JS/CSS

**Spec:** `docs/superpowers/specs/2026-03-17-mobile-dashboard-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/dashboard/web.py` | Add `is_mobile_ua()`, modify `/` route, add `/mobile` + `/desktop` routes |
| Create | `src/dashboard/templates/mobile.html` | Mobile template with accordion layout + embedded JS |
| Create | `src/dashboard/static/mobile.css` | Mobile-specific styles (duplicated `:root` vars + mobile layout) |
| Untouched | `src/dashboard/templates/index.html` | Desktop template |
| Untouched | `src/dashboard/static/style.css` | Desktop styles |

---

## Chunk 1: Backend routing

### Task 1: Add mobile UA detection and routing to web.py

**Files:**
- Modify: `src/dashboard/web.py:68-72` (the `/` route)

- [ ] **Step 1: Add `is_mobile_ua` helper**

Add this function above `create_app()` in `web.py`:

```python
import re

_MOBILE_UA_RE = re.compile(r"iPhone|Android|Mobile|webOS|iPod|BlackBerry", re.IGNORECASE)

def is_mobile_ua(request: Request) -> bool:
    ua = request.headers.get("user-agent", "")
    return bool(_MOBILE_UA_RE.search(ua))
```

- [ ] **Step 2: Modify the `/` route to serve mobile template on mobile UA**

Replace the existing `/` route:

```python
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if templates:
        template = "mobile.html" if is_mobile_ua(request) else "index.html"
        return templates.TemplateResponse(template, {"request": request})
    return HTMLResponse("<h1>Polymarket Bot Dashboard</h1><p>Templates not found.</p>")
```

- [ ] **Step 3: Add explicit `/mobile` route**

Add after the `/` route:

```python
@app.get("/mobile", response_class=HTMLResponse)
async def mobile(request: Request):
    if templates:
        return templates.TemplateResponse("mobile.html", {"request": request})
    return HTMLResponse("<h1>Polymarket Bot Dashboard</h1><p>Templates not found.</p>")
```

- [ ] **Step 4: Add explicit `/desktop` route**

Add after the `/mobile` route:

```python
@app.get("/desktop", response_class=HTMLResponse)
async def desktop(request: Request):
    if templates:
        return templates.TemplateResponse("index.html", {"request": request})
    return HTMLResponse("<h1>Polymarket Bot Dashboard</h1><p>Templates not found.</p>")
```

- [ ] **Step 5: Commit**

```bash
git add src/dashboard/web.py
git commit -m "feat: add mobile UA detection and /mobile + /desktop routes"
```

---

## Chunk 2: Mobile CSS

### Task 2: Create mobile.css

**Files:**
- Create: `src/dashboard/static/mobile.css`

- [ ] **Step 1: Create `mobile.css` with duplicated `:root` variables and full mobile layout styles**

The CSS file must contain all sections listed below. **This is the complete CSS class inventory — every class used in the JS must be defined here.**

**Section 1: Google Fonts import + `:root` variables**
```css
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,200..800&family=JetBrains+Mono:wght@300;400;500;600;700&display=swap');
```
Then copy the full `:root` block from `style.css` lines 3-37 (colors, fonts, radii, easing).

**Section 2: Reset + base styles** — scrollable body, 14px base font, `overflow-y: auto` (NOT hidden)

**Section 3: Sticky header** — flex row, 44px height, `position: sticky; top: 0; z-index: 100`
- `.header-left` — flex row, align center, gap 8px
- `.header-dot` — 8px green circle with pulse animation + glow shadow
- `.header-title` — bold, 13px
- `.header-status` — flex row for badge display
- `.header-actions` — flex row, gap 6px
- `.btn-sm` — compact button, 44px min touch target
- `.btn-icon` — icon-only variant

**Section 4: Activity bar** — `activity-dot`, `activity-dot.active`, `activity-label`, `activity-detail` (these class names are hardcoded in the `/api/activity` HTML response)

**Section 5: Stats grid**
- `.stats-grid` — container
- `.stats-top` — 2x2 CSS grid
- `.stat-card` — card with label + value
- `.stat-label` — 8px uppercase dim text
- `.stat-value` — 18px bold
- `.stat-value.pending` — amber color
- `.stats-more-toggle` — centered, dashed underline, 9px, dim
- `.stats-more` — 2-column grid, hidden by default, `display: none`
- `.stats-more.open` — `display: grid`
- `.stat-card.full-width` — `grid-column: span 2` for centering the 3rd "more" stat

**Section 6: Accordion**
```css
.accordion { margin: 0 12px 6px; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
.accordion-header { background: var(--surface); padding: 8px 10px; display: flex; align-items: center; min-height: 44px; cursor: pointer; gap: 8px; }
.accordion-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); flex: 1; }
.accordion-badge { font-size: 9px; color: var(--text-dim); }
.accordion-arrow { font-size: 10px; color: var(--text-dim); transition: transform 0.3s var(--ease); }
.accordion-body { display: grid; grid-template-rows: 0fr; transition: grid-template-rows 0.3s var(--ease); }
.accordion-body.open { grid-template-rows: 1fr; }
.accordion-body > div { overflow: hidden; }
.accordion-content { padding: 12px; }
```

**Section 7: Trade cards**
```css
.trade-card { background: var(--surface); border: 1px solid var(--border-subtle); border-radius: var(--radius); padding: 10px 12px; margin-bottom: 8px; }
.trade-card-question { font-family: var(--font-display); font-size: 12px; font-weight: 500; color: var(--text); line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; margin-bottom: 6px; }
.trade-card-row { display: flex; align-items: center; gap: 8px; font-size: 11px; }
.side-badge { font-weight: 700; font-size: 10px; padding: 1px 6px; border-radius: 3px; }
.side-yes { background: var(--neon-dim); color: var(--neon); }
.side-no { background: var(--red-dim); color: var(--red); }
.trade-amount { color: var(--text-secondary); }
.trade-status { font-size: 10px; }
.status-pending { color: var(--amber); }
.status-settled { color: var(--neon); }
.status-dim { color: var(--text-dim); }
.trade-pnl { margin-left: auto; font-weight: 600; }
.pnl-pos { color: var(--neon); }
.pnl-neg { color: var(--red); }
.pnl-na { color: var(--text-ghost); }
```

**Section 8: Market cards**
```css
.market-card { background: var(--surface); border: 1px solid var(--border-subtle); border-radius: var(--radius); padding: 10px 12px; margin-bottom: 8px; }
.market-card-question { font-family: var(--font-display); font-size: 12px; font-weight: 500; color: var(--text); line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; margin-bottom: 6px; }
.market-card-row { display: flex; align-items: center; gap: 8px; font-size: 11px; flex-wrap: wrap; }
.yes-price { font-weight: 600; }
.price-high { color: var(--neon); }
.price-low { color: var(--red); }
.price-mid { color: var(--text-secondary); }
.result-traded { color: var(--neon); font-weight: 600; }
.result-rejected { color: var(--red); font-size: 10px; }
.result-pending { color: var(--amber); }
.result-none { color: var(--text-ghost); font-size: 10px; }
.edge-value { color: var(--blue); font-weight: 500; margin-left: auto; }
.edge-na { color: var(--text-ghost); margin-left: auto; }
```

**Section 9: Log feed** — `.log-feed` (scrollable, max-height 300px), `.log-line`, `.log-error`, `.log-warning`, `.log-blocked` (same color rules as desktop)

**Section 10: Lessons** — `ul`, `li`, `li strong` (category tags with blue background, same as desktop pattern)

**Section 11: Status badge + tags**
```css
.badge { font-size: 0.6rem; font-weight: 700; padding: 2px 6px; border-radius: 3px; }
.badge-dry { background: var(--amber-dim); color: var(--amber); }
.badge-live { background: var(--neon-dim); color: var(--neon); }
.tag-loop { color: var(--blue); margin-left: 4px; font-weight: 600; font-size: 0.55rem; }
.tag-scan { color: var(--amber); margin-left: 4px; font-weight: 600; font-size: 0.55rem; }
.tag-err { color: var(--red); margin-left: 4px; font-weight: 600; font-size: 0.55rem; }
```

**Section 12: Pager** — `.pager`, `.pager-btn`, `.pager-info` (same as desktop but slightly larger touch targets)

**Section 13: Settings dialog** — same as desktop but full-width, 44px min input height, `.btn-retrain` (secondary style, full-width, amber border), `.btn-close` (full-width)

**Section 14: Toast** — same as desktop but `bottom: 1rem; left: 50%; transform: translateX(-50%)` for center positioning

**Section 15: Animations** — `@keyframes fade-in`, `@keyframes pulse` (for header dot), `.muted` text style

**Section 16: Scrollbar** — same thin scrollbar as desktop

- [ ] **Step 2: Commit**

```bash
git add src/dashboard/static/mobile.css
git commit -m "feat: add mobile.css with full phone layout styles"
```

---

## Chunk 3: Mobile HTML template

### Task 3: Create mobile.html — structure and header

**Files:**
- Create: `src/dashboard/templates/mobile.html`

- [ ] **Step 1: Create `mobile.html` with HTML head, sticky header, activity bar, and stats grid**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Polymarket Bot</title>
    <link rel="stylesheet" href="/static/mobile.css">
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0"></script>
</head>
<body>
    <header>
        <div class="header-left">
            <div class="header-dot"></div>
            <span class="header-title">Polymarket Bot</span>
        </div>
        <div id="status-badge" hx-get="/api/status" hx-trigger="load, every 10s"
             hx-swap="innerHTML" class="header-status"></div>
        <nav class="header-actions">
            <button hx-post="/api/scan" hx-swap="none" class="btn-sm" onclick="toast('Scan triggered')">Scan</button>
            <button hx-post="/api/loop" hx-swap="none" class="btn-sm" onclick="toast('Loop toggled')">Loop</button>
            <button onclick="document.getElementById('settings-modal').showModal()" class="btn-sm btn-icon">&#9881;</button>
        </nav>
    </header>

    <section class="activity-bar" id="activity-bar"
             hx-get="/api/activity" hx-trigger="load, every 2s" hx-swap="innerHTML">
    </section>

    <main>
        <section class="stats-grid" id="stats-grid"
                 hx-get="/api/stats" hx-trigger="load, every 10s" hx-swap="innerHTML">
        </section>

        <!-- Accordion sections here (Task 4) -->
    </main>

    <!-- Settings dialog here (Task 5) -->

    <script>
    // JS here (Tasks 4-6)
    </script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add src/dashboard/templates/mobile.html
git commit -m "feat: add mobile.html skeleton with header, activity bar, stats"
```

### Task 4: Add accordion sections to mobile.html

**Files:**
- Modify: `src/dashboard/templates/mobile.html`

- [ ] **Step 1: Add the 5 accordion sections inside `<main>` after the stats grid**

Each accordion follows this pattern:
```html
<section class="accordion" id="acc-pnl">
    <div class="accordion-header" onclick="toggleAccordion('pnl')">
        <span class="accordion-title">PnL Chart</span>
        <span class="accordion-badge" id="badge-pnl"></span>
        <span class="accordion-arrow" id="arrow-pnl">▶</span>
    </div>
    <div class="accordion-body" id="body-pnl">
        <div>
            <div class="accordion-content">
                <canvas id="pnl-chart" style="height:200px;"></canvas>
            </div>
        </div>
    </div>
</section>
```

The 5 sections:
1. **PnL Chart** (`acc-pnl`) — contains `<canvas id="pnl-chart">`
2. **Trade History** (`acc-trades`) — contains `<div id="trades-list"></div>`
3. **Flagged Markets** (`acc-markets`) — contains `<div id="markets-list"></div>`
4. **Live Feed** (`acc-feed`) — contains `<div id="log-feed" class="log-feed" hx-get="/api/logs" hx-trigger="load, every 5s" hx-swap="innerHTML"></div>`
5. **Lessons** (`acc-lessons`) — contains `<div id="lessons-list" hx-get="/api/lessons" hx-trigger="load, every 30s" hx-swap="innerHTML"></div>`

- [ ] **Step 2: Commit**

```bash
git add src/dashboard/templates/mobile.html
git commit -m "feat: add 5 accordion sections to mobile.html"
```

### Task 5: Add settings modal and retrain button to mobile.html

**Files:**
- Modify: `src/dashboard/templates/mobile.html`

- [ ] **Step 1: Add settings dialog before `</body>`**

```html
<dialog id="settings-modal">
    <h2>Settings</h2>
    <button hx-post="/api/retrain" hx-swap="none" class="btn-retrain" onclick="toast('Retrain triggered')">Retrain Model</button>
    <p class="muted">In-memory only. Restart resets to .env values.</p>
    <form id="settings-form">
        <label>BANKROLL <input type="number" name="BANKROLL" step="any"></label>
        <label>MAX_BET_FRACTION <input type="number" name="MAX_BET_FRACTION" step="0.01"></label>
        <label>CONFIDENCE_THRESHOLD <input type="number" name="CONFIDENCE_THRESHOLD" step="0.01"></label>
        <label>MIN_EDGE_THRESHOLD <input type="number" name="MIN_EDGE_THRESHOLD" step="0.01"></label>
        <label>MAX_DAILY_LOSS <input type="number" name="MAX_DAILY_LOSS" step="any"></label>
        <label>LOOP_INTERVAL <input type="number" name="LOOP_INTERVAL" step="1"></label>
    </form>
    <button onclick="document.getElementById('settings-modal').close()" class="btn-close">Close</button>
</dialog>
```

- [ ] **Step 2: Commit**

```bash
git add src/dashboard/templates/mobile.html
git commit -m "feat: add settings modal with retrain button to mobile.html"
```

---

## Chunk 4: Mobile JavaScript

### Task 6: Add all JavaScript to mobile.html

**Files:**
- Modify: `src/dashboard/templates/mobile.html` (the `<script>` block)

- [ ] **Step 1: Add utility functions (esc, toast, logClass)**

```javascript
function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

function toast(msg) {
    const el = document.createElement('div');
    el.className = 'toast';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}

function logClass(line) {
    if (line.includes('[ERROR]')) return 'log-line log-error';
    if (line.includes('[WARNING]')) return 'log-line log-warning';
    if (line.includes('[BLOCKED]')) return 'log-line log-blocked';
    return 'log-line';
}
```

- [ ] **Step 2: Add accordion toggle + localStorage persistence**

```javascript
const ACCORDION_KEY = 'mobile-accordion-state';
const DEFAULT_STATE = { pnl: true, trades: false, markets: false, feed: false, lessons: false };

function getAccordionState() {
    try {
        return JSON.parse(localStorage.getItem(ACCORDION_KEY)) || DEFAULT_STATE;
    } catch { return DEFAULT_STATE; }
}

function saveAccordionState(state) {
    localStorage.setItem(ACCORDION_KEY, JSON.stringify(state));
}

function toggleAccordion(id) {
    const state = getAccordionState();
    state[id] = !state[id];
    saveAccordionState(state);
    applyAccordionState();
    // Resize chart when PnL accordion opens (Chart.js needs non-zero dimensions)
    if (id === 'pnl' && state[id] && pnlChart) {
        setTimeout(() => pnlChart.resize(), 350);
    }
}

function applyAccordionState() {
    const state = getAccordionState();
    for (const [id, open] of Object.entries(state)) {
        const body = document.getElementById('body-' + id);
        const arrow = document.getElementById('arrow-' + id);
        if (body) {
            body.classList.toggle('open', open);
            if (arrow) arrow.textContent = open ? '▼' : '▶';
        }
    }
}

// Apply on load
applyAccordionState();
```

- [ ] **Step 3: Add PnL chart initialization (adapted from desktop)**

```javascript
let pnlChart = null;
async function refreshChart() {
    const resp = await fetch('/api/pnl-history');
    const data = await resp.json();
    const labels = data.map(d => d.date);
    const values = data.map(d => d.cumulative_pnl);
    const canvas = document.getElementById('pnl-chart');
    if (!canvas) return;

    if (!pnlChart) {
        const ctx = canvas.getContext('2d');
        const gradient = ctx.createLinearGradient(0, 0, 0, 200);
        gradient.addColorStop(0, 'rgba(0, 230, 138, 0.12)');
        gradient.addColorStop(0.6, 'rgba(0, 230, 138, 0.02)');
        gradient.addColorStop(1, 'rgba(0, 230, 138, 0)');

        pnlChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: 'Cumulative PnL ($)',
                    data: values,
                    borderColor: '#00E68A',
                    borderWidth: 1.5,
                    backgroundColor: gradient,
                    fill: true,
                    tension: 0.35,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    pointHoverBackgroundColor: '#00E68A',
                    pointHoverBorderColor: '#0B0E14',
                    pointHoverBorderWidth: 2,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { intersect: false, mode: 'index' },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: '#131820',
                        borderColor: '#1C2333',
                        borderWidth: 1,
                        titleFont: { family: 'Bricolage Grotesque', size: 10, weight: '600' },
                        bodyFont: { family: 'JetBrains Mono', size: 11, weight: '500' },
                        titleColor: '#566175',
                        bodyColor: '#00E68A',
                        padding: { x: 8, y: 6 },
                        cornerRadius: 4,
                        displayColors: false,
                        callbacks: { label: ctx => '$' + ctx.parsed.y.toFixed(2) }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(28, 35, 51, 0.5)', drawTicks: false },
                        ticks: { font: { family: 'JetBrains Mono', size: 8 }, color: '#2E3848', maxRotation: 0, maxTicksLimit: 4 },
                        border: { display: false },
                    },
                    y: {
                        grid: { color: 'rgba(28, 35, 51, 0.5)', drawTicks: false },
                        ticks: { font: { family: 'JetBrains Mono', size: 8 }, color: '#2E3848', callback: v => '$' + v },
                        border: { display: false },
                    }
                },
                layout: { padding: { top: 2 } }
            }
        });
    } else {
        pnlChart.data.labels = labels;
        pnlChart.data.datasets[0].data = values;
        pnlChart.update('none');
    }
}
refreshChart();
setInterval(refreshChart, 60000);
```

- [ ] **Step 4: Add trades loader with card layout and pagination**

```javascript
let tradesPage = 1;
const TRADES_PER_PAGE = 20;

async function loadTrades(page) {
    tradesPage = page || 1;
    const resp = await fetch(`/api/trades?page=${tradesPage}&per_page=${TRADES_PER_PAGE}`);
    const data = await resp.json();
    const el = document.getElementById('trades-list');
    if (!el) return;

    // Update badge
    const badge = document.getElementById('badge-trades');
    if (badge) badge.textContent = data.total + ' trades';

    if (data.total === 0) { el.innerHTML = '<p class="muted">No trades yet.</p>'; return; }

    let html = '';
    data.items.forEach(t => {
        const name = esc(t.question || t.market_id || '');
        const pnl = t.pnl != null ? t.pnl : (t.hypothetical_pnl != null ? t.hypothetical_pnl : null);
        const pnlStr = pnl !== null ? (pnl >= 0 ? '+' : '') + '$' + Math.abs(pnl).toFixed(2) : '\u2014';
        const pnlCls = pnl !== null ? (pnl >= 0 ? 'pnl-pos' : 'pnl-neg') : 'pnl-na';
        const sideCls = t.side === 'YES' ? 'side-yes' : 'side-no';
        const statusCls = t.status === 'dry_run' ? 'status-pending' : t.status === 'dry_run_settled' ? 'status-settled' : 'status-dim';
        html += `<div class="trade-card">
            <div class="trade-card-question">${name}</div>
            <div class="trade-card-row">
                <span class="side-badge ${sideCls}">${esc(t.side)}</span>
                <span class="trade-amount">$${t.amount.toFixed(0)}</span>
                <span class="trade-status ${statusCls}">${esc(t.status)}</span>
                <span class="trade-pnl ${pnlCls}">${pnlStr}</span>
            </div>
        </div>`;
    });

    // Pager
    const totalPages = Math.ceil(data.total / TRADES_PER_PAGE);
    if (totalPages > 1) {
        html += `<div class="pager">
            <button class="pager-btn" ${tradesPage <= 1 ? 'disabled' : ''} onclick="loadTrades(${tradesPage - 1})">&laquo;</button>
            <span class="pager-info">${tradesPage} / ${totalPages}</span>
            <button class="pager-btn" ${tradesPage >= totalPages ? 'disabled' : ''} onclick="loadTrades(${tradesPage + 1})">&raquo;</button>
        </div>`;
    }
    el.innerHTML = html;
}
loadTrades();
setInterval(() => loadTrades(tradesPage), 10000);
```

- [ ] **Step 5: Add markets loader with card layout and pagination**

```javascript
let marketsPage = 1;
const MARKETS_PER_PAGE = 20;

async function loadMarkets(page) {
    marketsPage = page || 1;
    const resp = await fetch(`/api/markets?page=${marketsPage}&per_page=${MARKETS_PER_PAGE}`);
    const data = await resp.json();
    const el = document.getElementById('markets-list');
    if (!el) return;

    const badge = document.getElementById('badge-markets');
    if (badge) badge.textContent = data.total + ' flagged';

    if (data.total === 0) { el.innerHTML = '<p class="muted">No flagged markets.</p>'; return; }

    let html = '';
    data.items.forEach(m => {
        const price = m.yes_price.toFixed(2);
        const priceCls = m.yes_price > 0.7 ? 'price-high' : m.yes_price < 0.3 ? 'price-low' : 'price-mid';
        let resultHtml = '';
        if (m.trade_status) {
            resultHtml = `<span class="result-traded">${esc(m.recommended_side)} $${m.trade_amount.toFixed(0)}</span>`;
        } else if (m.approved === 0 && m.rejection_reason) {
            resultHtml = `<span class="result-rejected">${esc(m.rejection_reason)}</span>`;
        } else if (m.recommended_side) {
            resultHtml = `<span class="result-pending">${esc(m.recommended_side)}</span>`;
        } else {
            resultHtml = '<span class="result-none">Not evaluated</span>';
        }
        const edgeHtml = m.edge != null
            ? `<span class="edge-value">${(m.edge * 100).toFixed(1)}%</span>`
            : '<span class="edge-na">\u2014</span>';

        html += `<div class="market-card">
            <div class="market-card-question">${esc(m.question||'')}</div>
            <div class="market-card-row">
                <span class="yes-price ${priceCls}">${price}</span>
                ${resultHtml}
                ${edgeHtml}
            </div>
        </div>`;
    });

    const totalPages = Math.ceil(data.total / MARKETS_PER_PAGE);
    if (totalPages > 1) {
        html += `<div class="pager">
            <button class="pager-btn" ${marketsPage <= 1 ? 'disabled' : ''} onclick="loadMarkets(${marketsPage - 1})">&laquo;</button>
            <span class="pager-info">${marketsPage} / ${totalPages}</span>
            <button class="pager-btn" ${marketsPage >= totalPages ? 'disabled' : ''} onclick="loadMarkets(${marketsPage + 1})">&raquo;</button>
        </div>`;
    }
    el.innerHTML = html;
}
loadMarkets();
setInterval(() => loadMarkets(marketsPage), 10000);
```

- [ ] **Step 6: Add HTMX beforeSwap handlers for status, stats, logs, lessons**

```javascript
// Store latest stats for badge counts
let latestStats = {};

htmx.on('htmx:beforeSwap', function(evt) {

    /* Status badge */
    if (evt.detail.target.id === 'status-badge') {
        const d = JSON.parse(evt.detail.xhr.responseText);
        const mode = d.dry_run ? 'DRY RUN' : 'LIVE';
        const cls = d.dry_run ? 'badge-dry' : 'badge-live';
        const loop = d.loop_active ? '<span class="tag-loop">LOOP</span>' : '';
        const scan = d.scanning ? '<span class="tag-scan">SCANNING</span>' : '';
        evt.detail.serverResponse =
            `<span class="badge ${cls}">${mode}</span>` + loop + scan +
            (d.last_error ? '<span class="tag-err">ERR</span>' : '');
    }

    /* Stats grid — top 4 + expandable more */
    if (evt.detail.target.id === 'stats-grid') {
        const s = JSON.parse(evt.detail.xhr.responseText);
        latestStats = s;
        const pnlColor = s.total_pnl >= 0 ? 'var(--neon)' : 'var(--red)';
        const pnlSign = s.total_pnl >= 0 ? '+' : '';
        const approvalRate = s.total_predictions > 0
            ? ((s.approved / s.total_predictions) * 100).toFixed(0) + '%'
            : '\u2014';
        const accStr = s.prediction_accuracy && s.prediction_accuracy.evaluated > 0
            ? (s.prediction_accuracy.accuracy * 100).toFixed(0) + '%'
            : '\u2014';

        evt.detail.serverResponse = `
            <div class="stats-top">
                <div class="stat-card">
                    <div class="stat-label">Trades</div>
                    <div class="stat-value">${s.total_trades}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Pending</div>
                    <div class="stat-value pending">${s.dry_run_pending || 0}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Win Rate</div>
                    <div class="stat-value">${(s.win_rate*100).toFixed(0)}%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">PnL</div>
                    <div class="stat-value" style="color:${pnlColor}">${pnlSign}$${Math.abs(s.total_pnl).toFixed(2)}</div>
                </div>
            </div>
            <div class="stats-more-toggle" onclick="this.nextElementSibling.classList.toggle('open');this.textContent=this.nextElementSibling.classList.contains('open')?'▲ less stats':'▼ more stats'">▼ more stats</div>
            <div class="stats-more">
                <div class="stat-card">
                    <div class="stat-label">Predictions</div>
                    <div class="stat-value">${s.total_predictions || 0}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Accuracy</div>
                    <div class="stat-value" style="color:${accStr !== '\u2014' ? 'var(--neon)' : 'var(--text-ghost)'}">${accStr}</div>
                </div>
                <div class="stat-card full-width">
                    <div class="stat-label">Snapshots</div>
                    <div class="stat-value">${s.snapshot_count}</div>
                </div>
            </div>`;

        // Update accordion badges from stats
        const bt = document.getElementById('badge-trades');
        if (bt) bt.textContent = s.total_trades + ' trades';
    }

    /* Log feed */
    if (evt.detail.target.id === 'log-feed') {
        const logs = JSON.parse(evt.detail.xhr.responseText);
        if (logs.length === 0) {
            evt.detail.serverResponse = '<p class="muted">No logs yet.</p>';
        } else {
            evt.detail.serverResponse = logs.map(l =>
                `<div class="${logClass(l)}">${esc(l)}</div>`
            ).join('');
        }
    }

    /* Lessons */
    if (evt.detail.target.id === 'lessons-list') {
        const lessons = JSON.parse(evt.detail.xhr.responseText);
        const badge = document.getElementById('badge-lessons');
        if (badge) badge.textContent = lessons.length + ' lessons';
        if (lessons.length === 0) {
            evt.detail.serverResponse = '<p class="muted">No lessons yet.</p>';
        } else {
            evt.detail.serverResponse = '<ul>' + lessons.map(l =>
                `<li><strong>${esc(l.category)}</strong> ${esc(l.lesson)}</li>`
            ).join('') + '</ul>';
        }
    }
});
```

- [ ] **Step 7: Add settings form handler + visibilitychange listener**

```javascript
/* Settings form */
document.getElementById('settings-form').addEventListener('change', async (e) => {
    const key = e.target.name;
    const value = parseFloat(e.target.value);
    const resp = await fetch('/api/settings', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key, value})
    });
    const result = await resp.json();
    if (!result.ok) toast('Error: ' + result.error);
    else toast(key + ' updated');
});

/* Force refresh when returning to tab */
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
        htmx.trigger(document.getElementById('activity-bar'), 'load');
        htmx.trigger(document.getElementById('stats-grid'), 'load');
        loadTrades(tradesPage);
        loadMarkets(marketsPage);
        refreshChart();
    }
});
```

- [ ] **Step 8: Commit**

```bash
git add src/dashboard/templates/mobile.html
git commit -m "feat: add all mobile JS — accordion, chart, trades, markets, HTMX handlers"
```

---

## Chunk 5: Smoke test and polish

### Task 7: Manual smoke test on phone

- [ ] **Step 1: Start the dashboard locally**

```bash
python run.py --web --host 0.0.0.0
```

- [ ] **Step 2: Open on phone via local IP (e.g., `http://192.168.x.x:8050`)**

Verify:
- Sticky header stays pinned while scrolling
- Scan, Loop, Config buttons work
- Activity bar updates every 2s
- Stats grid shows 4 cards, "more stats" expands/collapses
- PnL chart renders in accordion
- Trade History shows card layout with prev/next pagination
- Flagged Markets shows card layout with pagination
- Live Feed shows color-coded log lines
- Lessons shows category tags
- Accordion open/close persists across page refresh (localStorage)
- Settings modal opens from gear icon, Retrain button visible at top
- Toast notifications appear at bottom center
- No horizontal scroll anywhere

- [ ] **Step 3: Open on desktop browser — verify desktop view is unchanged**

Visit `http://localhost:8050` — should show the original desktop dashboard with no changes.

- [ ] **Step 4: Test `/mobile` route on desktop browser**

Visit `http://localhost:8050/mobile` — should show mobile layout even on desktop UA.

- [ ] **Step 5: Fix any issues found, commit**

```bash
git add src/dashboard/templates/mobile.html src/dashboard/static/mobile.css
git commit -m "fix: mobile dashboard polish from smoke test"
```

### Task 8: Add .superpowers to .gitignore

- [ ] **Step 1: Check if `.superpowers/` is already in `.gitignore`**

```bash
grep -q superpowers .gitignore
```

- [ ] **Step 2: If not present, add it**

Append `.superpowers/` to `.gitignore`.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: add .superpowers/ to gitignore"
```
