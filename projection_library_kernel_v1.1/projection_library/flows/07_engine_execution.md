# Flow 07 — Engine execution (E0-E8 + year loop)

## Scopo

Cuore matematico del sistema. Esegue le 11 fasi engine per ogni anno Y1, Y2, Y3 in sequenza. Produce piano integrato P&L + SP + CF.

## Trigger

Utente preme "Run engine" dalla dashboard, oppure automaticamente dopo:
- Override (Flow 09 sezione 3)
- Cambio assumption (manualmente premendo "Refresh")

## Pre-condizioni

- Progetto con bilancio caricato e mappato
- Validation storica con 0 block
- KPI storici calcolati
- Method configs definiti
- Driver caricati (o skipped esplicitamente)
- Assumption popolate

Se manca uno dei sopra, run fallisce con errore "Project not ready".

## Architettura execution

### Stato del modello

`ModelState` è la struttura dati che viene passata e modificata dalle fasi:

```python
@dataclass
class ModelState:
    project: Project
    historical_data: dict[voice_id, dict[year, float]]
    drivers: dict[driver_id, dict[year | parameter, float]]
    assumptions: dict[voice_id, dict[assumption_name, dict[year, float]]]
    
    # Computed during execution
    voices: dict[voice_id, dict[year, float]]  # tutte le voci, storiche + proiettate
    overrides: list[Override]                  # override attivi (organic + one_shot)
    
    # Phase tracking
    current_phase: str  # E0, E1, ..., E8
    current_year: str   # Y1, Y2, Y3
    
    # Validation state
    validation_issues: list[ValidationIssue]
    approximations_applied: list[ApproximationLog]
```

### Year loop

```python
def run_engine(state: ModelState) -> ProjectionResult:
    # E0 una volta sola (setup)
    state = phase_e0_setup(state)
    
    # Loop per anno
    for year in ["Y1", "Y2", "Y3"]:
        state.current_year = year
        state = phase_e1(state)
        state = phase_e2(state)
        state = phase_e3(state)
        state = phase_e3_1(state)
        state = phase_e4(state)
        state = phase_e5(state)
        state = phase_e6(state)
        state = phase_e7(state)
        state = phase_e7_5(state)
        state = phase_e8(state)
        validate_year(state, year)
    
    # Post-loop
    state = compute_projected_kpis(state)
    state = compute_adjusted_metrics(state)  # ebitda_adjusted, ebit_adjusted
    state = generate_validation_report(state)
    state = apply_overrides(state)  # override layer (Flow 09)
    
    return build_projection_result(state)
```

### Phase pattern

Ogni fase è funzione pura `(state, year) -> state`:

```python
def phase_e1(state: ModelState) -> ModelState:
    """E1 — P&L driver core"""
    year = state.current_year
    
    # Per ogni voce assigned a questa fase
    for voice_id in voices_by_phase["E1"]:
        if voice_id not in state.method_configs:
            continue  # voice skipped o disabled
        
        method_id = state.method_configs[voice_id].method_id
        method_spec = method_registry[method_id]
        
        # Resolve inputs
        inputs = resolve_method_inputs(method_spec, voice_id, state, year)
        
        # Evaluate formula
        value = evaluate_formula(method_spec.formula_expression, inputs)
        
        # Apply sign convention
        value = apply_sign_convention(value, voice_id)
        
        # Store
        state.voices[voice_id][year] = value
    
    # Run derived rules per phase
    apply_derived_rules(state, phase="E1")
    
    # Run validation rules per phase
    run_validation_rules(state, phase="E1_post")
    
    return state
```

## Le 11 fasi

Per ogni fase, riferimento a `04_dependencies` sheet dell'Excel + sezione corrispondente di questo doc.

### E0 — Setup (una sola volta, pre-loop)

**Voci processate**: 0 (modello), KPI storici (87 × anni storici).

**Input**: `historical_data`, `drivers`, configurazioni progetto.

**Output**:
- KPI storici computati e disponibili in state
- Sector pack applicato (active_voices, method_overrides, validation_overrides)
- Assumption pre-popolate (se non già fatto)
- Validazioni hard-blocking eseguite (DI_001-014)

**Validation triggered**: tutta categoria `data_integrity` + `configuration`.

**Errore residuo**: 0 (validation hard-blocking).

### E1 — P&L driver core

**Voci processate**: ~50 voci P&L.

**Voci**: tutte le voci `pl.rev.*` (escluse adjustments), `pl.cogs.*` (escluso inventory_writeoff e wip_capitalization), `pl.opex.*`, `pl.provisions.*`, `pl.financial.fx_gain_loss`, `pl.equity_method_result`, `pl.other.non_operating_*`.

**Input**: assumption Y1-Y3, KPI storici (per default), exogenous (CPI), anchor Y0.

**Output**: ricavi gross, deductions, net.proxy, COGS.proxy, OPEX, provisions, gross_profit.proxy, ebitda.proxy.

**Validation triggered**: SC_001-002, SC_007-008 (sign), AI_007 (ebitda definition su proxy).

