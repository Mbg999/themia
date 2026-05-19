# Windows (Native) — Environment Detection Recipes

Loaded by `SKILL.md` Step 3.1 when platform is Windows AND shell is PowerShell or cmd.

**For WSL, use [`linux.md`](linux.md) instead** — WSL is Linux underneath, even though `$OS` may say `Windows_NT` from PowerShell's perspective.

## Shell detection

```powershell
# PowerShell
$PSVersionTable.PSVersion          # 5.1 = Windows PowerShell, 7+ = PowerShell Core
$env:OS                            # Windows_NT
```

```cmd
:: cmd.exe — no version variable but ECHOTEST works
ver                                 :: Windows version string
```

Default to PowerShell — cmd.exe is largely deprecated for tooling.

## Windows-specific gotchas

- **`command -v` doesn't exist** in PowerShell or cmd. Use `Get-Command` (PowerShell) or `where` (cmd).
- **Path separator is `\`** not `/`. PowerShell tolerates both in most APIs but external tools may not.
- **PATH is `;`-separated**, not `:`. `$env:PATH -split ';'` to inspect.
- **Refresh PATH after install**: new installs update the registry but NOT the current shell's `$env:PATH`. Either open a new shell OR use `refreshenv` (ships with chocolatey) OR manually re-read:
  ```powershell
  $env:PATH = [Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [Environment]::GetEnvironmentVariable("PATH", "User")
  ```
- **Spaces in paths**: `C:\Program Files\nodejs` requires quoting in shell invocations.
- **CRLF line endings** can break shell scripts cloned into WSL — set `git config core.autocrlf input` in WSL contexts.
- **Execution policy**: PowerShell scripts may need `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. Don't change machine-wide silently.

## Detection commands

```powershell
# PowerShell — exists?
Get-Command node -ErrorAction SilentlyContinue
# Version
node --version

# Get the resolved path
(Get-Command node).Source
```

```cmd
:: cmd.exe
where node
node --version
```

## Version managers (Windows)

Priority: **mise → fnm → volta → nvm-windows → pyenv-win → scoop/winget for system**.

⚠️ **`nvm-windows` ≠ Unix `nvm`** — different commands, different repo, different behavior. The skill uses "nvm-windows" explicitly to avoid confusion.

### mise (any tool — supports Windows since 2024)

```powershell
# Install:
winget install jdx.mise
# Usage (cross-platform — same as Unix):
mise install <tool>@<ver>
mise use <tool>@<ver>
mise current <tool>
```

### fnm (Node only — cross-platform Rust binary, fast)

```powershell
# Install via winget or scoop:
winget install Schniz.fnm
# OR: scoop install fnm

# Initialize (add to PowerShell $PROFILE):
fnm env --use-on-cd | Out-String | Invoke-Expression

fnm install <ver>
fnm use <ver>
node --version
```

### volta (Node only — pins per-project automatically)

```powershell
winget install Volta.Volta
# Restart shell after install

volta install node@<ver>
node --version
```

### nvm-windows (Node only — NOT the Unix nvm)

```powershell
# Install via winget:
winget install CoreyButler.NVMforWindows

# Use (note: requires explicit patch version, not "20")
nvm install 20.10.0
nvm use 20.10.0
nvm on                            # enable nvm-windows symlink

node --version                    # verify
```

⚠️ Limitations vs Unix nvm:
- `.nvmrc` is NOT auto-honored — must read it manually:
  ```powershell
  $ver = (Get-Content .nvmrc).Trim()
  nvm install $ver
  nvm use $ver
  ```
- No `nvm install --lts` shortcut — use full version.
- Requires admin once at install time to create the symlink.

### pyenv-win (Python only — Windows port of pyenv)

```powershell
# Install via pip OR git clone OR winget
winget install PyEnv-win.PyEnv-win
# Add to PATH (installer usually handles this; restart shell)

pyenv install <ver>
pyenv local <ver>                 # writes .python-version
pyenv rehash                      # rebuild shims
python --version
```

### rustup (Rust — same as Unix)

```powershell
# Install (downloads rustup-init.exe automatically):
winget install Rustlang.Rustup
# OR: Invoke-WebRequest -Uri https://win.rustup.rs -OutFile rustup-init.exe; .\rustup-init.exe -y

rustup install <ver>
rustup default <ver>
cargo --version
```

## System package managers (Windows)

Priority: **winget > scoop > chocolatey > direct .msi/.exe download**.

### winget (built into Windows 10 1809+ and Windows 11)

```powershell
# Search:
winget search Node.js
# Install (typically pre-built, fast):
winget install OpenJS.NodeJS.LTS
winget install Python.Python.3.11
winget install Microsoft.OpenJDK.17
winget install Git.Git
```

Pros: ships with Windows, signed packages, fast.
Cons: limited selection compared to scoop/choco.

### scoop (user-scope, no admin needed)

```powershell
# Install scoop itself if missing:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression

scoop install nodejs-lts
scoop install python
scoop install fnm
```

Pros: no admin, easy uninstall, project-local installs via buckets.
Cons: smaller default repo (use additional buckets).

### chocolatey (oldest, largest catalog, needs admin)

```powershell
# Install choco itself (admin PowerShell):
Set-ExecutionPolicy Bypass -Scope Process -Force
Invoke-Expression ((New-Object Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))

choco install nodejs-lts -y
choco install python -y
refreshenv                        # refresh PATH for current shell
```

Pros: largest catalog.
Cons: needs admin.

## Verify after switch/install

```powershell
# Version match
<tool> --version

# Path match — must be inside manager's dir
(Get-Command <tool>).Source

# Inspect PATH ordering
$env:PATH -split ';' | Select-Object -First 5
```

Expected paths:

| After | Path should contain |
|---|---|
| `nvm use 20.10.0` (nvm-windows) | `C:\Users\<u>\AppData\Roaming\nvm\v20.10.0\node.exe` (symlinked from `nodejs\node.exe`) |
| `fnm use 20` | `%LOCALAPPDATA%\fnm_multishells\<id>_*\node.exe` |
| `volta install node@20` | `%LOCALAPPDATA%\Volta\bin\node.exe` (shim) |
| `mise use node@20` | `%LOCALAPPDATA%\mise\installs\node\20.*\node.exe` |
| `pyenv local 3.11.7` | `%USERPROFILE%\.pyenv\pyenv-win\versions\3.11.7\python.exe` |
| `winget install OpenJS.NodeJS.LTS` | `C:\Program Files\nodejs\node.exe` |
| `scoop install nodejs-lts` | `%USERPROFILE%\scoop\apps\nodejs-lts\current\node.exe` |
| `choco install nodejs-lts` | `C:\Program Files\nodejs\node.exe` |

## Common Windows-specific traps

- **Two Node installs**: User has Node from nvm-windows AND from a direct .msi install. `Get-Command node` returns whichever wins PATH. Escalate as `[RedFlag] env: multiple node installs detected — <list of sources>`.
- **PATH ordering after admin install**: Tools installed by admin land in `Machine`-scope PATH; user managers land in `User`-scope. Machine wins by default. If a manager isn't taking precedence, this is why.
- **Long paths**: Windows MAX_PATH = 260 chars without long-path opt-in. node_modules nested deep can fail builds. Enable via `git config core.longpaths true` and the registry `LongPathsEnabled` policy.
