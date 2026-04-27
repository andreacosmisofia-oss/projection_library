# Flow 05 — Driver intake (TIER 2-4 dinamico)

## Scopo

Caricamento dei driver storici aggiuntivi richiesti dai metodi scelti in Flow 04. La lista driver è dinamica: dipende da quali metodi l'utente ha configurato.

## Trigger

Dopo method selection (Flow 04). Sistema mostra utente la lista driver da fornire (può essere vuota se utente ha scelto solo metodi TIER 1).

## Cosa è un driver

Un **driver** è un dato storico aggiuntivo (rispetto al bilancio) che alcuni metodi richiedono per calibrarsi. Esempi:

- `driver.headcount.cogs_labour_direct.Y0 = 45` (numero FTE produzione)
- `driver.production_volume.Y0 = 12500` (unità prodotte)
- `driver.saas.churn_arr.Y0 = 380` (ARR perso per churn)
- `driver.term_loan.initial_principal = 5000`, `.term_years = 7`, `.rate = 0.045` (parametri prestito)

Sono **diversi** da:
- **Voci di bilancio** (caricate in Flow 01) → contabili
- **Assumption** (compilate in Flow 06) → forward-looking (Y1-Y3)

I driver sono **dati storici di management**, paralleli al bilancio.

## Logica

### 1. Lista driver richiesti

`domain/methods/compatibility.py`:

```python
def compute_required_drivers(method_configs: list[MethodConfig]) -> list[DriverRequirement]:
    """
    Per ogni method_config, estrai i driver dichiarati nel method.inputs.drivers.
    Aggregare per driver_id, eliminare duplicati.
    """
```

Output:
```json
[
  {
    "driver_id": "driver.headcount.cogs_labour_direct",
    "required_by_methods": ["headcount_unit_cost"],
    "required_for_voices": ["pl.cogs.labour.direct"],
    "type": "scalar_per_year",
    "years_required": ["Y-1", "Y0"],
    "unit": "FTE"
  },
  {
    "driver_id": "driver.term_loan.parameters",
    "required_by_methods": ["term_loan_amortization_linear"],
    "required_for_voices": ["bs.nfp.borrowings.term_loan_repayments"],
    "type": "static_parameters",
    "fields": [
      {"name": "initial_principal", "unit": "EUR_000"},
      {"name": "term_years", "unit": "years"},
      {"name": "rate", "unit": "pct"},
      {"name": "year_in_amortization", "unit": "year_index"}
    ]
  },
  ...
]
```

### 2. Tipi di driver

| Tipo | Schema | Esempio |
|---|---|---|
| `scalar_per_year` | un numero per ogni anno richiesto | headcount, capacity, production volume |
| `static_parameters` | set di parametri non-time-varying | term loan setup, BoM components |
| `time_series` | series temporale dettagliata | cohort customer counts |
| `aging_bucket` | distribuzione per bucket | IFRS 9 aging matrix |

### 3. Caricamento

3 modalità di caricamento:

**a. Manual input (form)**
Per driver semplici (scalar_per_year, static_parameters), sistema mostra form con campi.

**b. Excel upload**
Per driver complessi (time_series, aging_bucket), sistema fornisce template scaricabile e accetta upload.

**c. Skip**
Utente può saltare un driver. Conseguenza: il metodo che lo richiede passa a `available_with_fallback` o `not_applicable`. Sistema avvisa.

### 4. Validation driver

Per ogni driver caricato:
- Campi obbligatori presenti
- Tipi corretti (numerici, ranges plausibili)
- Coerenza con voci di bilancio (es. `driver.headcount.cogs_labour_direct × cost_per_fte` ~= `pl.cogs.labour.direct` Y0 → tolleranza)

Validation cross-check: warning, non block.

### 5. Persistence

Tabella `drivers`:
```json
{
  "id": "uuid",
  "project_id": "uuid",
  "driver_id": "driver.headcount.cogs_labour_direct",
  "year": "Y0",
  "value": 45,
  "unit": "FTE",
  "uploaded_at": "..."
}
```

