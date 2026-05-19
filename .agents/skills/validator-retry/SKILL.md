---
name: validator-retry
description: Static type/lint validator with compile-error-feedback retry loop. Eliminates hallucinated APIs and broken codegen without per-framework knowledge. Covers TypeScript (tsc), Python (pyright/mypy), Rust (cargo check), Go (go vet), and JavaScript (eslint). Use AFTER each code generation slice and AFTER the build step in build-test-agent.
---

# Validator-Retry

## Why this skill exists

Code generation models hallucinate APIs that don't exist in the pinned version.
Static validators know the *exact* API surface of the installed library. Feeding
validator stderr back as context is the cheapest correction loop available — no
per-framework knowledge needed from the agent.

Real failure mode: model generates `useFormStatus()` (React 19 hook). Project
pins React 18. `tsc --noEmit` catches it in < 2s. Without this loop the bug
reaches the test runner or production.

## Process (mandatory order)

### Step 1 — Detect applicable validators (DO NOT install)

Only use validators that are already present in the project. Check in this order:

| Ecosystem | Validator | Detection condition | Run command |
|---|---|---|---|
| TypeScript | `tsc` | `tsconfig.json` exists | `npx tsc --noEmit 2>&1` |
| JavaScript/TS | `eslint` | `.eslintrc*` OR `eslint` in `devDependencies` | `npx eslint . --max-warnings 0 2>&1` |
| Python | `pyright` | `pyrightconfig.json` OR `pyright` in dev deps | `pyright 2>&1` |
| Python | `mypy` | `mypy.ini` OR `mypy` in dev deps | `mypy . 2>&1` |
| Rust | `cargo check` | `Cargo.toml` exists | `cargo check 2>&1` |
| Go | `go vet` | `go.mod` exists | `go vet ./... 2>&1` |

Run ALL applicable validators for the detected ecosystem. Combine stderr output.

Emit one audit entry:
```
[Validator] detected: <tool1>, <tool2>   (or: none — skipping validation)
```

If no validators detected: log `[Validator] none detected — skipping` and STOP.
This is acceptable; the skill degrades gracefully.

### Step 2 — Run validators, capture output

```bash
# example — TypeScript
npx tsc --noEmit 2>&1; echo "tsc_exit:$?"
```

Capture:
- `exit_code` — 0 = clean, non-zero = errors present
- `errors_text` — full combined stderr/stdout
- `error_count` — number of lines containing "error" or "Error:"

If `exit_code == 0`: emit `[Validator] <tool> clean — 0 errors` and STOP.
No retry needed.

### Step 3 — Retry loop on errors (max 3 iterations)

On `exit_code != 0`:

**Per iteration:**

1. Emit `[Validator] <tool> attempt <N>/3 — <error_count> errors`
2. Re-enter the code generation step with this injected prefix:

   ```
   VALIDATOR ERRORS (attempt <N>/3 — fix these before continuing):
   <errors_text>

   Instructions:
   - Fix ONLY the errors listed above.
   - Do NOT change any other logic or add new features.
   - After fixing, the validator will re-run automatically.
   ```

3. Re-run validators after fix.
4. If `exit_code == 0`: emit `[Validator] clean after <N> retr(y|ies)` → continue normal flow.
5. If still failing after attempt 3:
   - Emit `[Validator] PERSISTENT FAILURE — <error_count> errors after 3 retries`
   - Include `errors_text` in `audit_entries[]` (truncated to 2 KB if needed)
   - Set `status: blocked`
   - HALT

### Step 4 — Audit entries

Emit per validation round:
```
[Validator] detected: tsc, eslint
[Validator] tsc attempt 1/3 — 4 errors
[Validator] eslint attempt 1/3 — 2 errors
[Validator] tsc clean after 1 retry
[Validator] eslint clean after 1 retry
```

Or on persistent failure:
```
[Validator] tsc attempt 3/3 — 2 errors (PERSISTENT)
[Validator] PERSISTENT FAILURE — blocked after 3 retries
[Validator] errors_text (truncated): <stderr snippet>
```

## Verification (objective gates)

| Check | How |
|---|---|
| Validator detected | `[Validator] detected:` entry in `audit_entries[]` before any code fix |
| Retry bounded | At most 3 `[Validator] * attempt` entries per validation round |
| Clean declared | `[Validator] clean` entry when exit_code == 0 |
| Persistent failure escalated | `status: blocked` set when exit_code != 0 after attempt 3 |

## Anti-patterns to REJECT

| Rationalization | Reality |
|---|---|
| "Type error is minor, I'll fix it later" | Fix now — it may be a hallucinated API. |
| "tsc errors are just warnings" | If exit_code != 0, they are errors. |
| "I need to install pyright first" | Only run what's already in the project's dev deps. |
| "The model knows the API, validation is redundant" | Models hallucinate. Validators are deterministic. |
| "eslint errors are style issues, not bugs" | `--max-warnings 0` treats all warnings as errors. Respect the project's rules. |

## Red flags (escalate)

- Validator produces **different** errors on consecutive attempts without code changes →
  non-deterministic validator config → `status: needs_human`
- `error_count` increases after a fix attempt → fix introduced new errors →
  emit `[RedFlag] validator-retry: error count increased on attempt <N>` → `status: needs_human`
- Validator takes > 30s → log `[Validator] slow: <tool> took > 30s` and continue (do NOT kill)
