# Extension Loading

PRIORITY: P4

At workflow start, scan `extensions/` recursively but load ONLY lightweight
opt-in files — NOT full rule files.

## Loading process
1. List subdirectories under `extensions/`.
2. In each, load ONLY `*.opt-in.md` files. The corresponding rules file is
   derived by convention: strip `.opt-in.md` suffix, append `.md`.
3. Do NOT load full rule files at this stage.

## Deferred rule loading
- During Requirements Analysis, opt-in prompts are presented to user.
- User opts IN → load corresponding rules file.
- User opts OUT → rules file never loaded.
- Extensions without an `*.opt-in.md` are always enforced — load immediately.

## Enforcement
Extension rules are hard constraints. At each stage, evaluate which apply.
Non-compliance is a **blocking finding** — do NOT present completion until resolved.
Include compliance summary (compliant/non-compliant/N/A) at stage completion.

## Resolution order (enabled?)
1. Manifest default: `agents.yaml` with `enabled_by_default: true` → auto-enable.
2. Run state: `aidlc-docs/aidlc-state.md` explicit entry → follow value.
3. Opt-in prompt: present to user if neither 1 nor 2.
4. No opt-in file → enforced (loaded automatically).

Record decision (enabled/disabled/auto-enabled) in `aidlc-docs/audit.md`.
