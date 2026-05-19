# Linux — Environment Detection Recipes

Loaded by `SKILL.md` Step 3.1 when platform is Linux (including WSL).

## Distro detection

```bash
[ -f /etc/os-release ] && . /etc/os-release && echo "$ID $VERSION_ID"
```

`$ID` values you'll see: `debian`, `ubuntu`, `pop`, `linuxmint` (apt) · `fedora`, `rhel`, `centos`, `rocky`, `almalinux` (dnf) · `arch`, `manjaro` (pacman) · `alpine` (apk) · `opensuse-leap`, `opensuse-tumbleweed` (zypper) · `nixos` (special — usually pre-managed).

## Shell expectations

- Default shell: `bash` (most distros), `dash` (Debian/Ubuntu `/bin/sh`), occasionally `zsh`.
- Init files: `~/.bashrc`, `~/.bash_profile`, `~/.profile`.
- **Alpine and minimal containers use `dash` as `/bin/sh`** — `source` doesn't exist, `[[ ]]` doesn't work. Use `.` (dot) and `[ ]`.
- POSIX `command -v` works in all of these.

## ⚠️ THE LINUX NODE TRAP

`apt install nodejs` and `dnf install nodejs` ship outdated Node on most LTS distros:

| Distro | Default Node version (as of 2024) | Modern project requirement |
|---|---|---|
| Ubuntu 20.04 LTS | 10.x | typically 18+ |
| Ubuntu 22.04 LTS | 12.x | typically 18+ |
| Debian 11 (bullseye) | 12.x | typically 18+ |
| Debian 12 (bookworm) | 18.x | acceptable for some |
| Fedora 38+ | 18.x | acceptable for some |
| RHEL 8/CentOS 8 | 10.x via AppStream | not viable |
| Alpine 3.18+ | 18.x | acceptable |

**Always verify with `node --version` after install.** If below project requirement, fall back to one of:

1. **NodeSource curl-script** (recommended):
   ```bash
   curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -   # Debian/Ubuntu
   sudo apt-get install -y nodejs
   # OR for RPM:
   curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo -E bash -
   sudo dnf install -y nodejs
   ```
2. **nvm** (preferred when user-owned install is OK):
   ```bash
   curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
   . "$HOME/.nvm/nvm.sh"
   nvm install 20
   ```

The same trap exists for `python3` on RHEL 7/CentOS 7 (Python 3.6) and Go on Debian (typically 2 versions behind). Always verify version against project requirement.

## Version managers — detection + recipes

Priority order: **mise → asdf → nvm/pyenv/rbenv/rustup → fnm/volta**.

### mise (any tool — recommended)

```bash
command -v mise && mise --version
mise install <tool>@<ver>
mise use <tool>@<ver>
mise current <tool>
```

### asdf (any tool)

```bash
[ -s "$HOME/.asdf/asdf.sh" ] && . "$HOME/.asdf/asdf.sh"
command -v asdf || { echo "asdf not loaded"; exit 1; }

asdf plugin list | grep -q "<tool>" || asdf plugin add <tool>
asdf install <tool> <ver>
asdf local <tool> <ver>
asdf current <tool>
```

### nvm (Node only)

```bash
[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh"
command -v nvm || { echo "nvm not loaded"; exit 1; }

nvm install <ver>
nvm use <ver>
node --version
```

### pyenv (Python only)

```bash
# pyenv on Linux usually needs `pyenv init` plumbed into shell rc files
eval "$(pyenv init -)"
pyenv install --skip-existing <ver>
pyenv local <ver>
python --version
```

Build deps required for pyenv to compile Python on Linux:

```bash
# Debian/Ubuntu
sudo apt install -y make build-essential libssl-dev zlib1g-dev \
  libbz2-dev libreadline-dev libsqlite3-dev curl libncursesw5-dev \
  xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev

# Fedora
sudo dnf install -y make gcc patch zlib-devel bzip2 bzip2-devel \
  readline-devel sqlite sqlite-devel openssl-devel tk-devel \
  libffi-devel xz-devel
```

### rustup (Rust only)

```bash
# Install rustup itself if missing:
command -v rustup || curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
. "$HOME/.cargo/env"

rustup install <ver>
rustup default <ver>
cargo --version
```

### fnm (Node only)

```bash
eval "$(fnm env)"
fnm install <ver>
fnm use <ver>
node --version
```

## System install fallback (per distro)

### Debian/Ubuntu (apt)

```bash
sudo apt-get update
sudo apt-get install -y <package>
# For Node — use NodeSource (see Linux Node trap above), NOT the distro package
```

### Fedora/RHEL/CentOS (dnf)

```bash
sudo dnf install -y <package>
# RHEL: enable EPEL for many packages
sudo dnf install -y epel-release
```

### Arch/Manjaro (pacman)

```bash
sudo pacman -Sy --noconfirm <package>
# Arch usually ships current versions — Node trap is rare here
```

### Alpine (apk)

```bash
sudo apk add --no-cache <package>
# Common in containers — pyenv build deps are limited; prefer pre-built python
```

### Snap (Ubuntu / others)

```bash
# Officially supported channel for Node — newer than apt
sudo snap install node --channel=20/stable --classic
```

### openSUSE (zypper)

```bash
sudo zypper install -y <package>
```

## Container runtimes (Docker, Podman)

When running INSIDE a container, the package manager is often locked to the base image. Detect with:

```bash
[ -f /.dockerenv ] && echo "docker"
[ -f /run/.containerenv ] && echo "podman"
```

If running inside a container during a stage (vs the stage installing things into a fresh container the agent builds), default to **detect-only mode** per [`../ci-and-containers.md`](../ci-and-containers.md).

## WSL specifics

WSL is Linux. Use the underlying distro's recipes. Watch for:

- Windows-side PATH leaking in: `command -v node` may return `/mnt/c/Program Files/nodejs/node.exe` if Windows Node is installed and `appendWindowsPath=true`. That's NOT what you want for Linux builds.
- Line endings: clone repos with `git config --global core.autocrlf input` so scripts have LF.
- Performance: keep code under `~/`, NOT `/mnt/c/`, for usable filesystem speed.

## Verify after switch/install

```bash
<tool> --version                                 # must match requested ver
command -v <tool>                                # path must be inside expected dir
```

Expected paths:

| After | Path should contain |
|---|---|
| `nvm use 20` | `~/.nvm/versions/node/v20.*/bin/node` |
| `asdf local nodejs 20.10.0` | `~/.asdf/installs/nodejs/20.10.0/bin/node` |
| `mise use node@20` | `~/.local/share/mise/installs/node/20.*/bin/node` |
| `pyenv local 3.11.7` | `~/.pyenv/versions/3.11.7/bin/python` |
| `apt install nodejs` (post-NodeSource) | `/usr/bin/node` |
| `snap install node` | `/snap/bin/node` |
