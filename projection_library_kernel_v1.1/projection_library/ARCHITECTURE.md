# Architettura — Pilot v1.1

## Layering

Architettura a 4 layer con separazione netta di responsabilità.

```
┌──────────────────────────────────────────────────────────────┐
│                    LAYER 1 — UI                              │
│   React SPA: dashboard, sidebar assumption, override panel  │
│   Componenti: AG Grid o TanStack Table per tabelle FS,     │
│   recharts per grafici, shadcn/ui per controlli            │
└──────────────────────────────────────────────────────────────┘
                              │
                         REST + JSON
                              │
┌──────────────────────────────────────────────────────────────┐
│                    LAYER 2 — API                             │
│   FastAPI routes, request validation (Pydantic),            │
│   auth (single-user pilot, no auth in v1.1),               │
│   serialization, error handling                             │
└──────────────────────────────────────────────────────────────┘
                              │
                       Service calls
                              │
┌──────────────────────────────────────────────────────────────┐
│                    LAYER 3 — DOMAIN (Engine)                 │
│   Business logic: parsing bilancio, mapping, KPI calc,     │
│   engine 11 fasi, validation, override resolution,         │
│   quality score                                             │
└──────────────────────────────────────────────────────────────┘
                              │
                       Repository pattern
                              │
┌──────────────────────────────────────────────────────────────┐
│                    LAYER 4 — PERSISTENCE                     │
│   SQLAlchemy ORM + SQLite, registry YAML loader,           │
│   file storage per upload bilanci                           │
└──────────────────────────────────────────────────────────────┘
```

## Module map

```
backend/
├── api/                            # Layer 2 — API
│   ├── __init__.py
│   ├── main.py                     # FastAPI app entry
│   ├── routes/
│   │   ├── projects.py             # CRUD progetti
│   │   ├── intake.py               # upload bilancio
│   │   ├── mapping.py              # mapping voci
│   │   ├── methods.py              # selezione metodi
│   │   ├── drivers.py              # caricamento driver TIER 2-4
│   │   ├── assumptions.py          # compilazione assumption
│   │   ├── execution.py            # run engine
│   │   ├── output.py               # FS proiettati, KPI, validation
│   │   └── override.py             # override layer
│   └── schemas/                    # Pydantic models per request/response
│       └── ...
│
├── domain/                         # Layer 3 — Engine
│   ├── __init__.py
│   ├── intake/
│   │   ├── parser.py               # parser bilancio Excel/CSV
│   │   ├── mapper.py               # mapping voci utente → voice_id
│   │   └── validator_historical.py # validazione storico (DI_001-014)
│   ├── kpi/
│   │   ├── calculator.py           # calcolo KPI storici
│   │   └── aggregator.py           # default aggregation logic
│   ├── methods/
│   │   ├── selector.py             # method selection (guided/expert)
│   │   ├── catalog.py              # accesso method_registry
│   │   └── compatibility.py        # check method × voice × dati
│   ├── engine/
│   │   ├── executor.py             # year loop, fase orchestration
│   │   ├── phases/
│   │   │   ├── e0_setup.py
│   │   │   ├── e1_pl_driver.py
│   │   │   ├── e2_fa_da.py
│   │   │   ├── e3_nwc.py
│   │   │   ├── e3_1_ifrs15.py
│   │   │   ├── e4_nfp.py
│   │   │   ├── e5_provisions_eb.py
│   │   │   ├── e6_tax_def_equity.py
│   │   │   ├── e7_pl_bottom.py
│   │   │   ├── e7_5_cit_nwc.py
│   │   │   └── e8_cf_close.py
│   │   ├── formulas.py             # evaluator formula_expression Python
│   │   ├── derived_rules.py        # 19 derived rules
│   │   └── dependency_graph.py     # ordering intra-fase
│   ├── validation/
│   │   ├── runner.py               # esecuzione 73 regole
│   │   ├── rules/
│   │   │   ├── data_integrity.py   # DI_001-014
│   │   │   ├── accounting_identity.py # AI_001-011
│   │   │   ├── sign_consistency.py # SC_001-009
│   │   │   ├── range_plausibility.py  # RP_001-022
│   │   │   ├── cross_period.py     # CP_001-008
│   │   │   ├── configuration.py    # CF_001-006
│   │   │   └── calculation_quality.py # CQ_001-003
│   │   └── reporter.py             # generazione validation report
│   ├── override/
│   │   ├── resolver.py             # applicazione override + propagazione
│   │   ├── policy.py               # propagation policy (organic/one_shot)
│   │   └── store.py                # lista override persistenti
│   ├── quality/
│   │   └── scorer.py               # quality score calc + sub-score
│   └── sector_packs/
│       └── applier.py              # apply_sector_pack logic
│
├── infrastructure/                 # Layer 4 — Persistence
│   ├── db/
│   │   ├── models.py               # SQLAlchemy ORM
│   │   ├── repositories.py         # CRUD repositories
│   │   └── migrations/             # Alembic
│   ├── registry/
│   │   ├── loader.py               # carica YAML registry
│   │   └── cache.py                # in-memory cache
│   └── storage/
│       └── files.py                # filesystem storage upload
│
├── tests/
│   ├── unit/                       # test moduli
│   ├── integration/                # test engine end-to-end
│   └── acceptance/                 # test acceptance criteria flow
│
└── pyproject.toml

frontend/
├── src/
│   ├── api/                        # client API generato da OpenAPI
│   ├── components/
│   │   ├── dashboard/              # widget centrali (P&L, SP, CF, KPI)
│   │   ├── sidebar/                # assumption box espandibili
│   │   ├── override/               # override panel
│   │   ├── intake/                 # upload + mapping wizard
│   │   ├── methods/                # method selection (guided/expert)
│   │   └── ui/                     # shadcn/ui copied components
│   ├── hooks/                      # custom React hooks
│   ├── stores/                     # Zustand store (state management)
│   ├── types/                      # TypeScript types (mirror Pydantic)
│   └── App.tsx
└── package.json

registries/                         # condiviso, root del repo
├── method_registry.yaml
├── voice_registry.yaml
├── kpi_registry.yaml
├── validation_rules.yaml
├── derived_rules.yaml
└── sector_packs/
    ├── industrial.yaml
    ├── saas.yaml
    ├── retail.yaml
    ├── real_estate.yaml
    └── services.yaml
```

