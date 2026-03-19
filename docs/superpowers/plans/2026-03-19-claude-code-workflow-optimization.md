# Claude Code Workflow Optimization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Claude Code friction in this repo — fewer permission prompts, auto-test/lint hooks, remote slash commands, and better memory.

**Architecture:** All config lives in `.claude/settings.local.json` (project-scoped). Slash commands go in `.claude/commands/`. Memory files in the user's project memory directory. Ruff added as a dev dependency with minimal config in `pyproject.toml`.

**Tech Stack:** Claude Code hooks, Claude Code slash commands, ruff, SSH, pyproject.toml

---

### Task 1: Add ruff to dev dependencies and configure

**Files:**
- Modify: `pyproject.toml:31-36` (dev deps) and append ruff config

- [ ] **Step 1: Add ruff to dev dependencies**

In `pyproject.toml`, add `"ruff>=0.4.0"` to the `[project.optional-dependencies] dev` list:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-mock>=3.14.0",
    "ruff>=0.4.0",
]
```

- [ ] **Step 2: Add ruff config to pyproject.toml**

Append to end of `pyproject.toml`:

```toml
[tool.ruff]
line-length = 120
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W"]
ignore = ["E501"]
```

Minimal ruleset: pyflakes (F) for real bugs, pycodestyle errors (E) and warnings (W), but ignore line length (E501) since the codebase has long lines.

- [ ] **Step 3: Install ruff**

Run: `pip install -e ".[dev]"`

- [ ] **Step 4: Verify ruff runs**

Run: `ruff check . 2>&1 | tail -10`
Expected: either "All checks passed" or a list of warnings (not an error about ruff not found)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add ruff linter to dev dependencies"
```

---

### Task 2: Replace permissions in settings.local.json

**Files:**
- Modify: `.claude/settings.local.json`

- [ ] **Step 1: Replace the entire file with clean permissions**

Write `.claude/settings.local.json` with:

```json
{
  "permissions": {
    "allow": [
      "Bash(python:*)",
      "Bash(pip:*)",
      "Bash(git add:*)",
      "Bash(git commit:*)",
      "Bash(git push:*)",
      "Bash(git checkout:*)",
      "Bash(git merge:*)",
      "Bash(git diff:*)",
      "Bash(git log:*)",
      "Bash(git status:*)",
      "Bash(git branch:*)",
      "Bash(git stash:*)",
      "Bash(curl:*)",
      "Bash(ls:*)",
      "Bash(wc:*)",
      "Bash(cat:*)",
      "Bash(find:*)",
      "Bash(grep:*)",
      "Bash(which:*)",
      "Bash(chmod:*)",
      "Bash(ssh:*)",
      "Bash(scp:*)",
      "Bash(ruff:*)",
      "Bash(bash:*)",
      "WebSearch",
      "WebFetch"
    ],
    "deny": [
      "Bash(rm -rf:*)",
      "Bash(git push --force:*)",
      "Bash(git reset --hard:*)"
    ]
  }
}
```

- [ ] **Step 2: Verify the file is valid JSON**

Run: `python -c "import json; json.load(open('.claude/settings.local.json')); print('valid')"`
Expected: `valid`

- [ ] **Step 3: Commit**

```bash
git add .claude/settings.local.json
git commit -m "chore: replace 89 one-off permissions with broad patterns"
```

---

### Task 3: Add auto-test and auto-lint hooks

**Files:**
- Modify: `.claude/settings.local.json` (add `hooks` key)

- [ ] **Step 1: Add hooks to settings.local.json**

Add a `"hooks"` key alongside `"permissions"` in `.claude/settings.local.json`:

```json
{
  "permissions": {
    ...existing...
  },
  "hooks": {
    "PostToolUse": [
      {
        "tools": ["Edit", "Write"],
        "match_files": ["**/*.py"],
        "command": "ruff check --fix . 2>&1 | tail -5"
      },
      {
        "tools": ["Edit", "Write"],
        "match_files": ["**/*.py"],
        "command": "python -m pytest tests/ -x -q 2>&1 | tail -5"
      }
    ]
  }
}
```

