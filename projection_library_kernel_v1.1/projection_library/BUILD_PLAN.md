# Build Plan — Pilot v1.1

## Filosofia del build

- **Vertical slice first**: ad ogni milestone si chiude end-to-end un pezzo del flusso, non si stratifica a layer.
- **Backend before frontend**: ogni feature è prima funzionante via Swagger UI / curl, poi connessa al frontend.
- **Test-first per engine core**: la matematica deve essere testata prima di costruirci sopra.
- **Frontend mockato all'inizio**: dashboard con dati hardcoded per validare UX, poi connessa al backend reale.
- **Registry come fonte di verità**: ogni decisione tecnica passa per i registry YAML, non hardcoded nel codice.

## Milestone

### Milestone 0 — Project bootstrap

**Obiettivo**: repo strutturato, dipendenze installate, hello world.

**Tasks**:
1. Init monorepo: `backend/`, `frontend/`, `registries/`, `data_contracts/`, `tests/`
2. Setup `backend/`:
   - `pyproject.toml` con dipendenze: `fastapi`, `uvicorn[standard]`, `sqlalchemy`, `alembic`, `pydantic`, `pydantic-settings`, `pyyaml`, `pandas`, `numpy`, `openpyxl`, `pytest`, `pytest-cov`, `httpx`, `structlog`
   - Struttura cartelle come da `ARCHITECTURE.md`
   - FastAPI app con endpoint `/health` che risponde `{"status": "ok"}`
   - SQLite db file in `backend/data/pilot.db`
   - Alembic init
3. Setup `frontend/`:
   - Vite + React + TypeScript template
   - Tailwind CSS configurato
   - shadcn/ui installato (alcuni componenti base: Button, Card, Dialog)
   - axios + react-query configurati
   - Pagina home che chiama `/health` e mostra "Backend connected"
4. Setup CORS dev (backend permette frontend su localhost:5173)
5. Test pytest setup: 1 test stupido che passa
6. Test vitest setup: 1 test stupido che passa
7. Git ignore standard

**Acceptance**: 
- `cd backend && uvicorn api.main:app --reload` → API risponde su :8000
- `cd frontend && npm run dev` → frontend su :5173 mostra "Backend connected"
- `cd backend && pytest` → 1 test passa
- `cd frontend && npm test` → 1 test passa

**Tempo stimato**: 2-4 ore.

---

### Milestone 1 — Registry + machine-readable artifacts (Step 2 deliverable)

**Obiettivo**: produrre tutti gli artefatti machine-readable che mancano per rendere il sistema implementabile in modo deterministico. Senza questi artefatti, qualunque milestone successiva è interpretazione.

**Sub-milestone**:

#### M1.0 — Audit count Excel + reconciliation

Script Python che apre `Projection_Library_Spec_v1.1.xlsx` e produce report:
- Count fisico per ogni sheet (voci, KPI, methods, derived rules, validation rules, sector packs)
- Cross-reference check: per ogni voice_id citato in 03_kpis, esiste in 02_voices? Per ogni method_id in 02_voices.default_method, esiste in 01_methods? ecc.
- Output: `audit_report.md` con count definitivi e lista incongruenze
- Aggiornare `README.md` e altri docs con i numeri definitivi

**Tempo**: 0.5-1 giorno.

#### M1.1 — JSON Schema per ogni registry

Cartella `data_contracts/registries/` con 8 schemi:
- `voice_registry.schema.json`
- `method_registry.schema.json`
- `kpi_registry.schema.json`
- `validation_rule.schema.json`
- `derived_rule.schema.json`
- `sector_pack.schema.json`
- `driver_registry.schema.json`
- `assumption_registry.schema.json`

Ogni schema definisce campi obbligatori, enum, range, cross-reference attese.

**Tempo**: 1-2 giorni.

#### M1.2 — Estrazione 6 registry YAML da Excel

Script Python che legge i fogli Excel e produce:
- `registries/voice_registry.yaml`
- `registries/method_registry.yaml`
- `registries/kpi_registry.yaml`
- `registries/validation_rules.yaml`
- `registries/derived_rules.yaml`
- `registries/sector_packs/{generic,industrial,saas,retail,real_estate,services}.yaml`

