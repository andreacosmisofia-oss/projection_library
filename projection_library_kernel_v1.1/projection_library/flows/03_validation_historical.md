# Flow 03 — Validation storica + KPI historical

## Scopo

Una volta mappato il bilancio, validare la consistenza dello storico e calcolare i KPI sui dati attuali. I KPI servono come default per le assumption forward-looking.

## Trigger

Dopo conferma mapping (Flow 02). Sistema esegue validation + KPI calc automaticamente, mostra risultati.

## Input

- `mapped_values`: per ogni `voice_id`, valori per anno (Y-3..Y0 a seconda di cosa caricato)
- `voice_registry` per metadata voci
- `validation_rules` filtrate per scope storico (non tutte le 73 si applicano allo storico)
- `kpi_registry`

## Logica

### 1. Validation storica

`domain/intake/validator_historical.py`:

Esegue regole con `trigger_phase` = `E0_pre`, `E0_post` filtrate per:
- Categorie `data_integrity` (DI_001-014) — applicabili tutti
- Categoria `accounting_identity` (AI_001-011) → solo subset:
  - AI_005 subtotal_consistency su storico
  - AI_006-008 P&L chain consistency
  - AI_009-010 provisions/EB balance se hanno open/close storici
- Categoria `sign_consistency` (SC_001-009) → tutti applicabili
- Categoria `cross_period` (CP_001-008) → applicabili solo se ≥2 anni storici
- Categoria `configuration` (CF_001-006) → CF_005, CF_006 (perimetro, currency)

Output: `ValidationReport` con liste per severity:

```json
{
  "block": [
    {"rule_id": "DI_002_y0_actual_complete", "voice_id": "pl.rev.net", "year": "Y0", "message": "..."}
  ],
  "error": [
    {"rule_id": "AI_005_subtotal_consistency_projected", "voice_id": "pl.opex.total", "year": "Y0", "expected": -500, "got": -495, "delta": -5}
  ],
  "warning": [...],
  "info": [...]
}
```

### 2. Behavior on validation

- **Block presente** → utente non può procedere. UI mostra "Fix these issues to continue".
- **Error presente** → utente può procedere ma vede banner "Plan contains accounting inconsistencies". Verrà mantenuto durante run.
- **Warning** → solo info, non blocca.

### 3. KPI calculation

`domain/kpi/calculator.py`:

Per ogni KPI in `kpi_registry`:

```python
def compute_kpi(
    kpi_spec: KPISpec,
    mapped_values: MappedValues,
    year: str
) -> Optional[float]:
    """
    Returns None se non calcolabile (denominator missing, dati mancanti).
    """
    num = resolve_voice_value(kpi_spec.numerator, mapped_values, year)
    den = resolve_voice_value(kpi_spec.denominator, mapped_values, year)
    
    if num is None or den is None:
        return None
    
    # Sign handling
    if kpi_spec.sign_handling == "abs_num":
        num = abs(num)
    elif kpi_spec.sign_handling == "abs_den":
        den = abs(den)
    elif kpi_spec.sign_handling == "abs_both":
        num, den = abs(num), abs(den)
    
    # Division
    if den == 0:
        return None
    
    return num / den
```

Calcolo per ogni anno disponibile (Y-3..Y0). Salva in `historical_kpis`.

### 4. KPI aggregation

Per ogni KPI con `default_aggregation`, calcolare l'aggregato che sarà usato come default per assumption Y1-Y3:

- `avg_3y`: media valori Y-2, Y-1, Y0 se tutti presenti, altrimenti media disponibili
- `last_3y_cagr`: CAGR Y-3 → Y0 se entrambi presenti
- `y0_value`: solo Y0
- `y0_value_with_drift`: Y0 con possibile drift suggerito (default 0)

Salva risultato nel campo `default_for_projection`.

### 5. LFL filtering

Se utente ha marcato Y-1 come "not LFL" (Flow 01), KPI calcolati **escludendo** quell'anno per `avg_3y` e `cagr` ma **includendolo** per Y0 e `y0_value`. Marca KPI con flag `lfl_warning = true` se calcolato su anni misti.

### 6. KPI calibration score

Per ogni KPI, score di calibrazione (0-1):
- 1.0 se ≥3 anni LFL disponibili
- 0.7 se 2 anni LFL
- 0.4 se 1 anno (solo Y0, niente trend)
- 0 se non calcolabile

Salvato in `historical_kpis.calibration_score`.

## Output

### KPI table per UI

