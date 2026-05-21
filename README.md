# Themia

Plataforma de análisis legal potenciada por LLMs.

## Idea

Themia es una aplicación que permite a los usuarios subir documentos legales en formato PDF y obtener un análisis detallado de su contenido, incluyendo un resumen simple, implicaciones legales, fundamentos jurídicos, e información + enlaces a fuentes oficiales de la legislación española.
Mi idea principal con esto es dar una aproximación lo más full stack posible, donde poder demostrar experiencia y capacidades en todas las partes del desarrollo de software posibles:
- backend
- frontend
- base de datos
- control de versiones con git, todo está gestionado como un monorepo por sencillez de entrega, podría usarse NX como gestor del workspace o similar, pero me complicaría de más para el caso de uso.
- despliegue
- DevOps
- integración de LLMs
- diseño de prompts
- diseño de arquitecturas RAG
- uso de herramientas de agentic coding para el desarrollo asistido por IA con fuerte base en AI Engineering
- instalación y uso de ollama en VPS remoto para hosting de modelos de embeddings personalizados

## Diseño y desarrollo

He hecho el diseño, arquitectura y revisión yo mismo, y usado Claude Code como implementador, siendo la mayor parte desarrollada por este, siguiendo la respuesta que di en la primera entrevista cuando respondí que era mi "stack" favorito para hoy día, aunque también hay código y configuraciones hechas a mano.

El diseño se basa en un RAG híbrido: semantic + BM25 + metadatos + fusión con RFF + top_n 5
* PostgreSQL + pgvector
* pipeline de ingestión mediante [script Python](thermia-back/scripts/ingest.py), el cual clona un repositorio público de legislación española, parsea los archivos markdown, extrae la estructura legal, chunking por artículos, generación de embeddings y almacenamiento en la base de datos. Usa hashing de los metadatos para evitar duplicados, y crea una bdd de archivos ya indexados, permitiendo la carga paralelizada para agilizar tiempos (son +1200 archivos, muchisimos chunks, aquí he querido mostrar que entiendo el problema de las cargas de datos masivas y he realizado una implementación eficiente, parte de esto ha sido a mano).
* pipeline de recuperación, implementa un endpoint POST /analyze (hice otro /analyze/text para pruebas sin necesidad de pdf, pensado para puro debugging, podría escalarse para hacer un chatbot o similar) que acepta un PDF, detecta su intención, aplica filtros de metadata, realiza búsqueda vectorial y BM25, fusión RRF, construcción de contexto y razonamiento con LLM para generar la respuesta estructurada.
* el frontend en Angular es una SPA sencilla con un input para subir el PDF, botón de analizar y renderizado de resultados, siguiendo un diseño basado en el DESIGN.md que indico en la sección de tecnologías, inspirado en el estilo Apple, comunicación vía api rest, habilitado también mediante cors y utilizando una api key para autenticarse como cliente fiable, agregando una capa más de seguridad.

## Tecnologías

- Backend:
    * FastAPI v0.115.0
    * uvicorn v0.32.0
    * SQLAlchemy v2.0.0
    * alembic v1.14.0
    * pytest v8.0.0
    * langchain v0.3.0