Ogni YAML deve passare validation contro lo schema corrispondente. Lo script fallisce se anche un solo record viola lo schema.

**Normalizzazioni richieste durante estrazione**:
- `nature` enum atomico (no più valori compositi tipo "driver (placeholder)")
- `calc_phase` valore singolo per voce (non "E1 proxy / E3 final"); usare campo dedicato `final_phase` per voci con proxy chain
- Aggiungere colonne mancanti: `aggregation_parent`, `is_required_by_tier`, `sector_scope`, `output_order`, `balance_sheet_side`, `cash_flow_classification`

**Tempo**: 3-4 giorni.

#### M1.3 — Formula registry machine-readable

Per ogni method e derived rule, aggiungere campo `formula_python` al registry esistente:

```yaml
- method_id: historical_avg_growth
  formula_human: "value[t] = value[t-1] × (1 + growth_rate)"
  formula_python: "voices[voice][prev_year] * (1 + assumptions[voice]['growth_rate'][year])"
  allowed_namespace: [voices, assumptions, drivers, kpis, prev_year, year, voice]
```

Per le validation rules, aggiungere `expression_python` o `custom_function`:

```yaml
- rule_id: AI_001_balance_check
  expression_python: "abs(voices['bs.total_assets'][year] - voices['bs.total_liab_equity'][year]) <= max(1.0, 0.0001 * abs(voices['bs.total_assets'][year]))"
```

Per regole troppo complesse, riferimento a funzione Python in modulo dedicato.

**Tempo**: 5-7 giorni (è il punto più lavorato perché ogni formula va verificata).

#### M1.4 — Voice dependency graph

`registries/voice_dependencies.yaml` generato semi-automaticamente:

1. Parsing AST di ogni `formula_python` per estrarre riferimenti a `voices[X][Y]`
2. Output:

```yaml
- voice_id: pl.ebit
  phase: E7
  depends_on_voices: [pl.ebitda.final, pl.da.total, pl.impairment.total]
  depends_on_kpis: []
  depends_on_assumptions: []
  formula_rule_id: DR_EBIT_001
  dependency_type: derived_identity
```

Il grafo deve passare check di acyclicity (DAG) — eccezioni per circolarità note documentate nelle approximations.

**Tempo**: 2-3 giorni (dipende da M1.3 completato).

#### M1.5 — Override policy matrix

`registries/override_policy.yaml` con matrice voice category → treatment:

```yaml
- policy_class: revenue_organic
  applies_to_voices_pattern: "pl.rev.gross.*"
  one_shot_allowed: true
  organic_propagation_targets:    # voci che assorbono delta in modalità organic
    - pl.cogs.*               # via metodo COGS attivo
    - bs.nwc.ar.*             # via DSO
    - pl.tax.current          # via ETR
  one_shot_propagation_targets:   # voci che assorbono delta anche in one_shot (sempre)
    - bs.nfp.cash             # via CF identity
  cf_treatment: "operating_cf"
  tax_treatment: "applies_etr_unless_flag_off"
  affects_future_years: false
```

Una policy class per ogni macro-categoria (~10-15 classi). Ogni voice_id mappato a una policy_class.

**Tempo**: 2-3 giorni.

#### M1.6 — Required Data Matrix (derivata)

Script che genera `required_data_matrix.yaml` da `voice_registry` × `method_registry` × `tier_levels` × `sector_packs`. Output:

```yaml
- required_data_id: hist_pl_rev_net_y0
  type: actual_voice
  voice_id: pl.rev.net
  method_id: historical_avg_growth
  tier: TIER_1
  required_if: "method_id == 'historical_avg_growth'"
- required_data_id: driver_saas_new_arr
  type: driver
  driver_id: driver.saas.new_arr
  method_id: arr_bridge
  tier: TIER_4_A
```

Materiale derivato, no manual editing.

**Tempo**: 1 giorno.

