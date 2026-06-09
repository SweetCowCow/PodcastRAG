# rag-service-layout Specification

## Purpose

定義 RAG service（`backend/app/services/`）的模組職責邊界與 facade 契約：`rag.py` 作為 re-export facade 維持外部 `rag.X` 介面穩定，六個子模組（`rag_types` / `rag_config` / `rag_sql` / `rag_retrieval` / `rag_enrich` / `rag_generation`）各司單一職責，依賴方向分層且無循環。此為維護性架構不變式，約束未來對 RAG service 的所有改動。

## Requirements

### Requirement: RAG service is organized into single-responsibility modules

The RAG service SHALL be split across single-responsibility modules under `backend/app/services/`, each owning exactly one concern: `rag_types` (shared data structures `ChunkHit` and `MetadataFilters`), `rag_config` (environment-flag parsing, runtime caches, and public tuning constants), `rag_sql` (SQL fragment builders including `_build_ts_query` and SQL template strings), `rag_retrieval` (`retrieve`, `retrieve_descriptions`, `retrieve_titles`, `route_episodes`, `retrieve_hybrid`), `rag_enrich` (`enrich_hits` and the `_fetch_*` helpers), and `rag_generation` (`answer_with_chunks`, `rewrite_question`, enumeration formatting, and JSON-repair helpers). New RAG logic SHALL be added to the module matching its concern, and SHALL NOT be added to the `rag.py` facade.

#### Scenario: Lexical query building lives in the SQL module

- **WHEN** a developer needs to modify how the Postgres text query is constructed (for example, future BM25 work)
- **THEN** `_build_ts_query` and the SQL template strings are located in `rag_sql`
- **AND** the change does not require editing `rag_retrieval`, `rag_enrich`, or the `rag.py` facade unless the call contract itself changes

#### Scenario: New generation helper added to the correct module

- **WHEN** a developer adds a new LLM-answer post-processing helper
- **THEN** the helper is placed in `rag_generation`
- **AND** it is not placed in the `rag.py` facade


<!-- @trace
source: rag-py-module-split
updated: 2026-06-09
code:
  - backend/app/services/rag.py
  - backend/app/services/rag_types.py
  - backend/app/services/rag_config.py
  - backend/app/services/rag_sql.py
  - backend/app/services/rag_retrieval.py
  - backend/app/services/rag_enrich.py
  - backend/app/services/rag_generation.py
-->

---
### Requirement: rag.py is a facade that preserves the external interface

`rag.py` SHALL re-export the public symbols of the six submodules so that every existing `rag.<symbol>` attribute access and every `from app.services.rag import <symbol>` import continues to resolve unchanged. The facade SHALL NOT contain business logic. Each submodule SHALL declare an explicit `__all__` to bound what the facade re-exports.

#### Scenario: Existing module-attribute access keeps working

- **WHEN** a caller accesses `rag.retrieve_hybrid`, `rag.enrich_hits`, `rag.answer_with_chunks`, `rag._build_ts_query`, `rag.ChunkHit`, or `rag.MetadataFilters`
- **THEN** the symbol resolves through the facade to the implementation in its owning submodule
- **AND** the observable behavior is identical to the pre-refactor implementation

#### Scenario: Existing symbol import keeps working

- **WHEN** `app/api/query.py` runs `from app.services.rag import ChunkHit as RagHit, MetadataFilters`
- **THEN** the import succeeds against the facade
- **AND** no importer of the RAG service needs to change its import statements


<!-- @trace
source: rag-py-module-split
updated: 2026-06-09
code:
  - backend/app/services/rag.py
  - backend/app/services/rag_types.py
  - backend/app/services/rag_config.py
  - backend/app/services/rag_sql.py
  - backend/app/services/rag_retrieval.py
  - backend/app/services/rag_enrich.py
  - backend/app/services/rag_generation.py
-->

---
### Requirement: Module dependency direction is acyclic

The RAG submodules SHALL depend in one direction only, from lower to higher layers: `rag_types` (lowest, depending on no other RAG submodule), then `rag_config`, then `rag_sql`, then `rag_retrieval` and `rag_enrich`, then `rag_generation`, with `rag.py` re-exporting all of them at the top. No submodule SHALL introduce a circular import.

#### Scenario: Shared data structures sit at the bottom

- **WHEN** `rag_retrieval`, `rag_enrich`, and `rag_generation` each need `ChunkHit`
- **THEN** they import it from `rag_types`
- **AND** `rag_types` imports no other RAG submodule, so no import cycle is formed

#### Scenario: Importing the service does not raise

- **WHEN** `from app.services import rag` is executed
- **THEN** the import completes without an ImportError or circular-import error


<!-- @trace
source: rag-py-module-split
updated: 2026-06-09
code:
  - backend/app/services/rag.py
  - backend/app/services/rag_types.py
  - backend/app/services/rag_config.py
  - backend/app/services/rag_sql.py
  - backend/app/services/rag_retrieval.py
  - backend/app/services/rag_enrich.py
  - backend/app/services/rag_generation.py
-->

---
### Requirement: RRF_WEIGHTS remains a single mutable object

`RRF_WEIGHTS` SHALL be defined once in `rag_config` and shared by reference, so that runtime in-place mutation (for example `app/api/admin/rrf_sweep.py` calling `clear()` and `update()` on `rag.RRF_WEIGHTS`) is visible to the retrieval code that reads the weights. No submodule or the facade SHALL rebind the `RRF_WEIGHTS` name to a new object.

#### Scenario: Admin sweep mutation is visible to retrieval

- **WHEN** the admin RRF sweep performs an in-place `update()` on `rag.RRF_WEIGHTS`
- **THEN** retrieval reading the weights observes the mutated values
- **AND** after the sweep restores the original mapping in place, retrieval observes the original values again

<!-- @trace
source: rag-py-module-split
updated: 2026-06-09
code:
  - backend/app/services/rag.py
  - backend/app/services/rag_types.py
  - backend/app/services/rag_config.py
  - backend/app/services/rag_sql.py
  - backend/app/services/rag_retrieval.py
  - backend/app/services/rag_enrich.py
  - backend/app/services/rag_generation.py
-->