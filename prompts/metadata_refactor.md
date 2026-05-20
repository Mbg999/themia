Metadata Refactor for Thermia Legal RAG
We need to improve the ingestion metadata model for Thermia.
Current metadata schema:
{
  "law_id": "",
  "law_title": "",
  "article": "",
  "section": "",
  "chunk_type": "article",
  "source_file": "",
  "jurisdiction": "ES",
  "year": 0,
  "hierarchy_path": ""
}
Current legal source repository:https://github.com/legalize-dev/legalize-es
The markdown files contain YAML/frontmatter metadata that should be leveraged during ingestion.

Goal
Refactor the ingestion pipeline metadata architecture to support a production-grade Spanish legal RAG system while still keeping the MVP simple.
We want:
* better legal retrieval quality
* better metadata filtering
* better legal grounding
* future-proofing for legal updates/versioning
* idempotent ingestion
* efficient PostgreSQL jsonb querying

Important Constraints
* Keep MVP-first philosophy
* Avoid overengineering
* Do NOT create complex domain-driven abstractions
* Keep ingestion pipeline readable and maintainable
* Everything must continue working locally with Docker
* Continue using PostgreSQL + pgvector
* Continue using SQLAlchemy
* Continue using FastAPI + LangChain architecture

Required Changes
1. Parse YAML/frontmatter metadata
Implement YAML/frontmatter extraction from the markdown files in legalize-es.
The parser must safely handle:
* missing fields
* malformed metadata
* unexpected formats

2. Split metadata into two layers
We want TWO metadata groups:
A) Retrieval Metadata
Small, filterable, indexed metadata used for:
* retrieval
* filtering
* ranking
* RRF
* future reranking
Recommended fields:
{
  "law_id": "",
  "law_title": "",
  "article": "",
  "section": "",
  "chunk_type": "article",
  "source_file": "",
  "jurisdiction": "ES",
  "year": 0,
  "hierarchy_path": "",
  "legal_rank": "",
  "status": "",
  "eli": "",
  "official_date": "",
  "version_date": "",
  "language": "es",
  "content_hash": ""
}

B) Source Metadata
Additional informational metadata from the YAML/frontmatter.
Examples:
* official publication references
* BOE identifiers
* URLs
* ministry/department
* publication details
This metadata is informative only and should NOT be heavily used in retrieval filtering.

3. Add content hashing
Implement deterministic content hashing for each article/subchunk.
Requirements:
* stable across re-runs
* changes if article content changes
* used to avoid unnecessary re-embedding in future iterations
Recommended:
* SHA256 hash
* based on normalized article content
Store hash inside retrieval metadata.

4. Improve legal awareness
Implement support for legal hierarchy awareness.
Examples:
* Constitución
* Ley Orgánica
* Ley
* Real Decreto
* Orden Ministerial
Extract/store:
* legal_rank
This will later be used for:
* retrieval ranking
* weighting
* explainability

5. Add legal status support
Extract/store legal status if available:
* vigente
* derogada
* parcialmente vigente
This is critical for avoiding retrieval of obsolete legal norms.

6. Preserve clean architecture
Do NOT:
* overabstract
* create unnecessary services
* create excessive inheritance
* create enterprise patterns
Keep:
* simple functions
* clear pipeline stages
* readable ingestion flow

7. Database Considerations
We are using:
* PostgreSQL
* pgvector
* SQLAlchemy
Please propose:
* whether retrieval metadata should remain inside jsonb
* whether some fields should become indexed relational columns
* what indexes should exist for hybrid retrieval
We care about:
* metadata filtering performance
* vector search performance
* future scalability

8. Important Retrieval Context
Future retrieval flow:
QUERY
↓
Metadata filtering
↓
Vector search (pgvector)
↓
BM25 search (tsvector)
↓
RRF fusion
↓
Optional reranking
↓
LLM
The metadata model should support this cleanly.