#### M1.7 — Sample datasets

Cartella `sample_data/` con file Excel pronti per test:
- `tier1_minimal_balance.xlsx` — solo Y0, voci aggregate, ~20 voci
- `tier2_industrial_clean.xlsx` — 2 anni LFL, bilancio quadrato, sector industrial completo
- `tier2_industrial_unbalanced.xlsx` — bilancio con DI_013 fail (per test validation)
- `saas_arr_bridge.xlsx` — driver SaaS completi per arr_bridge
- `retail_lease_ifrs16.xlsx` — IFRS 16 con ROU/lease liability
- `real_estate_ias40.xlsx` — IAS 40 IP fair value

Costruiti a mano (Excel realistici, non random).

**Tempo**: 3-4 giorni.

#### M1.8 — Test cases YAML

`registries/test_cases.yaml` collega sample dataset a expected output:

```yaml
- test_id: TC_E2E_industrial_clean
  sector: industrial
  tier: TIER_2
  input_dataset: sample_data/tier2_industrial_clean.xlsx
  expected_output:
    voices:
      pl.rev.net.Y3: {value: 2310, tolerance: 5}
      pl.ebitda.final.Y3: {value: 460, tolerance: 10}
    balance_check_max: 1.0
    quality_score_min: 75
  purpose: "smoke test full engine on standard industrial company"
```

**Tempo**: 2 giorni.

**Acceptance Milestone 1 totale**:
- Audit count completo, numeri definitivi nei docs
- 8 JSON Schema validi
- 6 registry YAML che passano validation contro schemi
- formula_python evaluabile per tutti method/derived/validation
- voice_dependencies.yaml è DAG (eccetto circolarità note)
- override_policy.yaml copre tutte le voci (no voice_id orphan)
- required_data_matrix.yaml generato
- 6 sample dataset Excel realistici
- test_cases.yaml con almeno 8 test end-to-end

**Tempo totale Milestone 1**: 3-5 settimane (era 3-5 giorni — la sotto-stima era massiccia perché sottostimavo il volume di artefatti machine-readable richiesti).

---

### Milestone 1.9 — Registry loader (backend infrastructure)

**Obiettivo**: caricare i registry YAML in memoria, esporli via API read-only. Prerequisito M1 completata.

**Tasks**:
1. Implementare `infrastructure/registry/loader.py`:
   - Carica YAML all'avvio FastAPI (lifespan event)
   - Validazione contro JSON Schema (M1.1) all'avvio
   - Cache in memoria
   - Validazione cross-reference: ogni `method.applicable_voices` punta a voci esistenti, ecc.
2. Endpoint API read-only per esposizione registry:
   - `GET /api/registry/methods` → lista method specs
   - `GET /api/registry/methods/{method_id}` → singolo metodo
   - `GET /api/registry/voices` → lista voci
   - `GET /api/registry/voices/{voice_id}` → singola voce
   - `GET /api/registry/kpis` → lista KPI
   - `GET /api/registry/validation-rules` → lista regole
   - `GET /api/registry/sector-packs` → lista pack
   - `GET /api/registry/voice-dependencies` → grafo
   - `GET /api/registry/override-policy` → matrice
3. Test: ogni endpoint risponde con count corretto.

**Acceptance**:
- Avvio backend fallisce con errore esplicito se registry non passa validation contro JSON Schema
- Avvio backend fallisce con errore esplicito se cross-reference non risolvono
- Avvio backend fallisce con errore esplicito se voice_dependencies non è DAG (eccetto circolarità note)
- Test pytest: tutti i registry caricano, tutti gli endpoint rispondono

**Tempo stimato**: 2-3 giorni.

---

### Milestone 2 — Project CRUD + Setup iniziale

**Obiettivo**: utente crea un progetto con configurazione iniziale.

**Riferimento flow**: `flows/00_setup.md`.

**Tasks**:
1. Schema DB: tabella `projects`
2. Endpoint API:
   - `POST /api/projects` (crea, body: name, sector_pack, perimeter, currency, country, horizon_years, tier_level)
   - `GET /api/projects` (lista)
   - `GET /api/projects/{id}` (dettaglio)
   - `PATCH /api/projects/{id}` (modifica)
   - `DELETE /api/projects/{id}` (soft delete)