```json
[
  {
    "kpi_id": "kpi.growth.revenue_yoy",
    "values": {"Y-1": null, "Y0": 0.105},
    "default_for_projection": 0.105,
    "calibration_score": 0.4,
    "lfl_warning": false
  },
  {
    "kpi_id": "kpi.margin.gross",
    "values": {"Y-1": 0.42, "Y0": 0.43},
    "default_for_projection": 0.425,
    "calibration_score": 0.7,
    "lfl_warning": false
  },
  ...
]
```

### Validation report (UI)

Tabella issue raggruppata per severity, ogni issue con:
- rule_id (cliccabile per spiegazione)
- voice/year context
- "Auto-fix" button quando possibile (es. sign flip suggerito)

## API

### `POST /api/projects/{id}/validate-historical`

Esegue validation, salva report. Idempotente.

**Response 200**:
```json
{
  "report_id": "uuid",
  "summary": {
    "block": 0,
    "error": 2,
    "warning": 5,
    "info": 1
  },
  "issues": [...],
  "can_proceed": true
}
```

`can_proceed = false` se almeno 1 block.

### `POST /api/projects/{id}/kpi-historical`

Calcola KPI, salva. Idempotente.

**Response 200**:
```json
{
  "computed": 75,
  "not_computable": 12,
  "stored_at": "..."
}
```

### `GET /api/projects/{id}/kpi-historical`

Ritorna KPI per UI.

### `GET /api/projects/{id}/validation-report/historical`

Ritorna report corrente.

## Frontend

### UI Validation

```
┌────────────────────────────────────────────────────────────┐
│  Step 3 of 6: Validate balance & compute KPIs               │
├────────────────────────────────────────────────────────────┤
│                                                              │
│  Validation summary:                                         │
│   ⛔ 0 blocks                                                │
│   🔴 2 errors                                                │
│   🟡 5 warnings                                              │
│   🔵 1 info                                                  │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 🔴 AI_005 — Subtotal mismatch                        │   │
│  │    pl.opex.total Y0: expected -500, got -495 (Δ -5) │   │
│  │    [ Show details ]                                  │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ 🔴 AI_005 — Subtotal mismatch                        │   │
│  │    bs.fa.tangible.gross_close Y0: ...               │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ 🟡 RP_002 — Gross margin out of range                │   │
│  │    Y0: -8% (expected -100%..+95%)                    │   │
│  │ ...                                                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
│  Plan contains accounting inconsistencies but can proceed.  │
│  Errors will be carried in final report.                    │
│                                                              │
│  [ ← Back ]                                  [ Continue → ] │
└────────────────────────────────────────────────────────────┘
```

### UI KPI table

Tab/section accanto a validation:

```
Historical KPIs (75 / 87 computable)

[ Filter by family ▼ ]    [ Show calibration score ☑ ]

┌──────────────────────────────────────┬──────┬──────┬───────┐
│ KPI                                   │ Y-1  │ Y0   │ Calib.│
├──────────────────────────────────────┼──────┼──────┼───────┤
│ Growth                                │      │      │       │
│   Revenue YoY                         │  —   │ 10.5%│ ●○○○○ │
│   EBITDA YoY                          │  —   │ 12.0%│ ●○○○○ │
├──────────────────────────────────────┼──────┼──────┼───────┤
│ Margin                                │      │      │       │
│   Gross margin                        │ 42.0%│ 43.0%│ ●●●○○ │
│   EBITDA margin                       │ 18.5%│ 19.0%│ ●●●○○ │
│ ...                                   │      │      │       │
└──────────────────────────────────────┴──────┴──────┴───────┘
```

## Acceptance criteria

1. Bilancio coerente caricato → validation con 0 block, KPI calcolati e visibili
2. Bilancio con SP non quadrato → DI_013 block, utente non può procedere
3. KPI con dati mancanti per CAGR → marcato "not computable" con reason
4. Y-1 marcato not-LFL → KPI cagr esclusi quel anno, flag visibile
5. UI mostra issue con contesto chiaro

## Edge cases

- **Solo Y0 caricato**: tutti i CAGR e avg_3y diventano `y0_value` (calibration score 0.4)
- **Y0 con valore 0 in denominator KPI**: KPI not computable, no error
- **Subtotal mismatch piccolo (< 0.5%)**: warning invece di error (tolleranza)
- **Validation in batch**: deve completare in <5s anche con 73 regole × 200 voci × 4 anni

## Test cases

- TC-03-01: bilancio quadrato, 4 anni → 87 KPI computati, 0 block
- TC-03-02: SP non quadrato Y0 → DI_013 block
- TC-03-03: solo Y0 → 87 KPI computati con calibration_score = 0.4
- TC-03-04: ricavi negativi storici → SC_001 error
- TC-03-05: Y-1 not-LFL → kpi.growth.revenue_cagr_3y skip Y-1, marcato lfl_warning
