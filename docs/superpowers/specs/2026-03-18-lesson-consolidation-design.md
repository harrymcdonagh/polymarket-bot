# Lesson Consolidation & Lesson-Enhanced Training

## Summary

Daily LLM-powered consolidation of raw lessons into a compact ruleset for prompts, plus feature suggestions for XGBoost training. Replaces raw lesson feeds in both calibrator and postmortem prompts with the consolidated ruleset.

## Problem

- Raw lessons grow unboundedly, inflating prompt token costs
- Only last 10-20 lessons are used, losing older important insights
- XGBoost training doesn't benefit from lesson knowledge
- Postmortem generates duplicate insights without full lesson context

## Architecture

### New DB Table: `consolidated_rules`

```sql
CREATE TABLE IF NOT EXISTS consolidated_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ruleset TEXT NOT NULL,           -- compact rules for prompts
    feature_suggestions TEXT,        -- JSON list of proposed XGBoost features
    lesson_count INTEGER,            -- how many raw lessons were consolidated
    consolidated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

History is retained (INSERT, not replace). Consumers always `SELECT ... ORDER BY consolidated_at DESC LIMIT 1`. This provides an audit trail and rollback capability if a consolidation produces bad rules.

### Consolidation Flow (settler, once daily)

```
1. Check if new lessons exist since last consolidation
2. If yes: fetch all raw lessons from DB (capped at 500 most recent)
3. Single LLM call → produces { rules: [...], feature_suggestions: [...] }
4. On success: INSERT new row into consolidated_rules
5. On LLM failure: log error, retain previous rules — never delete existing rules
6. Log rule count and feature suggestion count
```

**Trigger:** Runs at end of settler cycle, AFTER all postmortem analyses complete. Compares latest `consolidated_rules.consolidated_at` against max `lessons.created_at` — only consolidates if new lessons exist since last consolidation.

**Input cap:** If lessons exceed 500, use the most recent 500 and log a warning.

**LLM prompt outputs:**
- `rules`: 15-20 concise, actionable rules grouped by category (risk_management, model_error, data_quality, etc.)
- `feature_suggestions`: structured list of `{ name, description, rationale, priority }` for potential XGBoost features

### Prompt Integration

**Calibrator** (`src/predictor/calibrator.py`):
- Replace raw lessons feed with consolidated ruleset text
- Falls back to raw lessons (last 10) if no consolidated rules exist yet

**Postmortem** (`src/postmortem/postmortem.py`):
- Replace raw 20-lesson feed with consolidated ruleset text
- Same fallback behavior

### XGBoost Training (future spec)

**Feature suggestions** are stored in the `consolidated_rules` table and accessible via `/api/feature-suggestions` (API-only, for manual `curl` inspection). They accumulate as recommendations for review when retraining:
- Some are auto-applicable (confidence thresholds, category flags)
- Some require new data sources (sharp bookmaker lines, rest days)

**Sample weighting** based on lesson categories is deferred to a separate spec once we have enough settled trades to make weighting meaningful and can properly define the mapping between lesson categories and training samples.

## Components Modified

| File | Change |
|------|--------|
| `src/db.py` | Add `consolidated_rules` table, `save_consolidated_rules()`, `get_latest_rules()`, `has_new_lessons_since()` |
| `src/settler/settler.py` | Add `_maybe_consolidate_lessons()` called at end of `run()`, after postmortems and Brier scoring |
| `src/predictor/calibrator.py` | Read consolidated rules instead of raw lessons |
| `src/postmortem/postmortem.py` | Read consolidated rules instead of raw lessons in `analyze_loss()` |
| `src/dashboard/web.py` | Add `/api/feature-suggestions` endpoint |
| `src/pipeline.py` | Pass consolidated rules to calibrator instead of raw lessons |

## Consolidation Prompt Design

The LLM receives all raw lessons grouped by category and produces:

```json
{
  "rules": [
    "RISK: Never deploy full stake on predictions with confidence below 0.70",
    "RISK: Edge calculations for sports must be cross-validated against sharp bookmaker lines",
    "MODEL: Predictions in the 50-60% band are effectively coin flips — require 2x normal edge threshold"
  ],
  "feature_suggestions": [
    {
      "name": "rest_days_differential",
      "description": "Days since last game for each team",
      "rationale": "Multiple NBA losses attributed to ignoring rest/travel fatigue",
      "priority": "high"
    }
  ]
}
```

Rules are prefixed with their category for easy scanning. Target: 15-20 rules max, each under 150 characters.

## Error Handling

- **LLM call fails:** Log error, retain previous consolidated rules. Never delete or overwrite on failure.
- **Malformed JSON:** Strip markdown fences, attempt regex extraction (same pattern as postmortem). On total parse failure, retain previous rules.
- **No lessons yet:** Skip consolidation, log info message.
- **Token overflow:** Cap input at 500 most recent lessons. Log warning if truncated.

## Cost Analysis

- **Consolidation:** 1 LLM call/day (only when new lessons exist) — ~$0.02-0.05
- **Savings per prediction:** consolidated rules are ~500 tokens vs raw lessons which grow unboundedly
- **Savings per postmortem:** same reduction, and fewer duplicate lessons generated
- **Net:** cost-neutral within first week, then saves money as lessons accumulate