Lint runs first (fast, fixes issues), then tests run (slower, catches regressions).

- [ ] **Step 2: Verify JSON is still valid**

Run: `python -c "import json; json.load(open('.claude/settings.local.json')); print('valid')"`
Expected: `valid`

- [ ] **Step 3: Commit**

```bash
git add .claude/settings.local.json
git commit -m "chore: add auto-lint and auto-test hooks for .py files"
```

---

### Task 4: Create /deploy slash command

**Files:**
- Create: `.claude/commands/deploy.md`

- [ ] **Step 1: Create the commands directory and deploy.md**

```markdown
# Deploy to Production

Push latest code to the DigitalOcean droplet and restart services.

## Steps

1. Push to remote:
   ```bash
   git push origin master
   ```

2. SSH to droplet and deploy:
   ```bash
   ssh root@$DROPLET_IP "cd /opt/polymarket-bot && git pull origin master && pip install -e '.[dev]' && sudo systemctl restart polymarket-settler polymarket-web && echo '--- Service Status ---' && sudo systemctl status polymarket-settler polymarket-web --no-pager -l"
   ```

3. Report the service status output to the user.

## Notes
- The pipeline service (polymarket-bot) is currently stopped intentionally — do NOT restart it unless the user asks.
- DROPLET_IP should be read from the .env file or environment variable.
- If SSH fails, suggest the user check their SSH key setup.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/commands/deploy.md
git commit -m "feat: add /deploy slash command for production deployment"
```

---

### Task 5: Create /status slash command

**Files:**
- Create: `.claude/commands/status.md`

- [ ] **Step 1: Create status.md**

```markdown
# Server Status Check

Check the health of all services on the DigitalOcean droplet.

## Steps

1. SSH to droplet and gather status:
   ```bash
   ssh root@$DROPLET_IP "echo '=== SERVICE STATUS ===' && sudo systemctl status polymarket-bot polymarket-settler polymarket-web --no-pager -l && echo '=== RECENT LOGS (settler) ===' && journalctl -u polymarket-settler -n 15 --no-pager && echo '=== RECENT LOGS (web) ===' && journalctl -u polymarket-web -n 15 --no-pager && echo '=== RECENT LOGS (bot) ===' && journalctl -u polymarket-bot -n 15 --no-pager && echo '=== DISK ===' && df -h / && echo '=== MEMORY ===' && free -h"
   ```

2. Summarize the output to the user:
   - Which services are running/stopped
   - Any errors in recent logs
   - Disk/memory usage if concerning

## Notes
- DROPLET_IP should be read from the .env file or environment variable.
- All 3 services: polymarket-bot (pipeline), polymarket-settler, polymarket-web
```

- [ ] **Step 2: Commit**

```bash
git add .claude/commands/status.md
git commit -m "feat: add /status slash command for server health checks"
```

---

### Task 6: Set up SSH key auth to droplet

**Files:**
- None (interactive setup with user)

This task requires the user's involvement — it cannot be fully automated.

- [ ] **Step 1: Check if SSH key already exists**

Run: `ls ~/.ssh/id_ed25519.pub 2>/dev/null || ls ~/.ssh/id_rsa.pub 2>/dev/null || echo "no key found"`

- [ ] **Step 2: Generate key if needed**

If no key found:
Run: `ssh-keygen -t ed25519 -C "polymarket-bot-deploy" -f ~/.ssh/id_ed25519 -N ""`

- [ ] **Step 3: Display public key for user**

Run: `cat ~/.ssh/id_ed25519.pub`

Tell user: "Copy this public key. Go to your DigitalOcean droplet web console and run:
```bash
echo '<public-key>' >> ~/.ssh/authorized_keys
```"

