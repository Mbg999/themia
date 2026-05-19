# Unit Spec: `sources-display`
**Run:** `2026-05-19t20-50-00z-metadata-refactor`
**Layer:** 0 (no dependencies — reads from existing `metadata_` JSONB column)
**Status:** COMPLETE — all tasks already implemented

## Purpose
Surface the top retrieved source documents alongside the LLM analysis in the `/analyze` API response and Angular UI. Reads from the existing flat `metadata_` JSONB column — no dependency on the metadata refactor DB migrations.

## Responsibilities
- Append `fuentes[]` to the `/analyze` JSON response (backend `main.py`)
- Define `Fuente` TypeScript interface and extend `AnalysisResponse` (Angular service)
- Render "Fuentes Consultadas" card in the Angular UI — hidden when list is empty

## Public Interfaces
- **`POST /analyze` response** — now includes `fuentes: Fuente[]`:
  ```json
  {
    "resumen": "...",
    "implicaciones_legales": [...],
    "fundamento_juridico": [...],
    "fuentes": [
      {
        "law_id": "BOE-A-1835-2348",
        "law_title": "Real Orden de 30 de octubre de 1835...",
        "article": "Artículo 1",
        "section": "MINISTERIO DEL INTERIOR",
        "hierarchy_path": "BOE-A-1835-2348 > ..."
      }
    ]
  }
  ```
- **`Fuente` TypeScript interface** — exported from `analysis.service.ts` for consumption by the component template

## Internal Dependencies
None — reads from `doc.metadata_` which already exists. Does not depend on `db-schema-refactor` or `metadata-helpers`.

## External Dependencies
- pdfplumber, FastAPI, Angular — all already in use (no new dependencies)

## Tasks
| Task | Status | Description |
|---|---|---|
| SD-T1 | ✓ done | Add `fuentes` list comprehension to `main.py` `/analyze` handler |
| SD-T2 | ✓ done | Add `Fuente` interface + `fuentes: Fuente[]` to `AnalysisResponse` in `analysis.service.ts` |
| SD-T3 | ✓ done | Render "Fuentes Consultadas" card in `app.html` + styles in `app.scss` |

## Acceptance Criteria
- [x] `POST /analyze` response contains `fuentes` array (not null, empty list when no docs)
- [x] Each entry has `law_id`, `law_title`, `article`, `section`, `hierarchy_path` keys
- [x] Angular `AnalysisResponse.fuentes` typed as `Fuente[]`; TypeScript compiles without errors
- [x] "Fuentes Consultadas" card visible in the UI when `fuentes.length > 0`
- [x] Card hidden (not rendered) when `fuentes` is empty or absent
- [x] `law_title` shown as primary label; falls back to `law_id` when blank
- [x] `hierarchy_path` shown as secondary label only when non-empty

## Definition of Done
- [x] `thermia-back/app/main.py` — `fuentes` appended to result dict
- [x] `thermia-front/src/app/analysis.service.ts` — `Fuente` interface + `fuentes` on response type
- [x] `thermia-front/src/app/app.html` — "Fuentes Consultadas" card added
- [x] `thermia-front/src/app/app.scss` — `.source-list`, `.source-item`, `.source-title`, `.source-path` styles added