3. Validation iniziale: sector_pack ∈ valori validi, currency = "EUR" (forzato pilot), horizon_years = 3 (forzato pilot)
4. Frontend: pagina "New project" wizard 1 step + lista progetti
5. Test: CRUD end-to-end

**Acceptance**:
- Utente crea progetto via UI con tutti i parametri configurazione iniziale
- Progetto salvato in DB
- Lista progetti visualizzabile in UI

**Tempo stimato**: 2-3 giorni.

---

### Milestone 3 — Intake bilancio (caso 1: solo gestionale)

**Obiettivo**: utente carica file Excel/CSV con bilancio gestionale, sistema lo parsa.

**Riferimento flow**: `flows/01_data_intake.md`.

**Tasks**:
1. Schema DB: `balances`, `raw_voices`
2. Definire formato standard upload bilancio (vedi `data_contracts/balance_input.schema.json` da produrre in Step 2):
   - Excel con colonne: `voice_label`, `voice_section`, `Y-3`, `Y-2`, `Y-1`, `Y0`
   - Anni minimi: solo Y0 obbligatorio. Y-1, Y-2, Y-3 opzionali.
   - Sezioni indicative: P&L, SP, CF (se utente le fornisce)
3. Parser `domain/intake/parser.py`:
   - Legge Excel via openpyxl
   - Estrae voci con valori per anno
   - Identifica anni presenti (sparse)
4. Endpoint:
   - `POST /api/projects/{id}/balance/upload` (multipart file)
   - `GET /api/projects/{id}/balance` (ritorna voci parsate)
5. Frontend: drag-drop upload + preview tabellare voci parsate
6. Test: file Excel sample → parsing corretto

**Acceptance**:
- Utente carica Excel di bilancio (sample fornito)
- Sistema parsa e mostra in UI tabella con voci e valori per anno
- Anni mancanti sono visibili come "—"

**Tempo stimato**: 3-4 giorni.

**Estensione futura (Milestone 3.b)**: gestire caso 2 (gestionale + civilistico) e caso 3 (solo civilistico). In Milestone 3 si fa solo caso 1.

---

### Milestone 4 — Mapping voci utente → voice_registry

**Obiettivo**: mapping con auto-suggest e conferma utente.

**Riferimento flow**: `flows/02_mapping.md`.

**Tasks**:
1. Schema DB: `mappings`
2. `domain/intake/mapper.py` con:
   - Auto-suggest basato su matching lessicale (non LLM in pilot v1.1, troppo lento e costoso): 
     - Match esatto su sinonimi noti (es. "Acquisti materie prime" → `pl.cogs.materials.raw`)
     - Match fuzzy via Levenshtein/similarity score
     - Match per sezione (se voce arriva da sezione "P&L" e label contiene "ricav*", restringe candidate)
   - Confidence score 0-1 per ogni suggerimento
   - Lista candidate (non solo top-1)
3. Persistence per-azienda: cercare se esiste già un mapping confermato per la stessa azienda (`projects.name` o campo dedicato `company_id`), suggerirlo first
4. Endpoint:
   - `POST /api/projects/{id}/mapping/suggest` → ritorna mapping suggerito
   - `PUT /api/projects/{id}/mapping` → utente conferma con eventuali modifiche
   - `GET /api/projects/{id}/mapping` → mapping corrente
5. Frontend: tabella mapping con dropdown per voce, confidence indicator, alert su voci non mappate
6. Test: bilancio sample → mapping auto-suggest copre >80% voci con confidence >0.7

**Acceptance**:
- Utente carica bilancio
- Sistema propone mapping con confidence visibile
- Utente conferma o modifica
- Mapping persistito in DB

**Tempo stimato**: 5-7 giorni (mapper richiede calibrazione su dataset di sinonimi).

---

### Milestone 5 — Validation storica + KPI calc + Quality score

