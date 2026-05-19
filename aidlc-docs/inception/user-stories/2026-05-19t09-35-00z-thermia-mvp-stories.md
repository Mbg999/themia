# Thermia — User Stories
**Run ID:** 2026-05-19t09-35-00z-thermia-mvp

---

## US-1: Analyze a legal PDF

**As** Ana (tenant, non-expert),
**I want** to upload a PDF document and click "Analizar",
**So that** I receive a plain-Spanish summary of the legal implications and the exact legal articles that apply.

### Acceptance Criteria
- [ ] AC-US1-1: A PDF file input is visible and accepts only `.pdf` files.
- [ ] AC-US1-2: The "Analizar" button is disabled until a file is selected.
- [ ] AC-US1-3: After clicking "Analizar", a loading indicator is shown while the request is in flight.
- [ ] AC-US1-4: The response displays `analysis.resumen`, `analysis.implicaciones_legales`, and `analysis.fundamento_juridico` in clearly labelled sections in Spanish.
- [ ] AC-US1-5: The cited legal articles reference real Spanish law (e.g. "Art. 9 Ley 29/1994").

---

## US-2: Understand what a contract clause means

**As** Carlos (self-employed, medium legal literacy),
**I want** to receive a list of legal implications extracted from my contract,
**So that** I can decide whether to involve a lawyer or proceed directly.

### Acceptance Criteria
- [ ] AC-US2-1: `analysis.implicaciones_legales` is a non-empty list of bullet points, each describing one concrete legal consequence.
- [ ] AC-US2-2: `analysis.fundamento_juridico` cites the specific article(s) that back each implication.
- [ ] AC-US2-3: All output text is in Spanish.

---

## US-3: Know when my document is outside the system's scope

**As** any user,
**I want** the system to tell me clearly when my document cannot be analyzed,
**So that** I don't assume the system is broken and I know to seek other help.

### Acceptance Criteria
- [ ] AC-US3-1: Uploading an empty PDF (no extractable text) shows a Spanish error message in the frontend.
- [ ] AC-US3-2: Uploading a non-legal document (e.g. a recipe) shows the same out-of-scope Spanish error message.
- [ ] AC-US3-3: The error message does not show a raw HTTP error or stack trace.

---

## US-4: Handle service unavailability gracefully

**As** any user,
**I want** to see a user-friendly Spanish message when the analysis service is temporarily unavailable,
**So that** I understand the issue is temporary and know to try again.

### Acceptance Criteria
- [ ] AC-US4-1: When the LLM returns an error, the frontend displays the Spanish "servicio no disponible" message.
- [ ] AC-US4-2: The UI returns to a state where the user can try again (button re-enabled).

---

## US-5: Run the legal corpus ingestion

**As** a system operator (developer running locally),
**I want** to execute the ingestion script once to populate the database from the legalize-es corpus,
**So that** the retrieval pipeline has data to search against.

### Acceptance Criteria
- [ ] AC-US5-1: `python3 scripts/ingest.py` completes without error and prints progress.
- [ ] AC-US5-2: Running the script a second time produces the same final row count (idempotent upsert).
- [ ] AC-US5-3: Running with `--reset` truncates and re-ingests everything.