Per driver con multiple field (static_parameters), usare un record per field oppure JSON blob (decisione di build: JSON blob è più semplice).

## API

### `GET /api/projects/{id}/drivers/required`

**Response 200**:
```json
{
  "drivers": [
    {
      "driver_id": "...",
      "required_by_methods": [...],
      "required_for_voices": [...],
      "type": "scalar_per_year",
      "years_required": [...],
      "current_status": "missing | partial | complete | skipped"
    },
    ...
  ],
  "summary": {
    "total": 24,
    "complete": 8,
    "partial": 3,
    "missing": 12,
    "skipped": 1
  }
}
```

### `POST /api/projects/{id}/drivers`

Body:
```json
{
  "driver_id": "...",
  "values": {"Y-1": 42, "Y0": 45},
  "static_parameters": {...}
}
```

### `POST /api/projects/{id}/drivers/upload`

Multipart upload di file Excel template-compliant per driver complex.

### `PATCH /api/projects/{id}/drivers/{driver_id}/skip`

Marca driver come skipped. Sistema ricalcola compatibility metodi.

### `GET /api/projects/{id}/drivers/template/{driver_id}`

Ritorna template Excel scaricabile per il driver specifico.

## Frontend

### UI Driver list

```
┌──────────────────────────────────────────────────────────┐
│  Step 4 of 6: Provide additional drivers                  │
│  12 drivers required for methods you selected             │
├──────────────────────────────────────────────────────────┤
│                                                            │
│  ┌─ Headcount drivers (3) ─────────────────────────────┐ │
│  │                                                       │ │
│  │  • headcount.cogs_labour_direct                      │ │
│  │    Required for pl.cogs.labour.direct (volume_unit) │ │
│  │    Y-1: [____]  Y0: [____]              [Skip]      │ │
│  │                                                       │ │
│  │  • headcount.opex_sm_personnel                       │ │
│  │    Required for pl.opex.sm.personnel                 │ │
│  │    Y-1: [____]  Y0: [____]              [Skip]      │ │
│  │  ...                                                  │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌─ Volume drivers (1) ────────────────────────────────┐ │
│  │                                                       │ │
│  │  • production_volume                                 │ │
│  │    Required for pl.rev.gross.product_sales (V × P)  │ │
│  │    Y-1: [____]  Y0: [____]              [Skip]      │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌─ Debt drivers (parameters) ─────────────────────────┐ │
│  │                                                       │ │
│  │  • term_loan.parameters                              │ │
│  │    [ Open form ]      [Skip]                         │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌─ Cohort drivers (advanced) ─────────────────────────┐ │
│  │                                                       │ │
│  │  • saas.cohort_data                                  │ │
│  │    [ Download template ] [ Upload Excel ] [Skip]    │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  Status: 8/24 complete                                     │
│                                                            │
│  [ ← Back ]                              [ Continue → ]   │
└──────────────────────────────────────────────────────────┘
```

### Componenti
- shadcn `Accordion` per gruppi
- `Input` numerici per scalar
- `Dialog` modale per static_parameters complessi
- File upload per time_series

## Acceptance criteria

1. Sistema mostra lista driver richiesti coerente con method config
2. Utente compila campi → DB updated
3. Utente skip un driver → metodo che lo richiede degrada (compatibility ricomputata)
4. Cross-check warning visibile (es. headcount × cost_per_fte ≠ labour_cost storico)
5. Template Excel scaricabili per driver complessi

## Edge cases

- **Driver richiesto da multipli metodi**: caricato una volta, valido per tutti
- **Driver mancante in fase engine**: fallback method usato, warning permanente
- **Cambio metodo dopo driver caricato**: driver rimane in DB ma può non essere più usato

## Test cases

- TC-05-01: method config con headcount_unit_cost → driver headcount required
- TC-05-02: utente carica solo Y0 driver → partial status
- TC-05-03: skip driver → metodo passa ad available_with_fallback
- TC-05-04: cross-check fallisce → warning visibile, no block
