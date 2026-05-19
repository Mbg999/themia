# Unit Spec: `docker-infra`
**Run ID:** 2026-05-19t09-35-00z-thermia-mvp
**Layer:** 2 | **Dependencies:** `retrieval-api`, `ingestion-pipeline`

---

## Purpose
Container definitions and orchestration for the Thermia production stack. Packages `thermia-back` (FastAPI) and `thermia-front` (Angular → nginx) into Docker images, wires them together with `docker-compose.yml`, and provides `.env.example` files so new developers can configure the stack without guessing required variables.

> **No postgres service** — the database runs on the VPS; local dev uses an SSH tunnel from the app container (or natively), production connects directly.

## Responsibilities
- `Dockerfile` for `thermia-back` (Python 3.12-slim, non-root user, `requirements.txt` install)
- `Dockerfile` for `thermia-front` (multi-stage: Node 20 build → nginx:alpine serve)
- `nginx.conf` for Angular SPA: `try_files $uri /index.html` + upstream proxy to `thermia-back:8000`
- `docker-compose.yml` with both services, env_file references, port mappings (8000, 80)
- `.env.example` for `thermia-back/` (all 9 backend env vars, no real values)
- `.env.example` for `thermia-front/` (`apiUrl`, `apiKey`)
- Root `README.md` (monorepo): prerequisites, local dev setup, ingestion steps, Docker run, env var reference

## Public Interfaces
| Interface | Consumer | Description |
|---|---|---|
| `http://localhost:80` | Browser | Angular SPA (nginx) |
| `http://localhost:8000` | Angular SPA / direct | FastAPI backend |
| `docker compose up --build` | Developer | Full stack startup |

## Internal Dependencies
| Unit | Why |
|---|---|
| `retrieval-api` | `thermia-back` Dockerfile builds from `thermia-back/` — needs source to be complete |
| `ingestion-pipeline` | `ingest.py` must exist in `thermia-back/scripts/` to document in README |

## External Dependencies
| Tool | Version | Purpose |
|---|---|---|
| Docker | 24+ | Container runtime |
| Docker Compose | v2 | Multi-service orchestration |
| nginx | alpine | Serve Angular static build + proxy |
| Python | 3.12-slim | Backend base image |
| Node | 20-alpine | Frontend build base image |

## Tasks
| Task | Description |
|---|---|
| INF-T1 | `Dockerfile` for `thermia-back` (Python 3.12-slim, non-root, pip install) |
| INF-T2 | `Dockerfile` for `thermia-front` (multi-stage Node build → nginx:alpine) |
| INF-T3 | `nginx.conf` (SPA routing + backend proxy) |
| INF-T4 | `docker-compose.yml` (two services, env_file, port mappings, healthchecks) |
| INF-T5 | `.env.example` files for both services |
| INF-T6 | Root `README.md` (setup, local dev, ingestion, Docker, env vars reference) |

## Acceptance Criteria (rolled up)
- [ ] `docker build -f thermia-back/Dockerfile -t thermia-back .` succeeds
- [ ] `thermia-back` container starts FastAPI on port 8000; `GET /health` returns `{"status": "ok"}`
- [ ] `docker build -f thermia-front/Dockerfile -t thermia-front .` succeeds
- [ ] `thermia-front` container serves Angular SPA on port 80
- [ ] Deep links (e.g. `localhost:80/any/path`) resolve to `index.html`
- [ ] `docker compose up --build` starts both services; no startup errors
- [ ] Frontend loads at `http://localhost:80`; backend reachable at `http://localhost:8000`
- [ ] `.env.example` in `thermia-back/` lists all 9 env vars from requirements §5
- [ ] `.env.example` in `thermia-front/` lists `apiUrl` + `apiKey`
- [ ] `.env` and `.env.*` entries exist in root `.gitignore`
- [ ] README new-developer path: from clone to running stack in ≤ 10 commands

## Definition of Done
- All tasks complete
- `docker compose up --build` tested end-to-end locally
- No secrets in any committed file; `.env.example` has placeholder values only
- README verified by following it on a clean machine (or clean shell)