**Obiettivo**: una volta mappato, il sistema valida lo storico e calcola KPI.

**Riferimento flow**: `flows/03_validation_historical.md`, `flows/10_quality_score.md`.

**Tasks**:
1. `domain/intake/validator_historical.py`:
   - Implementa DI_001-014 + AI_001-011 + SC_001-009 + CP_001-008 sui dati storici (ovviamente non tutte applicabili allo storico, filtrare per scope)
   - Output: lista issue con severity
2. `domain/kpi/calculator.py`:
   - Per ogni KPI in registry, calcola valore Y-3..Y0 se calcolabile
   - Gestisce cogenza dati (se anni mancanti, KPI con `default_aggregation = avg_3y` non calcolabile)
   - Salva in DB
3. `domain/quality/scorer.py`:
   - Formula score totale + 4 sub-score (vedi `flows/10_quality_score.md`)
4. Endpoint:
   - `POST /api/projects/{id}/validate-historical` → ritorna lista issue
   - `POST /api/projects/{id}/kpi-historical` → calcola e salva
   - `GET /api/projects/{id}/kpi-historical` → ritorna KPI per UI
   - `POST /api/projects/{id}/quality-score` → calcola e salva
   - `GET /api/projects/{id}/quality-score` → ritorna score
5. Frontend: pannello validation con issue elencate (block bloccante, error/warning visibili), tabella KPI storici, badge quality score
6. Test: bilancio sample con issue noti → validation li intercetta correttamente

**Acceptance**:
- Bilancio non quadrato → issue DI_013 visibile, blocca avanzamento
- Bilancio corretto → KPI calcolati, quality score visibile
- Sub-score visibili e coerenti con dati caricati

**Tempo stimato**: 5-7 giorni.

---

### Milestone 6 — Method selection (modalità expert)

**Obiettivo**: utente seleziona metodi per voce (modalità expert prima, perché più semplice).

**Riferimento flow**: `flows/04_method_selection.md`.

**Tasks**:
1. Schema DB: `method_configs`
2. Pre-popolamento default metodo per voce (da `voice.default_method`)
3. Override sector pack: se sector_pack ≠ generic, applica `pack.method_overrides`
4. Compatibility check: `domain/methods/compatibility.py`:
   - Per ogni (voice, method), verifica disponibilità dati storici per calibrazione
   - Restituisce flag: `available | available_with_fallback | not_applicable`
5. Endpoint:
   - `GET /api/projects/{id}/methods` → ritorna config corrente
   - `PUT /api/projects/{id}/methods/{voice_id}` → cambia metodo per voce
   - `POST /api/projects/{id}/methods/apply-pack` → applica sector pack
6. Frontend: tabella expert mode con dropdown method per voce, indicatore compatibility
7. Test: cambio metodo → DB aggiornato, compatibility check coerente

**Acceptance**:
- Utente vede tabella 207 voci con metodo default precompilato
- Utente cambia metodo per singola voce → salvato
- Metodi non applicabili (es. arr_bridge se non SaaS) sono filtrati o flaggati

**Tempo stimato**: 4-5 giorni.

---

### Milestone 6.b — Method selection (modalità guided + ambition level)

**Obiettivo**: aggiunge modalità guided e visualizzazione Bronze/Silver/Gold.

**Riferimento flow**: `flows/04_method_selection.md` sezione 4.

**Tasks**:
1. `domain/methods/selector.py`:
   - Logica guided: questionario dinamico per famiglia voce
   - Calcolo Bronze/Silver/Gold per sector pack scelto
2. Frontend: switch guided/expert, wizard guided, badge ambition level
3. Test

**Acceptance**: utente può completare method selection in modalità guided rispondendo a domande senza vedere i 207 voci.

**Tempo stimato**: 5-7 giorni.

---

### Milestone 7 — Driver intake (TIER 2-4 dinamico)

**Obiettivo**: caricamento driver storici aggiuntivi richiesti dai metodi scelti.

**Riferimento flow**: `flows/05_driver_intake.md`.