- Frontend:
    * Angular v21.2.0
    * diseño basado en [DESIGN.md](/DESIGN.md) estilo Apple extraido de la biblioteca (https://styles.refero.design)[https://styles.refero.design/style/c9cabb96-32fa-4896-837a-f2497ce1c856]
- Base de datos: PostgreSQL + pgvector (hosteada en VPS remoto)
- modelo de embeddings: bge-m3 hosteado en VPS remoto sobre Ollama
- LLMs para análisis: llama-3.3-70b-versatile sobre Groq via API
- datos legales: corpus de legislación española (BOE, CENDOJ, etc.) clonado desde repositorios públicos [https://github.com/legalize-dev/legalize-es](https://github.com/legalize-dev/legalize-es)
- despliegue con Docker Compose sobre VPS Ubuntu 22
- expuesto a internet via nginx reverse proxy (con HTTPS, certificados de letsencrypt manejados por certbot)
- claude code + opencode + harness propio (sirve para ambos)
    * basado en el enrutado de fases de [AWS AIDLC](https://github.com/awslabs/aidlc-workflows) + SDD + hardening + backpresure, ahora mismo lo tengo en un repo privado, pero tengo pensado abrirlo cuando lo cure un poco más, si ejecutas /factory-onboarding, debe de darte un paseo por su funcionalidad (no tengo muy depurado ese comando aun, siendo sincero 😂)
    * orquestación de agentes + subagentes con roles y skills
    * [engram](https://github.com/Gentleman-Programming/engram) como memoria para aprendizaje continuo del agentic coding tool
    * [codegraph](https://github.com/colbymchenry/codegraph) para indexación de los archivos del repositorio vía grafos, incluyo la base de datos en [.codegraph](/.codegraph)
    * [agent skills](https://github.com/addyosmani/agent-skills)
    * [autoskills](https://github.com/midudev/autoskills)
    * [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp)
    * trazabilidad y reproducibilidad
    * incluyo los archivos en [aidlc-docs](/aidlc-docs) que contienen las specs, planes, diagramas, historias de usuario, historial de ejecuciones, etc.
    * incluyo los archivos de historial de los agentes en [.aidlc-orchestrator/runs](/.aidlc-orchestrator/runs)
    * [rtk](https://www.rtk-ai.app/) para ahorro de tokens de input
- pipeline para GitHub Actions que ejecuta tests unitarios y verifica el esquema de la base de datos con cada push [.github/workflows/ci.yml](.github/workflows/ci.yml)

## Prompts de features y varios sobre uso de IA para desarrollo

- [Prompt inicial](/prompts/inicial.md) con los requerimientos iniciales que le di a Claude Code para el desarrollo, incluyendo la arquitectura, tecnologías, y requerimientos funcionales.
- [Prompt para agregar la feature de rotación de api keys](/prompts/rotacion_api_keys.md), me di cuenta de que las APIs gratuitas no me iban a servir para todas las peticiones que iba a hacer, así que hice una nueva aproximación para utilizar varias api keys e ir rotándolas.
### Prompt para agregar la feature de rotación de api keys
- [Prompt refactor metadata (este lo hizo casi todo ChatGPT, era muy tarde y estaba cansado 😅)](/prompts/metadata_refactor.md), aquí vi que podía manejar los metadatos de una forma más óptima para sacar provecho de lo que legalize-es me daba
- algunos prompts con el jaleo del trabajo se me pasó apuntarlos, como el del refactor del sistema de embeddings para pasar de cohere a ollama, pero en aidlc-docs está todo el proceso


### Adicionalmente usé Gemini para evaluaciones y mejoras de las respuestas del sistema, también ChatGPT para dudas, aclarar ideas y ayudas con la configuración de la VPS.


## Notas finales

### Entorno de producción
- [https://themia.cvbooster.es/](https://themia.cvbooster.es/) entorno bastante humilde.

### Limitaciones y mejoras futuras
- Todo esto lo hice entre el martes 19, miércoles 20 y un breve rato el jueves 21, con bastante agotamiento mental por compaginarlo con mi trabajo actual, por lo que hay varias cosas que mejoraría de la implementación actual:
    * la api key que autoriza al front como cliente lleva el valor en los environment.ts, eso quiere decir que subirá al repo, y se verá en el código a distribuir, es un problea de seguridad, se podría externalizar y cargar al inicio mediante una llamada http o similar.
    * verás que hay sitios donde pone "thermia" en lugar de "themia", error por ir rápido, no lo he corregido por no cargarme la trazabilidad del historial de git
    * versiones más actuales de las dependencias de backend, y mejor gestión de dependencias (poetry, uv o similar)
    * la gestión de los pdf no es la mejor, de hecho, es probable que de errores con los que tengan imágenes y detalles de más complejidad.
    * linters, formateadores, pre-commit hooks, etc para mejorar la calidad del código (ruff o similar para backend, prettier, eslint, husky para frontend)
    * modelos gratuitos, dan resultados pero no los mejores
    * refinar mucho más los límites de las respuestas, ahora mismo no tengo guards significativos para evitar ciertas respuesas (suicio, prompt injection, etc.) y seguramente no pase el OWASP TOP 10 para apps que integren LLMs [https://github.com/OWASP/www-project-top-10-for-large-language-model-applications/tree/main](https://github.com/OWASP/www-project-top-10-for-large-language-model-applications/tree/main).
    * he llevado esta aproximación de MVP a producción, aunque la máquina VPS la tenía de una poc que hice por mi cuenta, no era mi primera opción, por lo que el dominio no coincide más allá del subdominio, por la configuración que ya traía esta, la realidad es que el docker-compose.yaml no lo uso (Dockerfile si), y nginx.conf tampoco, uso una aproximación por subdominios diferente, hice un script en bash para back y front a modo de pipeline de despliegue dentro de la vps.
    * evaluaciones: me gustaría usar ragas o similar para evaluar la calidad de las respuestas, y así poder iterar con los prompts para mejorar la calidad de las mismas
    * observabilidad, tanto a nivel del modelo llm, como de logs del sistema, métricas, etc, podría usarse datadog, azure insights, aws cloudwatch, langsmith o cualquiera.
    * los datos tienen mucho potencial, se podría escalar bastante más, con un chatbot, orientarlo más hacia profesionales legales como herramienta de apoyo, infraestructura más escalable en la nube, etc.
    * mejor gestión del workspace o separación de back y front en diferentes repositorios.
    * no he cargado todas las leyes en la base de datos por tiempo de procesamiento, ya que mi capacidad de cómputo para el modelo de embeddings es bastante limitada y tardaría como 1 día completo en poder procesar todas las leyes 🥲 solo he cargado las nacionales (/es/) las autonómicas me las he saltado.


### archivos para probar

dejo en /test_files algunos PDFs de ejemplo para probar el sistema, aunque el sistema debería funcionar con cualquier PDF legal en español, teniendo en cuenta las limitaciones de imágenes, etc, también se puede usar ese enpdoint de /analyze/text para probar con texto plano sin necesidad de PDF, pensado para debugging. (requiere de autenticación con API key, se puede copiar la de (environment.prod.ts)[/thermia-front/src/environments/environment.prod.ts])

```
curl --request POST \
  --url https://themiabackend.cvbooster.es/analyze/text \
  --header 'Authorization: Bearer <API_KEY>' \
  --header 'Content-Type: application/json' \
  --data '{"text": "hola"}'
```

------------
## descripciones sobre como usar este repositorio
------------

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
.venv/bin/uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd thermia-front
npm install
npm start   # serves at http://localhost:4200
```

---

## Data ingestion

Run the ingestion pipeline to load documents into the vector store:

```bash
cd thermia-back
source .venv/bin/activate
python scripts/ingest.py --help        # show available options
python scripts/ingest.py               # ingest the full legal corpus
python scripts/ingest.py --reset       # truncate documents table then ingest
```

### Parallel ingestion

Use `--shard INDEX/TOTAL` to split the file list round-robin across N processes.
Each instance picks every N-th file starting at INDEX, so the work is evenly distributed
regardless of file ordering.

```bash
# In two separate terminals (run --reset separately first if needed):
python scripts/ingest.py --shard 0/2
python scripts/ingest.py --shard 1/2
```

Scale to more instances by increasing TOTAL:

```bash
python scripts/ingest.py --shard 0/4
python scripts/ingest.py --shard 1/4
python scripts/ingest.py --shard 2/4
python scripts/ingest.py --shard 3/4
```

> **Note:** `--reset` truncates the table and should only be run once before launching the shards.

### Tracking progress with `.indexed` and `.lock`

The ingestion script maintains a lightweight progress file inside the cloned corpus directory so repeated runs (or parallel shards) skip files that were already processed.

- Location: the script clones the corpus into a repo directory (default: `/tmp/legalize-es`). The progress file is written to `<repo_dir>/.indexed` and contains one relative path per line for files that completed upsert.
- Locking: the script uses a separate lock file (`<repo_dir>.lock`) and an exclusive `flock` while reading/writing `.indexed` so multiple instances can coordinate safely.
- When written: a file is appended to `.indexed` only after a successful `upsert_documents()` call for that file. If the upsert fails the path is not marked.

Commands to inspect or reset:

```bash
# show recent processed files
tail -n 50 /tmp/legalize-es/.indexed

# count processed files
wc -l /tmp/legalize-es/.indexed

# remove the progress file to force re-indexing of all files
rm /tmp/legalize-es/.indexed
```

If you prefer not to rely on `.indexed`, run `python scripts/ingest.py --reset` to truncate the `documents` table and re-ingest everything (use with caution).

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
| `thermia-front` | 4200 localhost, 443 prod env | Angular SPA served by nginx; proxies `/analyze` and `/health` to backend |
| `thermia-back` | 8000, 443 proxy reversed at prod env | FastAPI backend |
