# Projection Library — Pilot v1.1

Sistema di proiezione finanziaria integrata P&L + SP + CF, registry-driven, multi-settore.

## Stato

Pilot v1.1. Specification freeze. Build pronto da iniziare.

## Cosa fa

Carica un bilancio gestionale di un'azienda (1+ anni storici), riconosce le voci, calcola KPI storici, propone metodi di proiezione, raccoglie assumption forward-looking, esegue piano integrato P&L + SP + CF su orizzonte Y1-Y3, presenta output con dashboard real-time-ish (refresh on demand) e permette iterazione con override layer.

## Cosa non fa (out of scope pilot v1.1)

- M&A engine (PPA, goodwill, consolidation)
- Carve-out / spin-off
- Multi-perimetro (consolidato + subsidiaries simultaneamente)
- Multi-currency
- Tax module avanzato (transfer pricing, group taxation, regime speciali oltre NOL)
- Lease-by-lease schedule
- Granularità monthly/quarterly
- Scenario engine (multi-scenario paralleli)
- Sensitivity analysis nativa
- Strumenti finanziari complessi (derivati, hedge, convertibles)
- RCF plug automatico
- Industry-specific accounting (IFRS 17 insurance, IFRS 6 mining, IAS 41 agriculture)

Vedi `09_exclusions_roadmap.md` o sheet `09_exclusions_roadmap` dell'Excel di riferimento.

## Tech stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy, Alembic
- **Engine**: pandas, numpy, openpyxl
- **Persistence**: SQLite (pilot), upgrade path a PostgreSQL
- **Frontend**: React 18+, TypeScript, Tailwind CSS, shadcn/ui, recharts, TanStack Table, axios + react-query
- **Registry**: YAML files
- **Testing**: pytest (backend), vitest + react-testing-library (frontend), Playwright (e2e)

## Reference materials

Documenti di specifica già prodotti, da tenere come fonte di verità durante il build:

1. **`Projection_Library_Spec_v1.1.xlsx`** (Operational Reference) — 11 sheet:
   - `00_index` — indice navigabile + glossario
   - `01_methods` — method_registry (metodi di proiezione + derived rules)
   - `02_voices` — voice_registry (voci modello P&L + SP + CF)
   - `03_kpis` — kpi_registry (KPI catalogati)
   - `04_dependencies` — engine execution order, 11 fasi, circolarità
   - `05_validation` — validation_rules
   - `06_tier_matrix` — TIER 0-4 + sub-tier method-specific
   - `07_sector_packs` — pack settoriali + generic
   - `08_approximations` — approximation log
   - `09_exclusions_roadmap` — pilot exclusions + improvement roadmap
   - `10_decisions_log` — decision log

> **Nota sui count**: i numeri esatti (voci, metodi, KPI, regole) vivono nei registry YAML che saranno generati in Step 2. **La fonte di verità unica è il registry**, non i docs descrittivi. I conteggi precisi saranno fissati al termine dello script di estrazione + audit di riconciliazione (vedi `BUILD_PLAN.md` Milestone 1).

2. **Documenti di flow** in `flows/` — file markdown che descrivono il flusso utente operativo step-by-step:
   - `00_setup.md` — configurazione iniziale progetto
   - `01_data_intake.md` — caricamento bilancio
   - `02_mapping.md` — mapping voci utente → voice_registry
   - `03_validation_historical.md` — validazione + KPI storici
   - `04_method_selection.md` — selezione metodi (guided/expert/ambition)
   - `05_driver_intake.md` — caricamento driver TIER 2-4
   - `06_assumption_compilation.md` — compilazione assumption Y1-Y3
   - `07_engine_execution.md` — engine execution E0-E8
   - `08_output_presentation.md` — dashboard output
   - `09_iteration.md` — iteration paths + override layer
   - `10_quality_score.md` — quality score
   - `11_override_policy_matrix.md` — matrice policy override per voice category

3. **Architettura sistema** in `ARCHITECTURE.md` — module map, layering, dataflow, schema DB (incluso `snapshot_values` normalizzato), pattern override come overlay layer

4. **Build plan** in `BUILD_PLAN.md` — ordering del build, milestone (M0-M14), acceptance criteria per milestone, tempistiche con buffer

## Documenti correlati ancora da produrre (Step 2 — Milestone 1 in BUILD_PLAN)

Step 2 è una milestone tecnica corposa (3-5 settimane), da svolgere in Claude Code prima di iniziare l'implementazione del backend. Comprende:

- **`data_contracts/registries/*.schema.json`** — 8 JSON Schema formali per ogni registry
- **`registries/*.yaml`** — 6 registry YAML estratti da Excel + validati contro schemi:
  - `voice_registry.yaml`, `method_registry.yaml`, `kpi_registry.yaml`
  - `validation_rules.yaml`, `derived_rules.yaml`
  - `sector_packs/{generic,industrial,saas,retail,real_estate,services}.yaml`
- **`registries/voice_dependencies.yaml`** — DAG voce-per-voce, generato via parsing AST formula_python
- **`registries/override_policy.yaml`** — matrice policy come da `flows/11_override_policy_matrix.md`
- **`registries/required_data_matrix.yaml`** — derivata da voice × method × tier × sector
- **`registries/test_cases.yaml`** — test end-to-end collegati a sample dataset
- **`sample_data/*.xlsx`** — 5-6 dataset Excel realistici per testing
- **Audit count Excel** — script + report di riconciliazione conteggi voce/KPI/methods/rules

Vedi `BUILD_PLAN.md` Milestone 1 per dettaglio sub-milestone (M1.0 → M1.8).

## Convenzioni

- **Lingua**: documentazione tecnica in italiano. Codice in inglese (variabili, funzioni, commenti).
- **Naming voce_id**: `{statement}.{section}.{group}.{voice}` (lowercase, dot notation), es. `pl.rev.gross.product_sales`
- **Naming method_id**: `lowercase_underscore` parlante, es. `pct_net_revenue`
- **Technical code metodo**: `M_XXX_NNN`, es. `M_RAT_001`
- **Sign convention**: IFRS Alternativa B (ricavi+, costi-, asset+, liability-)
- **Currency pilot**: EUR
- **Standard contabile pilot**: IFRS

## Come usare questo repo con Claude Code

1. Apri Claude Code in questa directory
2. Fagli leggere `BUILD_PLAN.md` come primo input
3. Procedi milestone per milestone come definito nel build plan
4. L'Excel `Projection_Library_Spec_v1.1.xlsx` deve essere accessibile come reference (mettilo nella root o in `/reference/`)
5. Quando emergono decisioni architetturali nuove, registrale in `10_decisions_log.md` (estensione del decisions log esistente)