**Tasks**:
1. `domain/methods/compatibility.py` esteso: calcola lista driver richiesti
2. Schema DB: `drivers`
3. Endpoint:
   - `GET /api/projects/{id}/drivers/required` → lista driver richiesti
   - `POST /api/projects/{id}/drivers/upload` (Excel sample driver)
   - `PUT /api/projects/{id}/drivers/{driver_id}` (input manuale)
4. Frontend: pannello driver con sezioni per famiglia (volumi, headcount, ecc.)
5. Test

**Acceptance**: dopo method selection, utente vede lista esatta driver da fornire e può uploadare/compilare.

**Tempo stimato**: 4-6 giorni.

---

### Milestone 8 — Assumption compilation

**Obiettivo**: pre-popolamento assumption Y1-Y3 da KPI, override utente.

**Riferimento flow**: `flows/06_assumption_compilation.md`.

**Tasks**:
1. `domain/assumptions/populator.py`: per ogni voce, popola Y1-Y3 con default da KPI o `flat`
2. Schema DB: `assumptions`
3. RP_xxx validation a runtime su input utente (warning, non block)
4. Endpoint:
   - `POST /api/projects/{id}/assumptions/populate-defaults`
   - `GET /api/projects/{id}/assumptions`
   - `PATCH /api/projects/{id}/assumptions/{voice_id}/{year}`
5. Frontend: sidebar assumption box espandibili (vedi `flows/06`)
6. Test

**Acceptance**: utente vede assumption Y1-Y3 precompilate, modificabili, con warning se fuori range plausibile.

**Tempo stimato**: 4-5 giorni.

---

### Milestone 9 — Engine core (E0-E8)

**Obiettivo**: il cuore. Esecuzione 11 fasi, year loop.

**Riferimento flow**: `flows/07_engine_execution.md`.

**Strategia**: implementare una fase alla volta, testare dopo ognuna.

**Sub-milestone**:
- 9.0: framework executor + year loop + phase orchestration
- 9.1: E0 setup (validation pre-run + KPI calc se non già fatto)
- 9.2: E1 P&L driver core
- 9.3: E2 fixed assets + D&A + impairment + IP fv
- 9.4: E3 NWC + ricalcolo COGS
- 9.5: E3.1 IFRS 15 adjustments
- 9.6: E4 NFP + financial expenses
- 9.7: E5 provisions + employee benefits
- 9.8: E6 tax differita + equity driver
- 9.9: E7 P&L bottom + tax current + retained earnings
- 9.10: E7.5 CIT NWC + NWC operating definitivo
- 9.11: E8 CF + cash close + balance check

**Per ogni sub-milestone**:
1. Test unitario fase (dato stato iniziale, verifica stato post-fase)
2. Test integrazione (chain di fasi precedenti + nuova)
3. Validation rules trigger_phase = E_X eseguite

**Tasks generali**:
1. `domain/engine/executor.py` con orchestration
2. `domain/engine/formulas.py` evaluator sicuro (no `eval()` libero, namespace whitelisted)
3. `domain/engine/derived_rules.py` per le 19 regole derived
4. Schema DB: `snapshots`
5. Endpoint:
   - `POST /api/projects/{id}/run` → esegue engine, salva snapshot
   - `GET /api/projects/{id}/snapshot/latest`

**Acceptance**:
- Engine esegue su sample project completo
- Output FS proiettati Y1-Y3
- Balance check entro tolleranza
- Validation report popolato

**Tempo stimato**: 3-4 settimane (è la milestone più grossa, è il cuore del sistema).

---

### Milestone 10 — Output dashboard MVP (frontend minimale)

**Obiettivo**: dashboard funzionale ma essenziale per visualizzare output. Niente Koyfin-style polish in M10.

**Riferimento flow**: `flows/08_output_presentation.md` — sezione "MVP UI subset".

**Scope MVP**:
- Topbar: project name + quality score badge + Refresh button
- Sidebar destra: assumption box collapsible per famiglia (no slider, solo input numerici)
- Main area con 3 tab: P&L / SP / CF (tabelle complete Y-1, Y0, Y1, Y2, Y3)
- Tab Validation con lista issue
- Tab Ratios con KPI proiettati (tabella semplice, no grafici)
- Bottombar: validation summary + last run timestamp + dirty indicator

