# Claude Code Workflow Optimization

**Date:** 2026-03-19
**Goal:** Reduce friction when using Claude Code in this repo — fewer permission prompts, better memory between sessions, automated testing/linting, and remote deployment commands.

## 1. Permissions Cleanup

Replace the 89 one-off permission entries in `.claude/settings.local.json` with broad patterns scoped to this project.

### Allow list:
```
Bash(python:*)        — run scripts, tests, imports
Bash(pip:*)           — install/list packages
Bash(git add:*)       — staging
Bash(git commit:*)    — commits
Bash(git push:*)      — push (non-force)
Bash(git checkout:*)  — branch switching
Bash(git merge:*)     — merges
Bash(git diff:*)      — diffs
Bash(git log:*)       — history
Bash(git status:*)    — status
Bash(git branch:*)    — branch management
Bash(curl:*)          — API calls
Bash(ls:*)            — list files
Bash(wc:*)            — line counts
Bash(cat:*)           — read files
Bash(find:*)          — find files
Bash(grep:*)          — search
Bash(which:*)         — check binaries
Bash(chmod:*)         — permissions
Bash(ssh:*)           — remote access (for /deploy, /status)
Bash(scp:*)           — file transfer
WebSearch             — web research
WebFetch              — fetch URLs
```

### Deny list:
```
Bash(rm -rf:*)            — no recursive delete
Bash(git push --force:*)  — no force push
Bash(git reset --hard:*)  — no hard reset
```

**Still prompts for:** `sudo`, `rm` (non-rf), anything not in the allow list.

## 2. Hooks — Auto-Test and Auto-Lint

Two `PostToolUse` hooks in `.claude/settings.local.json` that fire after any `.py` file is edited.

### Auto-test hook:
```json
{
  "event": "PostToolUse",
  "tools": ["Edit", "Write"],
  "match_files": ["**/*.py"],
  "command": "python -m pytest tests/ -x -q 2>&1 | tail -5"
}
```
Runs fast-fail test suite. Shows last 5 lines (pass count or first failure).

### Auto-lint hook:
```json
{
  "event": "PostToolUse",
  "tools": ["Edit", "Write"],
  "match_files": ["**/*.py"],
  "command": "ruff check --fix . 2>&1 | tail -5"
}
```
Runs ruff with auto-fix. Requires adding `ruff` to dev dependencies.

### Ruff setup:
- Add `ruff` to `pyproject.toml` dev dependencies
- Add minimal `[tool.ruff]` config to `pyproject.toml` (line length 120, Python 3.11 target, match existing code style)

## 3. Custom Slash Commands

Two skill files in `.claude/commands/` for remote server management.

### `/deploy`
**File:** `.claude/commands/deploy.md`

**Steps:**
1. `git push origin master`
2. SSH to droplet: `ssh <user>@<host>`
3. `cd /opt/polymarket-bot && git pull origin master`
4. `sudo systemctl restart polymarket-settler polymarket-web` (not polymarket-bot since pipeline is currently stopped)
5. Show service status: `sudo systemctl status polymarket-settler polymarket-web --no-pager`

**Prerequisite:** SSH key auth from local machine to droplet (setup documented below).

### `/status`
**File:** `.claude/commands/status.md`

**Steps:**
1. SSH to droplet
2. Show status of all 3 services: `sudo systemctl status polymarket-bot polymarket-settler polymarket-web --no-pager`
3. Show last 15 lines of each service's journal: `journalctl -u <service> -n 15 --no-pager`
4. Show disk usage: `df -h /`
5. Show memory: `free -h`

### SSH Key Setup (one-time)
1. Generate key if needed: `ssh-keygen -t ed25519 -C "polymarket-bot-deploy"`
2. Copy public key to droplet via DigitalOcean web console: add to `~/.ssh/authorized_keys`
3. Test: `ssh root@<droplet-ip> echo "connected"`
4. Save droplet IP/user to `.env` or memory for future reference

## 4. Memory Additions

### Update existing:
- **`project_cost_and_intervals.md`** — Update to: pipeline runs once daily, settler every 15 minutes. Pipeline currently stopped (as of 2026-03-19) to observe settler performance on 154 pending trades.
- **`project_deployment.md`** — Add SSH connection details (IP, user) once set up.

### New files:
- **`user_profile.md`** — Harry, comfortable with broad autonomy, experienced developer, building a trading bot as a project.
- **`feedback_communication_style.md`** — Prefers terse responses, no trailing summaries, comfortable with broad permissions, doesn't need hand-holding.

## Implementation Order

1. Add `ruff` to dev dependencies + minimal config
2. Replace permissions in `.claude/settings.local.json`
3. Add hooks to `.claude/settings.local.json`
4. Create `/deploy` and `/status` slash command files
5. Set up SSH key auth to droplet (interactive — needs user)
6. Update/create memory files
