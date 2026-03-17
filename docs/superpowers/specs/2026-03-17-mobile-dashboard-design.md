# Mobile Dashboard Design

**Date:** 2026-03-17
**Status:** Approved

## Overview

A dedicated phone-optimized dashboard served as a separate template (`mobile.html`) with its own stylesheet (`mobile.css`). The desktop dashboard remains completely untouched. The mobile view provides full control — all actions, stats, and data sections available on desktop are accessible on mobile.

## Routing & Detection

- **Auto-detection:** FastAPI middleware checks `User-Agent` for mobile keywords (`iPhone`, `Android`, `Mobile`). If detected, serves `mobile.html` instead of `index.html`.
- **Manual fallback:** `/mobile` route always serves the mobile template regardless of user-agent.
- **Desktop override:** `/desktop` route (or just `/`) always serves the desktop template on any device.
- The middleware only affects the `/` route. All `/api/*` endpoints are shared and unchanged.

## Layout — Portrait-Only, Single Column

### Sticky Header
- Pinned at top of viewport, always visible
- Left: activity indicator dot (green pulse when active) + "Polymarket Bot" title
- Right: compact action buttons — **Scan**, **Loop**, **Config** (gear icon)
- Retrain is accessed inside the Config/settings modal (less frequent action)
- Height: ~44px, matching mobile tap-target guidelines

### Activity Bar
- Below header, slim bar showing pipeline stage (Idle/Scanning/etc.) + elapsed time
- Same HTMX polling as desktop (`/api/activity`, every 2s)
- **Note:** `/api/activity` returns an HTML fragment (not JSON) containing `activity-dot`, `activity-label`, `activity-detail` classes. These must be styled in `mobile.css`.

### Stats Grid — Top 4 + Expandable
- **2x2 grid** showing: Trades, Pending, Win Rate, PnL
- Each stat card: label (uppercase, dim) + large value (color-coded)
- Below grid: "▼ more stats" toggle that expands to reveal Predictions, Accuracy, Snapshots in a row of 2 + 1 centered below
- Stats poll via `/api/stats` every 10s (same as desktop)

### Accordion Sections
Five collapsible sections, each as a card with a tap-to-toggle header:

1. **PnL Chart** — Chart.js line chart, same data as desktop (`/api/pnl-history`). Refreshes every 60s. Chart container height: 200px.
2. **Trade History** — Card-based layout (not a table). Each trade rendered as a stacked card showing: market question (clamped to 2 lines), side badge (YES/NO), amount, status, PnL. Paginated with a simple prev/next pager at the bottom. Data from `/api/trades`.
3. **Flagged Markets** — Card-based layout. Each market: question (clamped to 2 lines), YES price, result, edge%. Paginated with prev/next pager. Data from `/api/markets`.
4. **Live Feed** — Log lines in a scrollable container, same color-coding as desktop. From `/api/logs`, polls every 5s.
5. **Lessons** — List with category tags + lesson text. From `/api/lessons`, polls every 30s.

**Accordion behavior:**
- Multiple sections can be open simultaneously
- Each header shows a count/summary badge when collapsed (e.g., "130 trades", "12 flagged"). Counts sourced from `/api/stats` response (already polled every 10s) — no extra API calls needed. Shows "0" when empty.
- Smooth CSS transition on expand/collapse using `grid-template-rows: 0fr` → `1fr` (avoids max-height timing issues with variable content)
- Section open/closed state persisted to `localStorage` so it survives page refreshes
- Default: PnL Chart expanded, all others collapsed

### Settings Modal
- Same fields as desktop (BANKROLL, MAX_BET_FRACTION, etc.)
- **Retrain** button at the top of the modal, styled as a secondary action
- Full-width dialog, slightly larger input targets for touch
- Accessed via gear icon in header

### Toast Notifications
- Same as desktop, positioned at bottom center for mobile

## File Structure

```
src/dashboard/
├── templates/
│   ├── index.html          # Desktop (UNTOUCHED)
│   └── mobile.html         # New mobile template
├── static/
│   ├── style.css           # Desktop (UNTOUCHED)
│   └── mobile.css          # New mobile stylesheet
└── web.py                  # Add mobile route + UA detection middleware
```

## Shared Resources

- **CSS variables:** `mobile.css` duplicates the `:root` variables block from `style.css` (~35 lines of colors, fonts, radii). This avoids importing the full desktop stylesheet which would pull in conflicting rules (e.g., `overflow:hidden` on body). The duplication is intentional to maintain the "desktop untouched" constraint.
- **API endpoints:** All `/api/*` endpoints unchanged and shared
- **JS logic:** Mobile template has its own embedded `<script>` block (same pattern as desktop). Must re-implement `htmx:beforeSwap` handlers for: stats (render 2x2 grid + expandable), status badge, logs (color-coded lines), lessons (category tags). Accordion toggle is new (~30 lines). Also includes: chart init, toast function, settings form submission, `visibilitychange` listener to force-refresh stale data when user returns to tab.
- **External CDNs:** Same — Chart.js 4.4.0, HTMX 2.0.4, Google Fonts

## Backend Changes (web.py)

1. Add a `is_mobile_ua(request)` helper that checks the User-Agent header
2. Modify the `/` route handler to serve `mobile.html` when `is_mobile_ua()` returns true
3. Add explicit `/mobile` route that always serves `mobile.html`
4. No changes to any `/api/*` endpoint

## Design Tokens (Mobile-Specific)

- Font size base: 14px (fixed, not clamp — phone screens are predictable)
- Stat card value: 18px bold
- Accordion header: 13px, 44px min-height (tap target)
- Section content padding: 12px
- Card gap: 8px
- Border radius: 4px (same as desktop)
- Body: scrollable (not `overflow:hidden` like desktop)

## Trade/Market Card Layout (Mobile)

Instead of wide tables, each item renders as a compact card:

```
┌─────────────────────────────┐
│ Will X happen by Y?         │  ← market question (wraps)
│ YES  $25.00  pending        │  ← side badge, amount, status
│                    PnL: —   │  ← right-aligned PnL
└─────────────────────────────┘
```

- Side badge: green background for YES, red for NO
- Status: color-coded (pending=amber, settled=neon, dry_run=dim)
- PnL: green if positive, red if negative, dim if pending

## Non-Goals

- No landscape optimization
- No PWA/service worker
- No offline support
- No push notifications
- Desktop template and CSS are not modified in any way