**Errore residuo**: <1% sui proxy, corretti in E3/E3.1.

### E2 — Fixed assets + D&A + impairment + IP fv

**Voci processate**: ~39 voci.

**Voci**: tutte `bs.fa.*` (PPE, intangibles, goodwill, ROU, investment_property, financial), `pl.da.*`, `pl.impairment.*`, `pl.other.fair_value_gain_loss_investment_property`.

**Logica chiave**:
- Roll-forward per famiglia: gross_close = open + capex - disposals + acquisitions_via_ma
- D&A mid-year convention: `da = max(0, gross_avg - non_depreciable) / useful_life`
- Impairment: input manuale (default 0)
- IP FV revaluation flussa a P&L

**Validation triggered**: SC_003 (asset positive), SC_007 (D&A negative), AI_008 (ebit definition rifatta solo a fine E7).

### E3 — NWC + ricalcolo COGS esatto

**Voci processate**: ~25 voci.

**Voci**: tutte `bs.nwc.*` (escluso cit_*, calcolato in E7.5), `pl.cogs.inventory_writeoff`, `pl.cogs.wip_capitalization`, `pl.cogs.total.final`, `pl.gross_profit.final`, `pl.ebitda.final`.

**Logica chiave**:
- DSO/DIO/DPO targets computati su denominator (rev.net.proxy o COGS.proxy)
- Inventory writeoff = -% × inventory.total_avg
- WIP capitalization = -Δ inventory.wip
- Sostituire proxy COGS con valore esatto

**Validation triggered**: SC_003-004, AI_007 (ebitda recompute).

**Errore residuo**: <1% (proxy NWC su rev.net.proxy).

### E3.1 — IFRS 15 adjustments

**Voci processate**: 3 voci.

**Voci**: `pl.rev.adjustments.deferred_movement`, `pl.rev.adjustments.contract_asset_movement`, `pl.rev.adjustments_total`. Update `pl.rev.net.final`, `pl.gross_profit.final`, `pl.ebitda.final`.

**Logica chiave**:
- contract_liabilities movement → pl.rev.adjustments.deferred_movement (negative se liab cresce)
- contract_assets movement → pl.rev.adjustments.contract_asset_movement
- pl.rev.net.final = gross_total + deductions_total + adjustments_total

### E4 — NFP + financial expenses

**Voci processate**: ~15 voci.

**Voci**: `bs.nfp.borrowings.*`, `bs.nfp.lease_liability.*`, `pl.financial.interest_*`, `pl.financial.lease_interest`.

**Logica chiave**:
- Term loan amortization: linear o annuity (a seconda metodo scelto)
- Borrowings.balance_avg per interest expense
- Lease liability: roll-forward con interest_accrued (sub-circolarità intra-fase con proxy)
- Cash[t-1] proxy per interest_income

**Validation triggered**: SC_004, SC_008.

**Errore residuo**: <1% NI per interest_income proxy, <0.25% per lease.

### E5 — Provisions + Employee benefits

**Voci processate**: ~14 voci.

**Voci**: tutti `bs.provisions.*`, tutti `bs.employee_benefits.*`.

**Logica chiave**:
- Roll-forward fondi: balance_close = open + accrual + usage
- EB: service_cost % labour, interest_cost (sub-circolarità con proxy), payments turnover-based, actuarial → OCI

**Errore residuo**: <0.1% per EB interest sub-circolarità.

### E6 — Tax differita + Equity (driver)

**Voci processate**: ~13 voci.

**Voci**: `bs.tax.dta_*`, `bs.tax.dtl_*`, `bs.equity.capital.*`, `bs.equity.share_capital.close`, `bs.equity.oci_*`, `bs.equity.nci.close`.

**Logica chiave**:
- DTA/DTL semplificato: drift lineare lieve
- Capital changes: dividendi (default payout ratio), buyback, OCI riceve identity da EB actuarial

### E7 — P&L bottom + tax current + retained earnings

**Voci processate**: ~13 voci.

**Voci**: `pl.ebit`, `pl.financial.total_net`, `pl.ebt`, `pl.tax.current`, `pl.tax.deferred`, `pl.tax.total`, `pl.net_income`, `pl.ebitda_adjusted`, `pl.ebit_adjusted`, `bs.equity.retained_earnings.close`, `bs.equity.total_close`, `bs.tax.nol_carryforward.close`.

**Logica chiave**:
- ebit = ebitda + da.total + impairment.total
- ebt = ebit + financial.total_net + equity_method + non_operating + fv_IP
- tax.current = etr × max(0, ebt) [simplified] o catena NOL [advanced]
- net_income = ebt + tax.total
- ebitda_adjusted exclude voci con flag non_recurring_extraordinary

**Validation triggered**: SC_005, AI_006, AI_008, AI_003 (RE identity).

### E7.5 — CIT NWC + NWC operating definitivo

**Voci processate**: ~6 voci.