## Dataflow

### Flusso principale (happy path)

```
1. Utente crea progetto
   └─→ POST /projects → projects.create() → DB.insert(Project)

2. Utente carica bilancio
   └─→ POST /projects/{id}/balance → intake.parse() → DB.insert(Balance)
   └─→ ritorna lista voci utente

3. Sistema suggerisce mapping
   └─→ POST /projects/{id}/mapping/suggest → mapper.auto_suggest()
   └─→ ritorna dict[voce_utente, suggested_voice_id, confidence]

4. Utente conferma/modifica mapping
   └─→ POST /projects/{id}/mapping → mapping.save() → DB.insert(Mapping)

5. Sistema valida bilancio storico
   └─→ POST /projects/{id}/validate-historical → validator_historical.run()
   └─→ ritorna lista issue (block/error/warning)
   └─→ se BLOCK presente, non si procede

6. Sistema calcola KPI storici
   └─→ POST /projects/{id}/kpi-historical → kpi.calculator.run()
   └─→ DB.insert(HistoricalKPIs)

7. Sistema calcola quality score
   └─→ POST /projects/{id}/quality-score → quality.scorer.compute()
   └─→ ritorna score 0-100 + sub-scores

8. Utente sceglie metodi (guided/expert/sector pack)
   └─→ POST /projects/{id}/method-selection → methods.selector.apply()
   └─→ DB.insert(MethodConfig per voce)
   └─→ ritorna lista driver TIER 2/3/4 richiesti

9. Utente carica driver storici aggiuntivi
   └─→ POST /projects/{id}/drivers → drivers.upload()
   └─→ DB.insert(Driver)

10. Sistema pre-popola assumption con default
    └─→ POST /projects/{id}/assumptions/defaults → assumption.populate_defaults()
    └─→ DB.insert(Assumption Y1-Y3 con default da KPI)

11. Utente modifica assumption (UI)
    └─→ PATCH /projects/{id}/assumptions/{voice}/{year}
    └─→ DB.update(Assumption)

12. Utente lancia engine
    └─→ POST /projects/{id}/run → engine.executor.run()
    └─→ esegue E0-E8 per ogni anno Y1-Y3
    └─→ DB.insert(Snapshot output)

13. Sistema valida output
    └─→ validation.runner.run_all()
    └─→ DB.insert(ValidationReport)

14. UI mostra dashboard
    └─→ GET /projects/{id}/output → ritorna FS + KPI + validation report

15. (opzionale) Utente fa override
    └─→ POST /projects/{id}/overrides → override.store.add()
    └─→ trigger automatico re-run
    └─→ DB.update(Snapshot)

16. (opzionale) Utente modifica assumption / metodo
    └─→ stesso pattern, re-run engine
```