9. Deliverables
Please implement:
* updated metadata parsing
* YAML/frontmatter extraction
* improved chunk metadata generation
* content hashing
* legal rank extraction
* status extraction
* any required SQLAlchemy model changes
* migration updates if needed
* recommended PostgreSQL indexes
* comments/docstrings in English
Also explain:
* architectural decisions
* tradeoffs
* why certain fields should or should not be indexed
Keep the implementation pragmatic and MVP-oriented.

Example .md file https://github.com/legalize-dev/legalize-es/blob/main/es/BOE-A-1835-2348.md?plain=1---
title: "Real Orden de 30 de octubre de 1835 acerca del lugar en que han de enterrarse las religiosas"
identifier: "BOE-A-1835-2348"
country: "es"
rank: "orden"
publication_date: "1835-11-07"
last_updated: "1835-11-07"
status: "in_force"
source: "https://www.boe.es/buscar/act.php?id=BOE-A-1835-2348"
department: "Ministerio del Interior"
pdf_url: "https://www.boe.es/datos/pdfs/BOE/1835/316/A01254-01254.pdf"
subjects: ["Cementerios", "Defunciones", "Iglesia Católica", "Policía sanitaria mortuoria"]
department_code: "7320"
rank_code: "1350"
ambito_code: "1"
enactment_date: "1835-10-30"
official_journal: "Gaceta de Madrid"
journal_issue: "316"
consolidation_status: "Finalizado"
scope: "Estatal"
url_html_consolidada: "https://www.boe.es/buscar/act.php?id=BOE-A-1835-2348"
url_pdf: "https://www.boe.es/datos/pdfs/BOE/1835/316/A01254-01254.pdf"
page_start: "1254"
page_end: "1254"
image_marker: "A"
legislative_status: "L"
---
# Real Orden de 30 de octubre de 1835 acerca del lugar en que han de enterrarse las religiosas

### MINISTERIO DE LO INTERIOR

### *Real Orden*

He dado cuenta a S M. la Reina Gobernadora del expediente promovido por la priora y comunidad de religiosas de santo Domingo del Valle de Flores, extramuros de la villa de Vivero, provincia de Lugo, solicitando se las mantenga en posesión de la gracia que les está concedida de ser enterradas en sus conventos, y de lo que expone el gobernador civil de dicha provincia, proponiendo se derogue la Real cédula de 10 de Mayo de 1818, por la que se concedió aquel privilegio a todos los cadáveres de las religiosas profesas; y habiendo tenido a bien S. M. oir al Consejo Real de España e Indias, se ha servido mandar, conformándose con su dictámen, que continúe llevándose a efecto lo prevenido en la citada Real Cédula bajo las reglas siguientes:

1.ª Que hayan de sepultarse los cadáveres de las religiosas precisamente en los atrios o huertos de los monasterios o conventos, señalándose en ellos para este destino un paraje, con prohibición de que pueda hacerse en los coros bajos y en las iglesias.

2.ª Que los gobernadores civiles reconozcan los huertos y atrios asegurándose de su ventilación y demas requisitos necesarios antes de prestar su aprobación para la inhumación en ellos.

3.ª Que los cadáveres de las religiosas que fallecieren en monasterios o conventos en que no haya huerto o atrio ventilado donde sepultarlos, se conduzcan a los cementerios públicos, en los cuales se demarcará el lugar que pareciese mas a propósito.

4.ª Que los gobernadores civiles, asociados de un regidor y del síndico procurador general, reconozcan todos los monasterios y conventos de religiosas de las capitales para asegurarse de la existencia en ellos de huertos o lugares proporcionados para el enterramiento, prohibiendo desde luego que éste se verifique en otra parte.

Y 5.ª Que en los pueblos subalternos de la capital den comisión los gobernadores civiles al sujeto que tuvieren por oportuno para que en unión con un regidor y el síndico procurador general ejecute la visita con el objeto indicado.

De Real Orden lo comunico a V. para su inteligencia y cumplimiento.

Dios guarde a V. muchos años.

Madrid 30 de Octubre de 1835.

**Martin de los Heros.**