**Esclusioni MVP** (rimandate a M14):
- 4 mini-widget centrali (P&L mini, SP mini, CF mini, KPI snapshot)
- Drill-down progressivo per sezione P&L
- Right-click context menu su celle
- Tooltip on hover con method/assumption/formula
- Mini-trend chart recharts inline
- Tab switching con virtualization avanzata
- Modal espanso quality score con breakdown grafico

**Tasks**:
1. Layout 3-pane (topbar + sidebar dx + main + bottombar)
2. Implementazione tab P&L: tabella TanStack con tutte voci, anni come colonne
3. Tab SP, CF analoghi
4. Sidebar assumption con shadcn Accordion + Input numerici
5. Topbar quality badge (modal espanso = M14)
6. Refresh button + handling stato isRunning
7. Tab Validation con tabella issue
8. Tab Ratios con tabella KPI
9. Bottombar status indicators
10. Test e2e Playwright base (navigation tab, refresh, override add)

**Acceptance MVP**:
- Utente vede dati snapshot dopo run engine
- Cambio assumption + refresh produce nuovo snapshot visibile
- Override panel funziona (form modale, not right-click)
- Validation issues visibili
- Tutto funzionale, anche se "spartano"

**Tempo stimato**: 2-3 settimane (era 3-4 settimane per scope ampio).

---

### Milestone 11 — Override layer

**Obiettivo**: override organic/one_shot con propagazione e lista persistente.

**Riferimento flow**: `flows/09_iteration.md` sezione 3.

**Tasks**:
1. Schema DB: `overrides`
2. `domain/override/resolver.py`: applica override prima/dopo engine, gestisce propagation policy
3. `domain/override/store.py`: lista override attivi
4. Endpoint:
   - `POST /api/projects/{id}/overrides` (crea)
   - `GET /api/projects/{id}/overrides`
   - `PATCH /api/projects/{id}/overrides/{id}` (attiva/disattiva)
   - `DELETE /api/projects/{id}/overrides/{id}`
5. Re-run trigger automatico al cambio override
6. Frontend: override panel (lista + form add con toggle organic/one_shot)
7. Test: override organic propaga correttamente, override one_shot tocca solo voce + cash

**Acceptance**: 
- Utente crea override "+2 mln ricavi Y3 organic" → cogs/AR/cash si aggiornano
- Utente crea override "+5 mln ricavi Y2 one_shot" → solo ricavi e cash si aggiornano

**Tempo stimato**: 1-2 settimane.

---

### Milestone 12 — Validation report visualization + Iteration

**Obiettivo**: validation report visibile in UI, iteration paths funzionanti.

**Riferimento flow**: `flows/09_iteration.md`.

**Tasks**:
1. Frontend: panel validation report (issue list filtrabile per severity)
2. Approximation log visibile
3. Pilot exclusions log visibile
4. Iteration paths UI:
   - Modifica assumption → re-run veloce (stesso flusso assumption compilation)
   - Modifica metodo → re-run con eventuale richiesta driver mancanti
   - Modifica dato storico → re-validation completa
5. Test e2e

**Acceptance**: utente naviga tra le 3 path di iterazione senza perdere lo stato.

**Tempo stimato**: 1-2 settimane.

---

### Milestone 13 — Polish v1 (post-pilot demo readiness)

**Obiettivo**: pilot pronto per demo interna.

**Tasks**:
1. Onboarding guidato (tutorial primo utilizzo)
2. Sample project caricabile con un click (per demo)
3. Export Excel del piano finale
4. Documentazione utente (README utente, non solo tech)
5. Bug fixes generali
6. Performance: tempo run engine <2s, dashboard render <500ms

**Acceptance**: pilot demo-ready.

**Tempo stimato**: 1-2 settimane.

---

### Milestone 14 — Dashboard polish (Koyfin-style upgrade)

