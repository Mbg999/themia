# Thermia

AI-powered retrieval and analysis platform.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) 24+
- [Docker Compose](https://docs.docker.com/compose/install/) v2 (included with Docker Desktop)
- [git](https://git-scm.com/)
- Python 3.12+ (for local non-Docker development)
- Node.js 20+ (for local non-Docker frontend development)

---

## From clone to running stack in under 10 commands

```bash
git clone <repo-url>
cd thermia
cp thermia-back/.env.example thermia-back/.env
# Edit thermia-back/.env and fill in real values (see Environment Variables below)
docker compose up --build
```

The frontend will be available at http://localhost and the backend API at http://localhost:8000.

---

## Local development (without Docker)

### Backend

```bash
cd thermia-back
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in values
.venv/bin/alembic upgrade head          # run DB migrations
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd thermia-front
npm install
npm start                      # serves at http://localhost:4200
```

---

## Data ingestion

Run the ingestion pipeline to load documents into the vector store:

```bash
cd thermia-back
source .venv/bin/activate
python scripts/ingest.py --help        # show available options
python scripts/ingest.py <path>        # ingest a file or directory
```

---

## Running with Docker Compose

```bash
# Build images and start all services
docker compose up --build

# Run in the background
docker compose up --build -d

# Tail logs
docker compose logs -f

# Stop everything
docker compose down
```

The database runs on a remote VPS — there is no postgres container in the Compose stack.
Ensure `DATABASE_URL` (or the SSH tunnel vars) in `thermia-back/.env` points to the VPS.

---

## Environment variables reference

### Backend (`thermia-back/.env`)

| Variable | Description |
|---|---|
| `THERMIA_ENV` | `production` for direct DB access; `local` to use the SSH tunnel |
| `DATABASE_URL` | PostgreSQL connection URL (used when `THERMIA_ENV=production`) |
| `SSH_HOST` | Bastion / VPS hostname for SSH tunnel (used when `THERMIA_ENV=local`) |
| `SSH_USER` | SSH username for the tunnel |
| `SSH_PASSWORD` | SSH password for the tunnel |
| `SSH_REMOTE_BIND_PORT` | Remote PostgreSQL port to forward (usually `5432`) |
| `DB_USER` | PostgreSQL username (used when `THERMIA_ENV=local`) |
| `DB_PASSWORD` | PostgreSQL password (used when `THERMIA_ENV=local`) |
| `DB_NAME` | PostgreSQL database name (used when `THERMIA_ENV=local`) |
| `COHERE_API_KEY` | Cohere API key — required for the ingestion pipeline |
| `API_KEY` | Bearer token required for `POST /analyze` |
| `GROQ_API_KEY` | Groq LLM API key — required for `POST /analyze` |

### Frontend (`thermia-front/.env.example`)

The Angular frontend does not read `.env` files at runtime. `API_URL` and `API_KEY`
are provided here for reference only; they are configured in `src/environments/`.

| Variable | Description |
|---|---|
| `API_URL` | Base URL of the backend API |
| `API_KEY` | API key sent with requests to `/analyze` |

---

## Architecture overview

See [DESIGN.md](DESIGN.md) for the full architecture, data flow, and key design decisions.

---

## Ports

| Service | Port | Description |
|---|---|---|
| `thermia-front` | 80 | Angular SPA served by nginx; proxies `/analyze` and `/health` to backend |
| `thermia-back` | 8000 | FastAPI backend |