### Re-run policy

Re-run è **deferred** (utente preme tasto "Refresh"). Non auto-trigger su ogni modifica. Eccezione: dopo ogni override l'engine ricalcola automaticamente perché override richiede propagazione.

Tempo target re-run: <2 secondi per piano TIER 2 standard.

## Persistence — schema dati

### Tabelle SQLite principali

```sql
projects
  id, name, sector_pack, perimeter, currency, country,
  horizon_years, tier_level, created_at, updated_at

balances
  id, project_id, year, source_type (gestionale|civilistico|both),
  raw_data (JSON), uploaded_at

raw_voices
  id, balance_id, voice_user_label, voice_user_section,
  amount, year

mappings
  id, project_id, voice_user_label, voice_id_system,
  confidence (0-1), confirmed_by_user (bool)

historical_kpis
  id, project_id, kpi_id, year, value

quality_scores
  id, project_id, score_total, score_history,
  score_completeness, score_consistency, score_method_calibration,
  computed_at

method_configs
  id, project_id, voice_id, method_id, method_technical_code,
  is_default (bool)

drivers
  id, project_id, driver_id, year, value

assumptions
  id, project_id, voice_id, year, value,
  source (default_kpi|user_input)

snapshots
  id, project_id, run_timestamp, status,
  pl_data (JSON), sp_data (JSON), cf_data (JSON),
  projected_kpis (JSON), validation_report (JSON),
  approximation_log (JSON)

snapshot_values   -- normalizzata, per audit/debug/comparison/export
  id, snapshot_id, voice_id, year, value,
  source_type,             -- 'historical' | 'method_output' | 'override_adjusted' | 'derived_identity'
  method_id NULL,
  formula_rule_id NULL,
  base_value NULL,         -- valore pre-override
  override_delta NULL,     -- somma delta override applicati
  is_override_adjusted BOOL,
  INDEX (snapshot_id, voice_id, year)

overrides
  id, project_id, voice_id, year, delta_amount,
  nature (organic|one_shot),
  override_policy_class,   -- chiave in override_policy.yaml
  is_active (bool),
  created_at, deactivated_at
```

**Sui due storage di snapshot**: il JSON resta per ricostruzione veloce della dashboard (single query → tutto lo snapshot). La tabella normalizzata `snapshot_values` si popola in scrittura insieme al JSON e abilita:
- audit trail per singola voce
- comparison snapshot ↔ snapshot
- debug granulare di propagazione override
- export Excel
- query SQL ad-hoc (es. "tutte le voci con override delta > X")

Costo extra in scrittura: ~150-200ms per ~600 record (200 voci × 3 anni). Accettabile.

## Registry loading

I registry YAML sono caricati all'avvio del backend e cached in memoria. Refresh manuale via endpoint admin (utile in dev). Strutture:

- `MethodRegistry`: dict[method_id → MethodSpec] + dict[technical_code → method_id]
- `VoiceRegistry`: dict[voice_id → VoiceSpec], grafo dipendenze pre-computato
- `KPIRegistry`: dict[kpi_id → KPISpec]
- `ValidationRules`: list[Rule] partizionata per fase di trigger
- `DerivedRules`: dict[derived_rule_id → DerivedRuleSpec]
- `SectorPacks`: dict[pack_id → SectorPackSpec]

## Engine execution — invariants

Per garantire correttezza, l'engine rispetta queste invariant:

1. **Ogni fase E0-E8 è puramente funzionale**: input = stato modello pre-fase, output = stato modello post-fase. No side effect su DB durante run (solo a fine run).
2. **Year loop sequenziale**: Y1 finito completamente prima di iniziare Y2.
3. **Validation runs after each phase**: regole con trigger_phase = E_X eseguite dopo E_X, non in parallelo.
4. **Snapshot atomico**: o tutto il run completa con successo, o lo snapshot non viene scritto (rollback DB transaction).
5. **No circular dependency runtime**: il dependency graph è validato all'avvio (DI_009, DI_010).
6. **Formula evaluation safe**: formula Python valutate in namespace controllato, no `eval()` libero.
7. **Override come overlay, non rerun**: gli override non triggerano re-esecuzione delle fasi engine. L'engine produce `base_value` puro per ogni voce, e gli override entrano come overlay layer applicato durante la risoluzione delle dipendenze. Vedi sezione "Override layer pattern" sotto.

