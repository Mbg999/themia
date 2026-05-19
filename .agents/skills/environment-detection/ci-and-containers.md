# CI and Container Environments — Detect-Only Mode

Loaded by `SKILL.md` Step 0 when CI or container is detected. **The whole point**: when an automated runner has already set up your runtime, installing a SECOND copy creates `$PATH` races and burns wall-clock for zero benefit. Detect-only is the right discipline.

## Detection

Run these probes in order:

```bash
# bash/zsh/sh — try each, stop at first match
[ -n "$CI" ]              && echo "context=ci-generic"
[ -n "$GITHUB_ACTIONS" ]  && echo "context=ci-github-actions"
[ -n "$GITLAB_CI" ]       && echo "context=ci-gitlab"
[ -n "$CIRCLECI" ]        && echo "context=ci-circle"
[ -n "$JENKINS_URL" ]     && echo "context=ci-jenkins"
[ -n "$BUILDKITE" ]       && echo "context=ci-buildkite"
[ -n "$TRAVIS" ]          && echo "context=ci-travis"
[ -n "$DRONE" ]           && echo "context=ci-drone"
[ -n "$TEAMCITY_VERSION" ] && echo "context=ci-teamcity"

[ -f /.dockerenv ]         && echo "context=container-docker"
[ -f /run/.containerenv ]  && echo "context=container-podman"
[ -n "$KUBERNETES_SERVICE_HOST" ] && echo "context=container-k8s"
```

```powershell
# PowerShell
$env:GITHUB_ACTIONS, $env:GITLAB_CI, $env:CI                 # any non-empty = CI
$env:BUILD_BUILDID                                            # Azure DevOps
```

Log the detected context to audit:

```
[Env] context: ci-github-actions
[Env] CI/container detected — entering detect-only mode (no installs)
```

## Detect-only mode rules

**MUST NOT** invoke any install command. This includes:

- `npm install -g`, `pip install --user`, `gem install`
- `brew install`, `apt install`, `dnf install`, `pacman -S`, `apk add`, `winget install`, `scoop install`, `choco install`
- `nvm install`, `asdf install`, `pyenv install`, `mise install`, `volta install`, `fnm install`
- Direct `curl <installer.sh> | sh` or `Invoke-WebRequest <installer>.exe`

**MAY** invoke:

- Read-only probes: `command -v`, `Get-Command`, `where`, `<tool> --version`
- `npm install` / `pip install -r requirements.txt` / `bundle install` etc — **project-local dependency installs** are part of the build, not the environment setup. The CI runner expects these to run.
- `npm ci` (preferred over `npm install` in CI — uses the lock file exactly)

## What CI runners pre-install (use it, don't replace it)

| Runner | Action | Result |
|---|---|---|
| GitHub Actions `actions/setup-node@v4` | Pre-installs requested Node version | `node` on PATH at action-managed location |
| GitHub Actions `actions/setup-python@v5` | Pre-installs requested Python | `python` on PATH |
| GitHub Actions `actions/setup-go@v5` | Pre-installs requested Go | `go` on PATH |
| GitLab CI `image: node:20` | Container ships with Node 20 | `node` on PATH from container |
| CircleCI orbs (`circleci/node@5`) | Pre-installs Node | `node` on PATH |
| Jenkins NodeJS plugin | Adds Node to PATH for the build | `node` on PATH |

The setup is **per-job**, persisted only for that job. The agent should:

1. Detect the runtime is present (`node --version`).
2. Verify it matches the project pin.
3. If mismatch → log `[RedFlag] env: CI runner provided <ver-A>, project requires <ver-B> — fix the workflow file, not the agent`.

**Never** try to "fix" a runner version mismatch by installing a different version inside the job. The fix lives in the workflow YAML (`.github/workflows/*.yml`), not in the agent's commands.

## Container-specific guidance

Inside a Docker/Podman container during a build:

- The container image is the contract. If `node:20-alpine` is the image, you have Node 20 on Alpine, period.
- `apt`/`apk`/etc. are available for installing system libraries (e.g. `apk add --no-cache build-base` for native node-gyp deps) but NOT for language runtimes (those are baked in).
- If the project pin doesn't match the container's runtime version, the Dockerfile is wrong — fix the FROM line, not the agent.

## Distinguishing agent-INSIDE-container vs agent-BUILDS-container

This is the one nuance worth getting right:

- **Agent is RUNNING inside a container** (e.g. `/factory-build` invoked from inside a Docker dev container): detect-only mode applies. The container provides the runtime.
- **Agent is BUILDING a Dockerfile** (e.g. unit spec includes a Dockerfile, and the build-test-agent is generating it): the Dockerfile's RUN commands ARE installs, and they happen inside a fresh image. Those are NOT CI-mode — they're definitional. The skill still applies to the `RUN` line: pick `apk add --no-cache <pkg>` over `apt install` if the base is alpine, etc.

Heuristic: if `/.dockerenv` exists on the host the agent is running on right now → agent is INSIDE a container → detect-only. If the agent is writing a Dockerfile to disk → those install commands apply Steps 3-4 as normal, targeting whatever distro the base image specifies.

## Output

```
[Env] context: ci-github-actions
[Env] CI/container detected — detect-only mode
[Env] node detected: v20.10.0 at /opt/hostedtoolcache/node/20.10.0/x64/bin/node (runner-provided)
[Env] project pin .nvmrc: 20 — match ✓
[Env] python detected: 3.11.7 at /opt/hostedtoolcache/Python/3.11.7/x64/bin/python (runner-provided)
[Env] detection complete: 2 tool(s) verified from runner, 0 installs (CI policy)
```

The headline number is `0 installs`. In CI, that's the whole point.

## Anti-pattern to escalate

If a stage has a strict requirement to install something in CI (e.g. a binary the runner doesn't provide), surface it as `[RedFlag] env: CI policy says no installs, but stage needs <tool>. Recommendation: add to the workflow's setup step OR cache it in the container image, not in this agent's commands.`
