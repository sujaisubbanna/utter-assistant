# Router / plan-accuracy eval

A small, hermetic evaluation of Utter's **deterministic rule engine**:
`utter.router.rules.plan(utterance, ctx, profiles)`. It scores how often the
rule layer turns a spoken phrase into the Plan the corpus expects.

## What it measures

For each corpus case the harness runs `plan()` with a **fixed in-memory profile
set** and **fixed contexts** (no desktop, no network, no user config) and
compares the result — step for step — against the expected Plan.

```
"open youtube"  ->  key {chord: ctrl+y}   (focused in Firefox)
```

It reports overall accuracy, a per-category table, and exits non-zero when
accuracy is below the threshold.

**Honest scope limit:** this measures *PLAN accuracy*, not real desktop task
success. A green corpus means the rules chose the expected steps; it does not
prove the action executed, the app existed, a window focused, or the user got
what they wanted. Those are covered elsewhere (`tests/executor/`, `tests/m3/`,
manual testing).

## Run it

```bash
.venv-agent/bin/python tests/eval/run_eval.py
.venv-agent/bin/python tests/eval/run_eval.py --verbose    # show expected vs got
.venv-agent/bin/python tests/eval/run_eval.py --json       # machine-readable
.venv-agent/bin/python tests/eval/run_eval.py --threshold 0.98
```

`scripts/verify.sh` runs it with the default threshold, so a non-gap regression
fails verification.

## Threshold

`--threshold` is the minimum overall accuracy required to pass; it defaults to
`1.0` (the corpus must be fully green). Per-category counts are informational
only — the exit code is driven by the overall number alone.

## Files

| File | Role |
| --- | --- |
| `corpus.py` | The case data: fixed `PROFILES`, fixed `CONTEXTS`, `CASES`, `KNOWN_GAPS`. |
| `run_eval.py` | The runner: evaluates, aggregates, prints, exits. |
| `README.md` | This file. |

There is no `__init__.py`: `run_eval.py` adds `tests/eval/` to `sys.path` and
imports `corpus` directly, matching `tests/router/` (which is also run as plain
scripts). Run it as a script, not as a module.

## Adding a case

1. Add a tuple to `CASES` in `corpus.py`:

   ```python
   ("shortcut_new_tab", "shortcuts", "new tab", "browser",
    plan_of(key("ctrl+t", "new_tab in firefox"))),
   ```

   Fields: `(name, category, utterance, context_key, expected_snapshot)`.
   Use the `plan_of` / `step` / `url` / `app` / `niri` / `key` helpers so cases
   stay readable and the comparison stays exact.

2. Use a `context_key` from `CONTEXTS`. Contexts are deliberately few; add one
   only when a matcher genuinely depends on it (e.g. focused browser vs none).

3. **Ground the target:** only ids in `PROFILES` (or the CLI-agent names in
   `utter/data/cli_agents.json`) may appear as `app` targets. Do not invent ids.

4. Run the corpus. If it is green, done. If the expected plan does not match
   real output, decide which is right:

   - The expectation was wrong → fix it to the real output.
   - The expectation is the *intended* behaviour and the router genuinely
     disagrees → record it in `KNOWN_GAPS` and add a `gap_*` case to
     `gap_cases()`, with a one-line reason.

5. Pick an existing category (`custom_commands`, `niri`, `media`, `cli_agents`,
   `terminal`, `open_url_site_app`, `search`, `shortcuts`, `keys_editing`,
   `typing_scroll`, `perception`, `negatives`) so the table stays stable.
   `negatives` cases must return `None` (an utterance that should not route).

## Known gaps

`KNOWN_GAPS` lists cases whose expected value is the **intended** behaviour but
where the router currently disagrees. They are:

- reported separately,
- **excluded** from the accuracy threshold, and
- flagged `STALE (now passes)` when the router starts producing the expected
  plan, so the gap list gets cleaned up rather than rotting.

Never "fix" a failure by loosening the comparison or lowering the threshold for
a non-gap case. If a rule is genuinely wrong, leave it to a human; the harness
records reality, it does not change it.

## Data dependencies

Two shipped data files feed the rules under test and therefore the corpus:
`utter/data/niri_phrases.json` (extends the compositor phrase map at import) and
`utter/data/cli_agents.json` (CLI-agent names and terminal launcher). Keep the
corpus in step with those files; the `comfy` cases also depend on
`scripts/start-comfyui.sh` existing at its usual path.
