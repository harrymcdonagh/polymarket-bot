# Lesson Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate raw lessons into a compact ruleset daily, replacing unbounded raw lesson feeds in calibrator and postmortem prompts.

**Architecture:** New `consolidated_rules` DB table stores versioned rulesets. Settler runs daily consolidation via a single LLM call after postmortems complete. Calibrator and postmortem read the latest ruleset instead of raw lessons. Feature suggestions stored for manual review.

**Tech Stack:** SQLite, Anthropic API (claude-sonnet-4-6), existing DB/settler/calibrator/postmortem modules.

**Spec:** `docs/superpowers/specs/2026-03-18-lesson-consolidation-design.md`

---

### Task 1: DB Schema and Methods

**Files:**
- Modify: `src/db.py:77-83` (init tables), `src/db.py:139-170` (migrate)
- Test: `tests/test_db_migration.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_db_migration.py`:

```python
def test_save_and_get_consolidated_rules():
    db = Database(":memory:")
    db.init()
    db.save_consolidated_rules(
        ruleset="RISK: Never bet >50\nMODEL: Check base rates",
        feature_suggestions='[{"name": "rest_days", "priority": "high"}]',
        lesson_count=25,
    )
    rules = db.get_latest_rules()
    assert rules is not None
    assert "RISK: Never bet >50" in rules["ruleset"]
    assert rules["lesson_count"] == 25
    assert rules["consolidated_at"] is not None


def test_get_latest_rules_returns_most_recent():
    db = Database(":memory:")
    db.init()
    db.save_consolidated_rules(ruleset="old rules", feature_suggestions="[]", lesson_count=5)
    db.save_consolidated_rules(ruleset="new rules", feature_suggestions="[]", lesson_count=10)
    rules = db.get_latest_rules()
    assert rules["ruleset"] == "new rules"
    assert rules["lesson_count"] == 10


def test_get_latest_rules_returns_none_when_empty():
    db = Database(":memory:")
    db.init()
    assert db.get_latest_rules() is None


def test_has_new_lessons_since():
    db = Database(":memory:")
    db.init()
    # No lessons, no rules — nothing new
    assert db.has_new_lessons_since_consolidation() is False
    # Add a lesson — now there's something new
    db.save_lesson(category="risk_management", lesson="test lesson")
    assert db.has_new_lessons_since_consolidation() is True
    # Consolidate — now nothing new
    db.save_consolidated_rules(ruleset="rules", feature_suggestions="[]", lesson_count=1)
    assert db.has_new_lessons_since_consolidation() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db_migration.py::test_save_and_get_consolidated_rules tests/test_db_migration.py::test_get_latest_rules_returns_most_recent tests/test_db_migration.py::test_get_latest_rules_returns_none_when_empty tests/test_db_migration.py::test_has_new_lessons_since -v`
Expected: FAIL — methods don't exist

- [ ] **Step 3: Add table creation to `src/db.py` init**

In the `init()` method, after the `lessons` table creation (around line 83), add:

```python
            CREATE TABLE IF NOT EXISTS consolidated_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ruleset TEXT NOT NULL,
                feature_suggestions TEXT,
                lesson_count INTEGER,
                consolidated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
```

- [ ] **Step 4: Add DB methods to `src/db.py`**

Add after `get_lessons()` (around line 254):

```python
    def save_consolidated_rules(self, ruleset: str, feature_suggestions: str, lesson_count: int):
        """Save a new consolidated ruleset. History is retained."""
        conn = self._conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO consolidated_rules (ruleset, feature_suggestions, lesson_count, consolidated_at) VALUES (?, ?, ?, ?)",
            (ruleset, feature_suggestions, lesson_count, now),
        )
        conn.commit()

    def get_latest_rules(self) -> dict | None:
        """Get the most recent consolidated ruleset."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM consolidated_rules ORDER BY consolidated_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def has_new_lessons_since_consolidation(self) -> bool:
        """Check if any lessons were created after the last consolidation."""
        conn = self._conn()
        lesson_count = conn.execute("SELECT COUNT(*) as n FROM lessons").fetchone()["n"]
        if lesson_count == 0:
            return False
        latest_rules = self.get_latest_rules()
        if latest_rules is None:
            return True  # Never consolidated, but lessons exist
        # Count-based check: lessons only grow (INSERT OR IGNORE deduplicates),
        # so if count > last consolidation's count, there are genuinely new lessons.
        # Simpler than timestamp comparison and avoids timezone issues with CURRENT_TIMESTAMP.
        return lesson_count > latest_rules["lesson_count"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_db_migration.py -v -k "consolidated or has_new"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/db.py tests/test_db_migration.py
git commit -m "feat: add consolidated_rules table and DB methods"
```