**Obiettivo**: portare la dashboard MVP al livello "Koyfin-style" con polish visivo e UX avanzata. Lavoro post-pilot, prima di passare a use case più complessi.

**Tasks**:
1. 4 mini-widget centrali (P&L mini, SP mini, CF mini, KPI snapshot) cliccabili
2. Drill-down progressivo per sezione P&L (gross/net/ebitda/ebit/ni)
3. Right-click context menu su celle (override here, edit assumption, etc.)
4. Tooltip on hover con method/assumption/formula
5. Mini-trend chart recharts inline su KPI
6. Modal espanso quality score con breakdown grafico
7. Color coding celle (input/calculated/subtotal/override-adjusted)
8. Animazioni transition tra tab e refresh

**Acceptance**: dashboard visualmente al livello Koyfin/Bloomberg-lite.

**Tempo stimato**: 2-3 settimane.

---

## Sintesi tempistiche

| Milestone | Descrizione | Tempo |
|-----------|-------------|-------|
| 0 | Project bootstrap | 2-4 ore |
| **1 (Step 2)** | **Registry + machine-readable artifacts** | **3-5 settimane** |
| 1.9 | Registry loader | 2-3 giorni |
| 2 | Project CRUD | 2-3 giorni |
| 3 | Intake bilancio (caso 1) | 3-4 giorni |
| 4 | Mapping voci | 5-7 giorni |
| 5 | Validation + KPI + quality score | 5-7 giorni |
| 6 | Method selection (expert) | 4-5 giorni |
| 6.b | Method selection (guided + ambition) | 5-7 giorni |
| 7 | Driver intake | 4-6 giorni |
| 8 | Assumption compilation | 4-5 giorni |
| 9 | Engine core E0-E8 | 4-5 settimane (era 3-4, +30% buffer) |
| 10 | Dashboard MVP | 2-3 settimane |
| 11 | Override layer | 1-2 settimane |
| 12 | Validation report + iteration | 1-2 settimane |
| 13 | Polish v1 (demo-ready) | 1-2 settimane |
| 14 | Dashboard polish (Koyfin-style) | 2-3 settimane (post-pilot) |

**Totale stimato pilot demo-ready (M0-M13)**: 18-26 settimane di lavoro effettivo (era 14-20).

**Totale stimato post-pilot polish (M0-M14)**: 20-29 settimane.

**Note sul buffer**: la stima precedente sottovalutava in particolare:
- Volume di artefatti machine-readable di M1 (registry schemas, formula registry, dependency graph, override policy, sample data, test cases)
- Engine core M9 — implementare 11 fasi con safe formula evaluator + override overlay è più complesso del semplice "year loop + phase pattern"
- Volume mapping synonym table M4

Lo Step 2 in Claude Code (M1) richiede tempo dedicato perché molti degli artefatti vengono prodotti via parsing di Excel + estrazione AST formule + validazione cross-reference. Sottostimare questo step porta a costruire il sistema su fondamenta non testate.

## Ordine consigliato di sviluppo per Claude Code

Dare a Claude Code una milestone alla volta. Per ogni milestone:

1. Mostra `BUILD_PLAN.md` + il flow file rilevante (es. `flows/00_setup.md` per Milestone 2)
2. Chiedi: *"Esegui Milestone X. Mostra i file che crei/modifichi prima di scrivere. Non procedere alla milestone successiva."*
3. Review output
4. Test acceptance criteria
5. Solo se OK, passare alla milestone successiva

## Cose da NON fare durante il build

- Non saltare i test di engine. Il sistema è registry-driven matematico, una formula sbagliata si propaga ovunque.
- Non hardcodare voci/metodi/regole nel codice. Tutto deve passare per i registry.
- Non implementare features fuori scope (vedi exclusions). Tentazione forte ma debito tecnico immediato.
- Non ottimizzare prematuramente (es. cache aggressivo, query optimization). Pilot funzionante prima, poi ottimizzazione se necessaria.
- Non saltare il logging strutturato. Debug senza log strutturati su sistema con 11 fasi engine è incubo.
