# macOS — Environment Detection Recipes

Loaded by `SKILL.md` Step 3.1 when platform is Darwin.

## Shell expectations

- Default shell: `zsh` (Catalina 10.15+) or `bash` (older).
- Init files: `~/.zshrc`, `~/.zprofile`, `~/.bash_profile`, `~/.profile`.
- POSIX `command -v` works.

## macOS-specific traps

- `/usr/bin/python` is Python 2 / minimal Python 3 — **never use for app work**. Probe `python3` only.
- `/usr/bin/ruby` is the system Ruby (often 2.6) — same warning, use rbenv-managed Ruby.
- Apple Silicon: brew lives at `/opt/homebrew/`; Intel macs: `/usr/local/`. Either is fine but be aware when reading `command -v` output.
- Xcode Command Line Tools (`xcode-select --install`) provides system `git`, `make`, `clang`. These are usually fine; don't replace with brew versions unless required.

## Version managers — detection + recipes

Priority order: **mise → asdf → nvm/pyenv/rbenv/rustup → fnm/volta**.

### mise (any tool — recommended)

```bash
command -v mise && mise --version
# Reads .tool-versions automatically when cd'd into the project dir.

mise install <tool>@<ver>          # idempotent
mise use <tool>@<ver>              # writes .tool-versions (project-pin)
mise use --global <tool>@<ver>     # global default
mise current <tool>                # verify
```

### asdf (any tool)

```bash
# Source init first — asdf is a shell function
[ -s "$HOME/.asdf/asdf.sh" ] && . "$HOME/.asdf/asdf.sh"
command -v asdf || { echo "asdf not loaded"; exit 1; }

# Plugin is required per language
asdf plugin list | grep -q "<tool>" || asdf plugin add <tool>
asdf install <tool> <ver>          # idempotent: no-op if already installed
asdf local <tool> <ver>            # writes .tool-versions
asdf current <tool>                # verify
```

### nvm (Node only)

```bash
# Source init first — nvm is a shell function
[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh"
command -v nvm || { echo "nvm not loaded"; exit 1; }

# If .nvmrc exists, the simplest form:
nvm install                        # reads .nvmrc, installs that version
nvm use                            # activate it

# Otherwise:
nvm install <ver>                  # idempotent
nvm use <ver>
node --version                     # verify (should match)
```

### pyenv (Python only)

```bash
# pyenv is normally on PATH after brew install pyenv + shell init
eval "$(pyenv init -)"

pyenv install --skip-existing <ver>
pyenv local <ver>                  # writes .python-version
python --version                   # verify
```

### rbenv (Ruby only)

```bash
eval "$(rbenv init -)"
rbenv install --skip-existing <ver>
rbenv local <ver>
ruby --version
```

### rustup (Rust only)

```bash
rustup install <ver>
rustup default <ver>               # global default
# OR project pin:
echo "<ver>" > rust-toolchain
cargo --version
```

### fnm (Node only, fast Rust-based)

```bash
eval "$(fnm env)"
fnm install <ver>
fnm use <ver>
node --version
```

### volta (Node only, pins per-project automatically)

```bash
volta install node@<ver>           # installs + pins in package.json
node --version
```

## System install fallback (brew)

**Only when no version manager is available.** Brew is slow when formulas build from source — many do. Look for "Pouring <bottle>" in output = pre-built (fast); silence or "Compiling" = source build (slow).

```bash
# Detect brew
command -v brew && brew --version

# Install a runtime (versioned formulas avoid source builds more often)
brew install node@20               # versioned bottle — usually pre-built
brew install python@3.11

# RED FLAG: if `brew install` is running > 60s with no output:
#   1. STOP it (Ctrl+C / kill)
#   2. Re-run `command -v <tool>` — tool may already exist
#   3. If truly missing, try a version manager instead

# Post-install: brew doesn't always link versioned formulas
brew link --overwrite --force node@20    # only when needed
```

## Apple Silicon (M1/M2/M3) specifics

- `arch` returns `arm64`.
- Some node-gyp builds need Xcode CLI Tools AND Rosetta for legacy packages: `softwareupdate --install-rosetta --agree-to-license` (one-time).
- Brew at `/opt/homebrew/bin` must be on `$PATH` before `/usr/local/bin` for Apple Silicon native bottles.

## Verify after switch/install

```bash
<tool> --version                                 # must match requested ver
command -v <tool>                                # path must be inside manager's dir
echo "$PATH" | tr ':' '\n' | head -5             # debug PATH ordering if mismatch
```

Expected `command -v` results:

| After | Path should contain |
|---|---|
| `nvm use 20` | `~/.nvm/versions/node/v20.*/bin/node` |
| `asdf local nodejs 20.10.0` | `~/.asdf/installs/nodejs/20.10.0/bin/node` |
| `mise use node@20` | `~/.local/share/mise/installs/node/20.*/bin/node` (or similar) |
| `pyenv local 3.11.7` | `~/.pyenv/versions/3.11.7/bin/python` |
| `brew install node@20` | `/opt/homebrew/opt/node@20/bin/node` (M1+) or `/usr/local/opt/node@20/bin/node` (Intel) |

If `command -v` resolves outside the expected path, the manager's shim hasn't won the PATH race. Source the init script again or surface as a red flag.