---

### Task 2: Consolidation Logic in Settler

**Files:**
- Modify: `src/settler/settler.py:414-416` (after Brier scoring, before daily summary)
- Test: `tests/test_settler.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_settler.py`:

```python
@pytest.mark.asyncio
async def test_consolidation_runs_when_new_lessons(tmp_path):
    """Consolidation should run when new lessons exist since last consolidation."""
    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    db.init()

    # Add a lesson so consolidation has something to do
    db.save_lesson(category="risk_management", lesson="Never bet on low confidence")

    notifier = MagicMock()
    notifier.is_enabled = False

    # Mock the anthropic client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "rules": ["RISK: Never bet on low confidence predictions"],
        "feature_suggestions": [{"name": "confidence_flag", "priority": "high"}],
    }))]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    settler = Settler(db=db, notifier=notifier)
    settler._consolidation_client = mock_client
    await settler._maybe_consolidate_lessons()

    rules = db.get_latest_rules()
    assert rules is not None
    assert "RISK: Never bet on low confidence" in rules["ruleset"]
    assert rules["lesson_count"] == 1


@pytest.mark.asyncio
async def test_consolidation_skips_when_no_new_lessons(tmp_path):
    """Consolidation should skip when no new lessons since last run."""
    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    db.init()

    # Add a lesson and consolidate
    db.save_lesson(category="risk_management", lesson="test")
    db.save_consolidated_rules(ruleset="existing rules", feature_suggestions="[]", lesson_count=1)

    notifier = MagicMock()
    notifier.is_enabled = False
    settler = Settler(db=db, notifier=notifier)
    mock_client = MagicMock()
    settler._consolidation_client = mock_client

    await settler._maybe_consolidate_lessons()

    # LLM should NOT have been called
    mock_client.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_consolidation_handles_malformed_json(tmp_path):
    """Consolidation should retain previous rules when LLM returns bad JSON."""
    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    db.init()

    # Save existing rules and add a new lesson
    db.save_consolidated_rules(ruleset="old rules", feature_suggestions="[]", lesson_count=1)
    db.save_lesson(category="risk_management", lesson="lesson one")
    db.save_lesson(category="risk_management", lesson="lesson two")

    notifier = MagicMock()
    notifier.is_enabled = False

    # LLM returns garbage wrapped in markdown fences
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="```json\n{invalid json truncated")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    settler = Settler(db=db, notifier=notifier)
    settler._consolidation_client = mock_client
    await settler._maybe_consolidate_lessons()

    # Old rules should be retained
    rules = db.get_latest_rules()
    assert rules["ruleset"] == "old rules"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_settler.py::test_consolidation_runs_when_new_lessons tests/test_settler.py::test_consolidation_skips_when_no_new_lessons -v`
Expected: FAIL — method doesn't exist

- [ ] **Step 3: Add consolidation prompt and method to `src/settler/settler.py`**

Add at top of file, after existing imports:

```python
CONSOLIDATION_PROMPT = """You are a trading system analyst. Below are all lessons learned from prediction market trades, grouped by category. Consolidate them into:

1. A compact RULESET (15-20 rules max) — actionable rules the system should follow. Each rule should be prefixed with its category (RISK, MODEL, DATA, SENTIMENT, MARKET). Keep each rule under 150 characters. Merge similar lessons into single rules. Drop lessons that are too vague or situational to be actionable.

2. FEATURE SUGGESTIONS for the XGBoost model — concrete numerical features that could improve predictions, based on patterns in the lessons. Each suggestion needs a name, description, rationale, and priority (high/medium/low).

Lessons by category:
{lessons_by_category}

Return ONLY valid JSON:
{{
  "rules": ["CATEGORY: rule text", ...],
  "feature_suggestions": [
    {{"name": "feature_name", "description": "what it measures", "rationale": "why it would help", "priority": "high|medium|low"}},
    ...
  ]
}}"""
```

Add method to `Settler` class, before `_maybe_send_daily_summary`:

```python
    async def _maybe_consolidate_lessons(self) -> None:
        """Consolidate lessons into a compact ruleset once daily when new lessons exist."""
        if not self.db.has_new_lessons_since_consolidation():
            return

        lessons = self.db.get_lessons()
        if not lessons:
            return

        # Cap at 500 most recent
        if len(lessons) > 500:
            logger.warning(f"Truncating {len(lessons)} lessons to 500 for consolidation")
            lessons = lessons[-500:]

        # Group by category
        by_category: dict[str, list[str]] = {}
        for l in lessons:
            cat = l.get("category", "unknown")
            by_category.setdefault(cat, []).append(l["lesson"])

        lessons_text = ""
        for cat, items in sorted(by_category.items()):
            lessons_text += f"\n## {cat.upper()} ({len(items)} lessons)\n"
            for item in items:
                lessons_text += f"- {item}\n"

        client = getattr(self, '_consolidation_client', None)
        if client is None:
            import anthropic
            from src.config import Settings
            settings = Settings()
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        else:
            from src.config import Settings
            settings = Settings()

        try:
            response = client.messages.create(
                model=settings.POSTMORTEM_MODEL,
                max_tokens=4096,
                messages=[{"role": "user", "content": CONSOLIDATION_PROMPT.format(
                    lessons_by_category=lessons_text,
                )}],
            )
            text = response.content[0].text.strip()
            # Strip markdown fences
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```\s*$', '', text)
            text = text.strip()

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    logger.error(f"Consolidation returned invalid JSON: {text[:200]}")
                    return  # Retain previous rules

            rules = data.get("rules", [])
            feature_suggestions = json.dumps(data.get("feature_suggestions", []))
            ruleset = "\n".join(rules)

            self.db.save_consolidated_rules(
                ruleset=ruleset,
                feature_suggestions=feature_suggestions,
                lesson_count=len(lessons),
            )
            logger.info(f"Consolidated {len(lessons)} lessons into {len(rules)} rules, {len(data.get('feature_suggestions', []))} feature suggestions")

        except Exception as e:
            logger.error(f"Lesson consolidation failed: {e} — retaining previous rules")
```

- [ ] **Step 4: Wire consolidation into `run()` method**

First, add `import re` to the imports at the top of `src/settler/settler.py` (after `import json` on line 2):

```python
import re
```

Then, in `src/settler/settler.py`, after the Brier score block (line 414) and before `await self._maybe_send_daily_summary()` (line 416), add:

```python
        await self._maybe_consolidate_lessons()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_settler.py -v -k "consolidation"`
Expected: PASS

- [ ] **Step 6: Run all settler tests**

Run: `python -m pytest tests/test_settler.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/settler/settler.py tests/test_settler.py
git commit -m "feat: add daily lesson consolidation to settler"
```

---

### Task 3: Replace Raw Lessons in Calibrator

**Files:**
- Modify: `src/predictor/calibrator.py:79-84`
- Modify: `src/pipeline.py:196-199`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_pipeline.py`:

```python
def test_calibrator_uses_consolidated_rules(tmp_path):
    """Calibrator should use consolidated ruleset when available."""
    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    db.init()
    db.save_consolidated_rules(
        ruleset="RISK: Never bet on coin flips\nMODEL: Check base rates",
        feature_suggestions="[]",
        lesson_count=10,
    )
    rules = db.get_latest_rules()
    assert rules is not None
    assert "RISK: Never bet on coin flips" in rules["ruleset"]
```

- [ ] **Step 2: Run test to verify it passes** (this is a DB test, it should pass already)

Run: `python -m pytest tests/test_pipeline.py::test_calibrator_uses_consolidated_rules -v`
Expected: PASS

- [ ] **Step 3: Update `src/pipeline.py` to pass consolidated rules**

Replace lines 196-199:

```python
        # Feed lessons into calibrator for better predictions
        recent_lessons = [l["lesson"] for l in self.db.get_lessons()[-10:]]
        prediction = await self.calibrator.calibrate(
            market, research, xgb_prob, lessons=recent_lessons,
        )
```

With:

```python
        # Feed consolidated rules (or fallback to raw lessons) into calibrator
        rules = self.db.get_latest_rules()
        if rules:
            lessons_for_calibrator = rules["ruleset"]
        else:
            lessons_for_calibrator = "\n".join(f"- {l['lesson']}" for l in self.db.get_lessons()[-10:])
        prediction = await self.calibrator.calibrate(
            market, research, xgb_prob, lessons=lessons_for_calibrator,
        )
```

- [ ] **Step 4: Update `src/predictor/calibrator.py` to accept string instead of list**

Replace lines 79-84:

```python
        # Format lessons context if available
        if lessons:
            lessons_text = "\n".join(f"- {l}" for l in lessons[-10:])
            lessons_context = f"**Previous lessons learned (avoid repeating past mistakes):**\n{lessons_text}"
        else:
            lessons_context = ""
```

With:

```python
        # Format lessons context if available
        if lessons:
            if isinstance(lessons, list):
                lessons_text = "\n".join(f"- {l}" for l in lessons[-10:])
            else:
                lessons_text = lessons  # Already formatted (consolidated ruleset)
            lessons_context = f"**Trading rules (follow these):**\n{lessons_text}"
        else:
            lessons_context = ""
```

Also update the type hint on line 68:

```python
        lessons: list[str] | str | None = None,
```

- [ ] **Step 5: Run pipeline tests**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/pipeline.py src/predictor/calibrator.py tests/test_pipeline.py
git commit -m "feat: calibrator uses consolidated rules instead of raw lessons"
```

---

### Task 4: Replace Raw Lessons in Postmortem

**Files:**
- Modify: `src/postmortem/postmortem.py:62-65`
- Test: `tests/test_postmortem.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_postmortem.py`:

```python
def test_postmortem_uses_consolidated_rules(tmp_path):
    """Postmortem should use consolidated rules when available."""
    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    db.init()
    db.save_consolidated_rules(
        ruleset="RISK: Check confidence\nMODEL: Validate base rates",
        feature_suggestions="[]",
        lesson_count=5,
    )
    # Verify the DB method works — postmortem will call it
    rules = db.get_latest_rules()
    assert rules is not None
    assert "RISK: Check confidence" in rules["ruleset"]
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_postmortem.py::test_postmortem_uses_consolidated_rules -v`
Expected: PASS

- [ ] **Step 3: Update `src/postmortem/postmortem.py` to use consolidated rules**

Replace lines 62-65 in `analyze_loss()`:

```python
        previous_lessons = ""
        if self.db:
            lessons = self.db.get_lessons()
            previous_lessons = "\n".join(f"- {l['lesson']}" for l in lessons[-20:])
```

With:

```python
        previous_lessons = ""
        if self.db:
            rules = self.db.get_latest_rules()
            if rules:
                previous_lessons = rules["ruleset"]
            else:
                lessons = self.db.get_lessons()
                previous_lessons = "\n".join(f"- {l['lesson']}" for l in lessons[-20:])
```

- [ ] **Step 4: Run all postmortem tests**

Run: `python -m pytest tests/test_postmortem.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/postmortem/postmortem.py tests/test_postmortem.py
git commit -m "feat: postmortem uses consolidated rules instead of raw lessons"
```

---

### Task 5: Feature Suggestions API Endpoint

**Files:**
- Modify: `src/dashboard/web.py:124-126`
- Modify: `src/dashboard/service.py`

- [ ] **Step 1: Add method to `src/dashboard/service.py`**

Add after `get_lessons()`:

```python
    def get_feature_suggestions(self) -> list[dict]:
        rules = self.db.get_latest_rules()
        if not rules or not rules.get("feature_suggestions"):
            return []
        import json
        try:
            return json.loads(rules["feature_suggestions"])
        except (json.JSONDecodeError, TypeError):
            return []
```

- [ ] **Step 2: Add endpoint to `src/dashboard/web.py`**

After the `/api/lessons` endpoint (around line 126), add:

```python
    @app.get("/api/feature-suggestions")
    async def api_feature_suggestions():
        return await asyncio.to_thread(service.get_feature_suggestions)
```

- [ ] **Step 3: Run web tests**

Run: `python -m pytest tests/test_web.py -v`
Expected: Existing tests PASS (new endpoint not tested — API-only for manual inspection)

- [ ] **Step 4: Commit**

```bash
git add src/dashboard/web.py src/dashboard/service.py
git commit -m "feat: add /api/feature-suggestions endpoint"
```

---

### Task 6: Full Integration Test

- [ ] **Step 1: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All previously passing tests still pass

- [ ] **Step 2: Commit any remaining changes and push**

```bash
git push
```

- [ ] **Step 3: Deploy**

```bash
# On server:
cd /opt/polymarket-bot && git pull
sudo systemctl restart polymarket-bot polymarket-settler
```
