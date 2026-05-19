# Unit Spec: `frontend`
**Run ID:** 2026-05-19t09-35-00z-thermia-mvp
**Layer:** 2 | **Dependencies:** `retrieval-api`

---

## Purpose
The Angular 21.2.0 single-view SPA that allows users to upload a PDF and receive a structured Spanish legal analysis. Styled entirely per DESIGN.md.

## Responsibilities
- Angular environment config for `apiUrl` and `apiKey`
- `AnalysisService`: HTTP `POST /analyze` with `FormData` + `Authorization: Bearer` header; typed response observable
- `AppComponent`: PDF file input (`.pdf` only), "Analizar" button (disabled until file selected), loading state, results renderer, error handler
- Results renderer: `resumen` (paragraph), `implicaciones_legales` (bulleted list), `fundamento_juridico` (citation list) — all labeled in Spanish
- Error display: styled block for 401, 422, 503, and network errors
- SCSS styling per DESIGN.md (colors, typography, spacing, components)
- Vitest unit tests for component state and service HTTP mock

## Public Interfaces
| Interface | Consumer | Description |
|---|---|---|
| `http://localhost:80` (Docker) | End user | Single-page app served by nginx |
| Angular `environment.ts` | `AnalysisService` | `apiUrl` + `apiKey` injected at build time |

**`AnalysisService.analyze(file: File): Observable<AnalysisResponse>`**

## Internal Dependencies
| Unit | What it consumes |
|---|---|
| `retrieval-api` | `POST /analyze` endpoint contract (URL, auth, request/response schema) |

## External Dependencies
| Package | Version (pinned) | Purpose |
|---|---|---|
| `@angular/core` | `^21.2.0` | Framework (already scaffolded) |
| `@angular/common/http` | `^21.2.0` | HTTP client |
| `@angular/forms` | `^21.2.0` | Reactive forms for file input |
| `vitest` | latest stable | Unit test runner |
| `@analogjs/vitest-angular` or `@angular/core/testing` | latest compatible | Angular test utilities for Vitest |

## Tasks
| Task | Description |
|---|---|
| FE-T1 | Angular environment config (`environment.ts` + `environment.prod.ts`) with `apiUrl` + `apiKey` |
| FE-T2 | `AnalysisService`: POST /analyze, FormData, Bearer header, typed `AnalysisResponse` observable |
| FE-T3 | `AppComponent`: PDF file input + "Analizar" button (disabled state logic) |
| FE-T4 | Loading state + results renderer (resumen, implicaciones, fundamento sections) |
| FE-T5 | Error state handler (401, 422, 503, network; Spanish messages; UI reset for retry) |
| FE-T6 | SCSS styling per DESIGN.md (color tokens, typography, spacing, responsive at 375px + 1280px) |
| FE-T7 | Vitest unit tests: `AppComponent` (file input + button state) + `AnalysisService` (HTTP mock) |

## Acceptance Criteria (rolled up)
- [ ] File input accepts only `.pdf`; rejects other types with UI feedback
- [ ] "Analizar" button disabled with no file; enabled once `.pdf` file selected
- [ ] Loading indicator visible while request is in flight
- [ ] `analysis.resumen` rendered as a paragraph with Spanish heading
- [ ] `analysis.implicaciones_legales` rendered as a bulleted list
- [ ] `analysis.fundamento_juridico` rendered as a citation list
- [ ] Each section has a visible Spanish label
- [ ] Spanish error message shown for out-of-scope, empty PDF, LLM unavailable, and auth errors
- [ ] UI returns to actionable state (button re-enabled) after error
- [ ] Colors, fonts, and spacing match DESIGN.md exactly
- [ ] Responsive layout works at 375px and 1280px viewport widths
- [ ] `apiKey` not hardcoded in committed source; read from `environment.ts`
- [ ] `vitest run` passes for component + service unit tests

## Definition of Done
- All tasks complete with green Vitest tests
- Manual browser test: upload a real Spanish legal PDF, observe full results render
- DESIGN.md compliance verified visually
- No `apiKey` value in committed files
