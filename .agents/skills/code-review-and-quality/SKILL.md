---
name: code-review-and-quality
description: Multi-axis code review with automated linting, fixing, and building. Runs linter, auto-fixes, builds, tests, then reviews. Use before merging any change.
---

# Code Review and Quality (Custom — with automated gates)

## Overview

Same five-axis review as the standard skill, but with **automated gates first**.
The linter and build MUST pass before the conceptual review begins. This catches
trivial issues (unused imports, formatting, dead code) before a human or model
spends time on them.

**Pipeline:** lint → auto-fix → build → test → review

---

## When called from a reviewer agent

If you are executing as `reviewer-code` (i.e., your role is to emit findings, not to fix),
**skip Steps 1–4 entirely**. `build-test-agent` already ran lint, build, and tests as part
of `/factory-build`. Repeating them wastes time and produces no new signal.

Go directly to **Step 5: Five-axis review**.

---

## Step 1: Detect project type and tools

Read `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, or `CMakeLists.txt`
to determine which tools to use.

| File | Linter | Formatter | Build | Test |
|------|--------|-----------|-------|------|
| `package.json` | `npx eslint .` | `npx prettier --write .` | `npm run build` | `npm test` |
| `pyproject.toml` | `ruff check .` | `ruff format .` | `python -m build` | `pytest` |
| `Cargo.toml` | `cargo clippy` | `cargo fmt` | `cargo build` | `cargo test` |
| `go.mod` | `golangci-lint run` | `go fmt` | `go build ./...` | `go test ./...` |
| Unknown | Skip automated gates (log warning) | — | — | — |

If multiple project files exist, run ALL matching linters/builds.

---

## Step 1.5: Bootstrap lint config if absent

Before running any linter, check whether a lint config exists. If not, create one.
**Do not overwrite existing configs** — this step only runs when the config is missing.

### JavaScript / TypeScript (`package.json` present)

Check for any of: `.eslintrc`, `.eslintrc.js`, `.eslintrc.cjs`, `.eslintrc.json`,
`.eslintrc.yaml`, `.eslintrc.yml`, `eslint.config.js`, `eslint.config.mjs`,
or `"eslintConfig"` key in `package.json`.

If none found → create `eslint.config.js` at the project root:

```js
import js from "@eslint/js";
export default [
  js.configs.recommended,
  { ignores: ["dist/", "node_modules/", "coverage/", "build/"] },
];
```

If `typescript` is in `package.json` dependencies/devDependencies, use:

```js
import js from "@eslint/js";
import tseslint from "typescript-eslint";
export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
  { ignores: ["dist/", "node_modules/", "coverage/", "build/"] },
);
```

Install missing packages: `npm install --save-dev eslint @eslint/js` (add
`typescript-eslint` if TypeScript detected).

Check for `.prettierrc`, `.prettierrc.json`, `.prettierrc.js`, `prettier.config.js`,
or `"prettier"` key in `package.json`. If none found → create `.prettierrc`:

```json
{ "semi": true, "singleQuote": true, "trailingComma": "es5" }
```

Log: `[Skill] code-review-and-quality: bootstrapped ESLint config (eslint.config.js)`

---

### Python (`pyproject.toml` present)

Check for `[tool.ruff]` section in `pyproject.toml` or a standalone `ruff.toml`.
If neither exists → append to `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP"]
ignore = []
```

Log: `[Skill] code-review-and-quality: bootstrapped ruff config in pyproject.toml`

---

### Go (`go.mod` present)

Check for `.golangci.yml` or `.golangci.yaml`. If absent → create `.golangci.yml`:

```yaml
linters:
  enable:
    - govet
    - errcheck
    - staticcheck
    - unused
    - gosimple
run:
  timeout: 5m
```

Log: `[Skill] code-review-and-quality: bootstrapped golangci-lint config (.golangci.yml)`

---

### Rust (`Cargo.toml` present)

`cargo clippy` works without a config file. No bootstrap needed.

---

## Step 2: Lint and auto-fix

Run the project's linter with auto-fix enabled:

```bash
# JavaScript/TypeScript
npx eslint . --fix --max-warnings 0

# Python
ruff check . --fix

# Rust
cargo clippy --fix --allow-dirty

# Go
go fmt ./...
```

**Log every fix applied** to `aidlc-docs/audit.md`:
```
[Skill] code-review-and-quality: auto-fixed <N> lint issues
```

If linter exits with remaining warnings (non-auto-fixable), list them for the
review step.

---

## Step 3: Build

Run the project's build command:

```bash
# JS/TS
npm run build 2>&1

# Python
python -m build 2>&1

# Rust
cargo build 2>&1

# Go
go build ./... 2>&1
```

**If build fails:** the change is blocked. Do NOT proceed to review.
Log to audit: `[Skill] code-review-and-quality: BUILD FAILED — <error>`
Surface the build error to the user.

---

## Step 4: Run tests

```bash
# JS/TS
npm test 2>&1

# Python
pytest -v 2>&1

# Rust
cargo test 2>&1

# Go
go test ./... -v 2>&1
```

**If tests fail:** the change is blocked. Do NOT proceed to review.
Log to audit: `[Skill] code-review-and-quality: <N> TEST(S) FAILED`
Surface test failures to the user.

---

## Step 5: Five-axis review

Only after lint + build + test pass, do the conceptual review from the
standard skill:

1. **Correctness** — matches spec, edge cases, error paths
2. **Readability** — clear names, simple logic, no dead code
3. **Architecture** — fits system, clean boundaries, no duplication
4. **Security** — input validation, secrets, auth checks
5. **Performance** — N+1 queries, pagination, hot paths

For each finding, label severity: **Critical**, **Nit**, **Optional**, **FYI**.

---

## Step 6: Verify lint is clean after changes

If the review finds issues and code is modified to address them, re-run the
linter for the project's stack (same command as Step 2, without `--fix`):

```bash
npx eslint . --max-warnings 0   # JS/TS
ruff check .                    # Python
cargo clippy                    # Rust
golangci-lint run               # Go
```

Lint must remain clean after fixes.

---

## Completion

Log to `aidlc-docs/audit.md`:

```
[Skill] Executed: code-review-and-quality (Reviewer) — PASS
- Auto-fixed: <N> lint issues
- Build: <pass|fail>
- Tests: <N> passed, <N> failed
- Review findings: <N> (<Critical>, <Nit>, <Optional>)
```

---

## See Also

- Standard code-review-and-quality skill for detailed five-axis guidance
- References at `.agents/skills/_references/security-checklist.md`
- References at `.agents/skills/_references/performance-checklist.md`