**Voci**: `bs.nwc.other_current_liab.cit_payable`, `bs.nwc.other_current_assets.cit_receivable`, `bs.nwc.other_current_assets`, `bs.nwc.other_current_liab`, `bs.nwc.operating.final`.

**Logica chiave**:
- CIT payable = Δ tax.current annuale
- CIT receivable = acconti
- Sostituisce proxy NWC con valore final

**Errore residuo**: 0 (identity-based).

### E8 — CF + cash close + balance check

**Voci processate**: ~38 voci.

**Voci**: tutti `cf.*`, `cf.net_change_cash`, `bs.nfp.cash`, `bs.nfp.net_debt`, `bs.total_assets`, `bs.total_liabilities_equity`, `bs.balance_check`.

**Logica chiave**:
- CF operating: net_income + addback (D&A, impairment, provisions, deferred tax, financial, equity method, FV IP) - NWC change - tax_paid - EB_paid
- CF investing: -capex + disposals + IP_change + financial_assets_movement + M&A placeholder
- CF financing: borrowings flows + lease principal + interest paid - dividends + capital changes
- net_change_cash = CF_op + CF_inv + CF_fin
- cash[t] = cash[t-1] + net_change_cash[t] (identity)
- balance_check = total_assets - (total_liabilities + total_equity)

**Validation triggered**: AI_001 (balance check), AI_002 (cash identity), AI_011 (NWC change), tutta categoria SC, tutta RP, CP_001-008, CQ_001-003.

**Errore residuo**: <1% balance_check (gestito con tolleranza).

## Override layer

Dopo E8, applicare override attivi (vedi Flow 09 sezione 3). Pseudocodice:

```python
def apply_overrides(state: ModelState) -> ModelState:
    for override in state.overrides:
        if not override.is_active:
            continue
        
        voice_id = override.voice_id
        year = override.year
        delta = override.delta_amount
        
        # Apply delta
        state.voices[voice_id][year] += delta
        
        # Propagation
        if override.nature == "organic":
            propagate_organic(state, override)
        # one_shot: solo cash si aggiusta via CF identity (auto)
        
        # Cash always recompute
        recompute_cash(state, year)
    
    return state
```

## Persistence

Ogni run produce uno `Snapshot`:

```json
{
  "id": "uuid",
  "project_id": "uuid",
  "run_timestamp": "...",
  "status": "success | error",
  "duration_ms": 1842,
  "pl_data": {
    "Y-1": {...},
    "Y0": {...},
    "Y1": {...},
    "Y2": {...},
    "Y3": {...}
  },
  "sp_data": {...},
  "cf_data": {...},
  "projected_kpis": {...},
  "validation_report": {
    "block": [],
    "error": [...],
    "warning": [...],
    "info": [...]
  },
  "approximation_log": [...],
  "exclusions_active": [...],
  "overrides_applied": [...]
}
```

Solo lo snapshot più recente è "current". Storia recente accessibile (ultimi 5 snapshots) per debug/comparison.

## API

### `POST /api/projects/{id}/run`

Esegue engine. Sincrono per pilot v1.1 (target <2s). Async/queue se diventa più lento.

**Response 200**: snapshot completo.

**Response 422**: project not ready (manca prerequisito).

**Response 500**: errore engine (con stack trace in dev mode).

### `GET /api/projects/{id}/snapshot/latest`

Ritorna ultimo snapshot.

### `GET /api/projects/{id}/snapshots`

Ritorna ultimi 5 snapshots (per comparison).

## Performance targets

- E0: <100ms
- Ogni anno (E1-E8): <500ms
- Total run Y1-Y3: <2s
- Snapshot save: <200ms

Se sopra target, ottimizzazioni progressive:
1. Vettorizzare formule con numpy
2. Cache intermediate results
3. Lazy validation (solo on-demand)

## Acceptance criteria

1. Sample project completo + run → output snapshot con FS Y1-Y3
2. Balance check entro tolleranza per ogni anno
3. Cash identity verificata
4. Validation report popolato
5. Approximation log popolato (proxy applicati)
6. Performance <2s su sample TIER 2

## Edge cases

- **Method config con dato mancante**: fallback chain attivata, warning in approximation log
- **Formula evaluation fail** (es. divisione per zero non catturata): wrap in try/except, voce a 0 con error log
- **Voice referenced but not configured**: usa default `flat` con anchor Y0
- **Year loop interrotto da exception**: salva snapshot parziale con status=error

## Test cases

- TC-07-01: sample TIER 1 minimal → run completo, balance check < 1
- TC-07-02: TIER 2 standard, sector industrial → run < 2s, FS coerenti
- TC-07-03: TIER 2 standard, sector saas con arr_bridge → ARR Y3 coerente con assumption
- TC-07-04: balance check fail (formula bug introdotto in test) → error visibile
- TC-07-05: due run consecutivi senza modifiche → output identico
- TC-07-06: run con override organic +2mln revenue Y3 → cogs/AR/cash adjusted
- TC-07-07: run con override one_shot +5mln revenue Y2 → solo revenue + cash