- [ ] **Step 4: Get droplet IP from user**

Ask the user for their droplet IP address.

- [ ] **Step 5: Test SSH connection**

Run: `ssh -o StrictHostKeyChecking=accept-new root@<DROPLET_IP> echo "connected"`
Expected: `connected`

- [ ] **Step 6: Add DROPLET_IP to .env**

Add `DROPLET_IP=<ip>` to `.env` and `.env.example`.

- [ ] **Step 7: Commit .env.example update**

```bash
git add .env.example
git commit -m "chore: add DROPLET_IP to env example"
```

---

### Task 7: Update memory files

**Files:**
- Modify: `C:\Users\harry\.claude\projects\D--polymarket-bot\memory\project_cost_and_intervals.md`
- Modify: `C:\Users\harry\.claude\projects\D--polymarket-bot\memory\project_deployment.md`
- Create: `C:\Users\harry\.claude\projects\D--polymarket-bot\memory\user_profile.md`
- Create: `C:\Users\harry\.claude\projects\D--polymarket-bot\memory\feedback_communication_style.md`
- Modify: `C:\Users\harry\.claude\projects\D--polymarket-bot\memory\MEMORY.md`

- [ ] **Step 1: Update project_cost_and_intervals.md**

Replace contents with:

```markdown
---
name: Pipeline cost and interval strategy
description: Pipeline runs once daily, settler every 15 min; pipeline currently stopped as of 2026-03-19
type: project
---

Each full pipeline+settlement cycle costs ~$0.50 (Anthropic API usage).

**Current config (2026-03-19):** Pipeline once daily, settler every 15 minutes. Pipeline currently stopped to observe settler performance on 154 pending trades.

**Why:** User wants to see how existing trades resolve before committing to more. Cost-conscious about API spend (~$0.50/cycle).

**How to apply:** When suggesting interval changes or new features that increase API calls, factor in the ~$0.50/cycle cost. Don't assume pipeline is running — check first.
```

- [ ] **Step 2: Create user_profile.md**

```markdown
---
name: User profile
description: Harry — experienced developer, comfortable with autonomy, building a trading bot project
type: user
---

Harry is an experienced developer building an autonomous Polymarket trading bot. Comfortable with:
- Broad autonomy — doesn't need hand-holding
- Direct, terse communication
- Giving Claude Code wide permissions
- Making quick decisions (prefers multiple choice over open-ended)

Prefers to observe and iterate rather than over-engineer upfront.
```

- [ ] **Step 3: Update project_deployment.md with SSH details**

After Task 6 completes, add the SSH connection details to the existing deployment memory file. Update the file to include:

```markdown
**SSH access (added 2026-03-19):**
- User: `root`
- IP: `<DROPLET_IP from Task 6>`
- Command: `ssh root@<DROPLET_IP>`
```

- [ ] **Step 4: Create feedback_communication_style.md**

```markdown
---
name: Communication style preferences
description: Harry prefers terse responses, no summaries, no over-explaining
type: feedback
---

Keep responses short and direct. No trailing summaries of what was just done.

**Why:** Harry can read diffs and output himself. Restating work wastes time.

**How to apply:** Lead with the answer or action. Skip preamble. Don't recap what was changed unless asked. When presenting options, use multiple choice format — it's faster.
```

- [ ] **Step 5: Update MEMORY.md index**

Update the existing `project_cost_and_intervals.md` description and add entries for the two new files:

```markdown
- [project_cost_and_intervals.md](project_cost_and_intervals.md) - Pipeline once daily, settler every 15 min; pipeline currently stopped
- [user_profile.md](user_profile.md) - Harry: experienced dev, prefers autonomy and terse communication
- [feedback_communication_style.md](feedback_communication_style.md) - Keep responses short, no summaries, use multiple choice
```

- [ ] **Step 6: No commit needed** (memory files are outside the repo)
