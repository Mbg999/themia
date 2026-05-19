---
name: environment-detection
description: Cross-platform detect-before-install discipline for language runtimes, package managers, and build tools. Works on macOS, Linux (Debian/RHEL/Arch/Alpine), Windows (PowerShell + WSL), and inside CI/container environments. Loads platform-specific recipes on demand from platforms/{macos,linux,windows}.md and short-circuits installs when running under CI/container per ci-and-containers.md. Use BEFORE any install command in build-test-agent, code-generator, and workspace-scout.
---

# Environment Detection

Cross-platform tool detection + install discipline. Prevents the
"install-everything-from-brew" trap, the "apt's-Node-is-from-2017" trap, the
"PowerShell-doesn't-have-`command -v`" trap, and the "CI-already-set-up-Node
but-I-installed-a-second-one" trap.

## Why this skill exists

Real failure modes seen in production:

1. macOS: User has `node@20` via nvm. Agent runs `brew install node@20`. Brew compiles from source. **180s timeout**.
2. Ubuntu 22.04: Agent runs `apt-get install -y nodejs`. Gets Node 12. Project requires Node 18+. Build fails at runtime with cryptic syntax errors.
3. Windows PowerShell: Agent runs `command -v node`. Returns nothing because `command` doesn't exist in PowerShell. Agent concludes node is missing, downloads installer, installs second copy. PATH ordering breaks the previously-working setup.
4. GitHub Actions runner: `setup-node@v4` already pinned Node 20. Agent doesn't check, installs another Node via nvm. `which node` flips between the two on subsequent commands.

This skill makes detection cross-platform, CI-aware, and idempotent.

## Process (mandatory order)

### Step 0 — Platform + context fingerprint

Before detecting tools, fingerprint the environment. The fingerprint determines which platform recipe file to load AND whether to short-circuit installs entirely.

| Probe | Result | Next |
|---|---|---|
| `$CI`, `$GITHUB_ACTIONS`, `$GITLAB_CI`, `$CIRCLECI`, `$JENKINS_URL`, `$BUILDKITE` any set | CI environment | Load [`ci-and-containers.md`](ci-and-containers.md) → detect-only mode (Steps 1+2, then stop). Do NOT install. |
| `/.dockerenv` exists OR `/run/.containerenv` exists | Container | Same as CI — respect what the image provides. |
| `uname` returns `Darwin` | macOS | Load [`platforms/macos.md`](platforms/macos.md) |
| `uname` returns `Linux` | Linux | Load [`platforms/linux.md`](platforms/linux.md). Detect distro via `/etc/os-release` `ID=` (debian/ubuntu/fedora/rhel/arch/alpine). |
| `$OS` equals `Windows_NT` AND shell is PowerShell or cmd | Windows native | Load [`platforms/windows.md`](platforms/windows.md) |
| `$OS` equals `Windows_NT` AND shell is bash (WSL) | WSL | Treat as Linux — load [`platforms/linux.md`](platforms/linux.md) |

Detection commands (try in this order — first to succeed wins):

```bash
# bash / zsh / sh / dash
uname -s                          # Darwin | Linux | MINGW*/MSYS*/CYGWIN* (Git Bash on Windows)
[ -f /etc/os-release ] && . /etc/os-release && echo "$ID"
[ -n "$CI" ] && echo "CI=$CI"
[ -f /.dockerenv ] && echo "container=docker"
```

```powershell
# PowerShell
$env:OS                           # Windows_NT
$PSVersionTable.PSVersion         # PowerShell version
$env:GITHUB_ACTIONS               # CI signal
```

Emit one summary audit entry:

```
[Env] platform: <os> <distro?> · shell: <bash|zsh|sh|powershell|cmd> · context: <standard|ci-<name>|container>
```

### Step 1 — Detect each required tool

For every tool the stage needs, run the platform-appropriate probe.

| Shell | Existence | Version |
|---|---|---|
| bash/zsh/sh/dash | `command -v <tool>` (POSIX; prefer over `which`) | `<tool> --version` |
| PowerShell | `Get-Command <tool> -ErrorAction SilentlyContinue` | `<tool> --version` |
| cmd.exe | `where <tool>` | `<tool> --version` |

Notes:

- **macOS gotcha**: `/usr/bin/python` is Python 2 or absent on modern macOS. Always probe `python3`, never `python`.
- **Path gotcha**: on Windows, paths use `\`; in PowerShell single-quote everything to avoid escape-character issues.
- **Dash gotcha**: Alpine and some Docker images use `dash` as `/bin/sh`. `[[ ]]` and `source` don't work. Use `[ ]` and `.`.

Log every result:

```
[Env] node detected: v20.10.0 at /Users/x/.nvm/versions/node/v20.10.0/bin/node
[Env] python3 missing
```

### Step 2 — Compatible? Use it.

If a tool is detected AND its version satisfies the requirement → **USE IT. Stop.** Log `[Env] <tool> <ver> — using existing`. Skip Step 3 and Step 4 for that tool.

How "compatible" is decided:

1. Project pin (highest precedence — see Step 3.0 table).
2. Unit spec's explicit version requirement.
3. Reasonable LTS default if neither pin nor spec specifies.

### Step 3 — Read project pin, then use a version manager

#### Step 3.0 — Project pin precedence (universal)

Read pin files BEFORE picking a version. Project pin always wins:

| Pin file | Tool | Example | Precedence |
|---|---|---|---|
| `.tool-versions` | any (asdf/mise) | `nodejs 20.10.0` | highest |
| `.nvmrc` | Node | `20` or `v20.10.0` | high |
| `.node-version` | Node | `20.10.0` | high |
| `.python-version` | Python | `3.11.7` | high |
| `.ruby-version` | Ruby | `3.2.2` | high |
| `package.json` → `engines.node` | Node | `">=18.0.0"` | medium |
| `pyproject.toml` → `requires-python` | Python | `">=3.10"` | medium |
| `rust-toolchain.toml` → `toolchain.channel` | Rust | `"1.75.0"` | medium |
| `Gemfile` → `ruby 'X'` | Ruby | `ruby '3.2.2'` | medium |
| `go.mod` → `go X.Y` | Go | `go 1.22` | medium |

If a pin file is present, **use that version**. Don't upgrade "because newer is better". Pin files exist for compatibility reasons you don't know.

#### Step 3.1 — Load the platform recipe file

Load the platform-specific recipes for version managers and system installers:

- **macOS** → [`platforms/macos.md`](platforms/macos.md)
- **Linux** → [`platforms/linux.md`](platforms/linux.md)
- **Windows native** → [`platforms/windows.md`](platforms/windows.md)
- **WSL** → [`platforms/linux.md`](platforms/linux.md) (it's Linux underneath)

Each platform file documents:
- Available version managers and their detection probes
- Install/switch recipes per manager (idempotent, copy-pasteable)
- System install fallbacks
- Platform-specific traps (e.g. Linux Node trap, macOS python symlink)

#### Step 3.2 — Decision tree (universal)

```
detected version == required version  → no-op, you're done (Step 2 path)
detected version != required version  → SWITCH via manager (no reinstall)
detected: nothing                     → INSTALL via manager
no manager available                  → Step 4 (system install)
```

Never reinstall a version a manager already has. Most managers' install commands are idempotent (`nvm install`, `asdf install`, `pyenv install --skip-existing`) — that's safe. The anti-pattern is using a *different* installer (e.g. `brew install node`) when a manager already has the version.

### Step 4 — System install (last resort, platform-specific)

If no version manager is available (rare on developer machines, common in fresh CI/containers), fall back to the platform's system package manager. The platform recipe file documents this — read it.

**Cross-cutting traps that bite on every platform:**

- **Linux Node trap**: `apt install nodejs` (Debian/Ubuntu) and `dnf install nodejs` (Fedora) often ship outdated Node (12-16 on LTS distros that are still in support). Always check `node --version` after install; if below project requirement, fall back to NodeSource curl-script OR nvm. See [`platforms/linux.md`](platforms/linux.md).
- **macOS Python trap**: `/usr/bin/python` is the system Python (Python 2 / minimal Python 3). Don't use it for application work. Use pyenv-installed Python or `python3` from brew (which itself can be slow — prefer pyenv).
- **Windows installer trap**: Direct `.msi` installs from a website silently write to Program Files but don't always update PATH for current shell. Restart shell OR `refreshenv` (with choco) after install.

### Step 5 — Verify after switch/install

After ANY install or switch, verify with the actual tool:

```bash
# bash/zsh/sh
<tool> --version          # must match the requested version
command -v <tool>         # path must be inside the manager's dir (~/.nvm/, ~/.asdf/, etc.)
```

```powershell
# PowerShell
& <tool> --version
(Get-Command <tool>).Source     # must be inside the manager's dir
```

If `command -v` / `Get-Command` resolves OUTSIDE the manager's dir (e.g. `/opt/homebrew/bin/node` after `nvm use 20`), `$PATH` ordering is wrong. Log `[RedFlag] env: <tool> PATH resolves to <wrong-path> despite manager <X> picking <ver>` and surface — don't silently continue.

## Anti-patterns to REJECT

| Rationalization | Reality |
|---|---|
| "node@20 is available via brew, let me install" | Check `command -v node` / `Get-Command node` FIRST. |
| "brew/winget/apt is the standard install path on this OS" | Standard ≠ fastest. Version managers pull pre-built binaries in seconds. |
| "I'll install fresh to be safe" | Two installations on PATH compete; fresh is LESS safe. |
| "I'm in CI, install is fine — it's ephemeral" | CI runners pre-install runtimes. Installing a second copy breaks the runner's $PATH. Use what's there. |
| "PowerShell doesn't have command -v so I'll just install" | PowerShell has `Get-Command`. Use it. |
| "`apt install nodejs` works on my Ubuntu 22.04" | Yes — and ships Node 12. Verify version against requirement. |
| "I'll skip the verify step, the install succeeded" | Install succeeding ≠ tool on PATH for current/next shell. ALWAYS verify. |

## Red flags (escalate)

- `brew install` running > 60s with no stdout → compiling from source → STOP, kill, re-check Step 1.
- `apt install nodejs` returns Node version below the project's requirement → STOP, switch to NodeSource or nvm.
- `command -v <tool>` resolves to a path OUTSIDE the version manager's dir after `nvm use` / `asdf local` → `$PATH` ordering issue.
- `Get-Command <tool>` returns multiple results → multiple installs on Windows PATH; pick the manager-owned one explicitly with full path.
- CI variable set AND attempt to install via a non-CI method → bug in agent logic. Escalate.

## Output (mandatory `audit_entries[]`)

The skill produces an evidence chain in the audit log:

```
[Env] platform: <os> <distro?> · shell: <name> · context: <standard|ci-<name>|container>
[Env] detection start
[Env] <tool> detected: <version> at <path>           # one per tool
[Env] <tool> missing                                  # one per missing tool
[Env] project pin <pinfile>: <ver>                    # one per pin file found
[Env] <tool> resolved via <existing|nvm|asdf|mise|pyenv|brew|apt|winget|...>: <version>
[Env] verify: <tool> --version → <ver> ✓ at <path>
[Env] detection complete: <N> existing, <M> manager-handled, <K> system-installed, 0 source-builds in CI
```

The "0 source-builds" is the headline number when running in CI. Report it in stage completion.

## Verification (objective gates)

| Check | How |
|---|---|
| Platform fingerprinted | First `[Env] platform:` entry in `audit_entries[]` precedes any tool detection |
| Detection ran before any install | First `[Env] <tool> detected/missing` entry precedes any install command in audit log |
| No fresh install of an already-present tool | If `[Env] <tool> detected` is present, there MUST NOT be a subsequent system install for that tool |
| CI short-circuit honored | If `context: ci-*`, no install commands in audit log |
| Source-build avoided | No `brew install <tool>` ran longer than 60s without being killed |

## See also

- [`platforms/macos.md`](platforms/macos.md) — macOS-specific recipes (mise, asdf, nvm, pyenv, rbenv, rustup, brew)
- [`platforms/linux.md`](platforms/linux.md) — Linux-specific recipes incl. distro detection + Node trap
- [`platforms/windows.md`](platforms/windows.md) — Windows-native PowerShell recipes (nvm-windows, fnm, volta, winget, scoop, choco)
- [`ci-and-containers.md`](ci-and-containers.md) — CI/container detect-only short-circuit
- `aidlc-rules/aws-aidlc-rule-details/common/stage-conventions.md` — stage skill protocol