## Override layer pattern

L'engine NON fa "rerun from phase X" quando un override viene applicato. Il pattern è single-pass con effective value resolution:

```python
def resolve_voice_value(voice_id: str, year: str, state: ModelState) -> float:
    """
    Single source of truth per ottenere il valore di una voce.
    Tutti i metodi/derived rules/CF identity passano da qui.
    """
    base_value = state.base_values[voice_id][year]
    
    # Apply active overrides as overlay
    delta = sum(
        ov.delta_amount
        for ov in state.overrides
        if ov.voice_id == voice_id
        and ov.year == year
        and ov.is_active
    )
    
    return base_value + delta
```

Questa funzione è chiamata da:
- Tutte le formule dei metodi (input resolution)
- Derived rules
- Validation rules
- CF identity per cash close
- Output presentation

**Conseguenza**: quando l'utente aggiunge un override, sistema esegue:
1. Il base_value rimane invariato (non ri-eseguo l'engine)
2. Override salvato in tabella `overrides`
3. Re-run di un singolo step "propagation": ricalcolo voci derived/dependent del voice_id overridden, applicando effective values via resolve_voice_value
4. Cash si auto-aggiusta via CF identity (anche cash usa resolve_voice_value)
5. Snapshot aggiornato: `snapshot_values.base_value` invariato, `override_delta` aggiornato, `value = base + delta`

**Vantaggi**:
- Single-pass, no rerun engine completo
- Audit trail pulito (`base_value` e `override_delta` separati nel DB)
- Idempotenza: aggiungere/rimuovere override è reversibile senza ricalcolo da zero
- one_shot vs organic non sono path implementativi diversi: differiscono solo per quali voci dipendenti propagano l'effetto, governato da `override_policy.yaml` (vedi `flows/11_override_policy_matrix.md`)

**Implementation step propagation** (riga 3 sopra):
- Identifica le voci che dipendono dal voice_id overridden via `voice_dependencies.yaml`
- Per ogni dipendente, ricalcola il base_value usando effective values degli input
- Itera fino a fixed point (convergenza dopo ~3-5 iterazioni tipicamente)
- Per `one_shot`: la propagazione si ferma alle voci segnate come "always_propagate" nella policy (es. cash via CF identity); le altre voci dipendenti non assorbono il delta

Questa architettura risolve il rischio implementativo segnalato nella critica originale: niente più ambiguità su "ri-eseguire la fase X o no".

## Frontend — pattern

- **State management**: Zustand per state globale leggero. Niente Redux per pilot.
- **Data fetching**: react-query (TanStack Query) per cache, retry, loading states.
- **Routing**: React Router.
- **Forms**: react-hook-form + zod per validation.
- **Tabelle finanziarie**: AG Grid Community (free) o TanStack Table — decidere durante build in funzione di feature richieste (drill-down, edit inline).
- **Grafici**: recharts per pilot. Eventualmente Plotly se servono interazioni complesse.

## Decisioni architetturali da fissare durante il build

Cose che non sono ancora state decise e vanno risolte all'inizio del build (prima dei flow):

1. **Pacchettizzazione progetto**: monorepo con backend + frontend in stesso git, oppure due repo separati?
2. **API versioning**: `/api/v1/...` da subito, oppure inizio senza prefisso?
3. **CORS in dev**: backend e frontend su porte diverse, gestione CORS.
4. **Testing strategy**: pytest + coverage da subito, o solo a milestone successive?
5. **Logging**: structlog o logging stdlib? File rotanti o stdout? Per pilot OK stdout.
6. **Configurazione environment**: pydantic-settings + .env file.
7. **Hot reload dev**: uvicorn --reload per backend, Vite HMR per frontend.

Suggerimento operativo: **monorepo, no API versioning iniziale, CORS aperto in dev, pytest da subito ma solo per engine core, structlog su stdout, pydantic-settings, hot reload sì**.
