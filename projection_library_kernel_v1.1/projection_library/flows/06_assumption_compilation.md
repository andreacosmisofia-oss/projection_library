# Flow 06 — Assumption compilation (Y1-Y3)

## Scopo

L'utente compila i parametri forward-looking (Y1-Y3) per ogni metodo configurato. Il sistema pre-popola con default da KPI storici, l'utente accetta o modifica.

## Trigger

Dopo driver intake (Flow 05). Sistema ha tutti i dati storici e i metodi configurati. Manca solo "quanto cresce ogni cosa" Y1-Y3.

## Input

- `method_configs` (Flow 04)
- `historical_kpis` (Flow 03)
- `drivers` (Flow 05)

## Logica

### 1. Estrazione assumption necessarie

Per ogni `method_config`, estrarre dalla `method_registry.assumptions` la lista di parametri richiesti:

```yaml
# method_registry.yaml
- method_id: historical_avg_growth
  assumptions:
    - name: growth_rate
      type: pct
      default_kpi: kpi.growth.<voice>_yoy
      default_aggregation: avg_3y
      validation_range: [-0.50, 2.00]
      
- method_id: pct_net_revenue
  assumptions:
    - name: pct
      type: pct
      default_kpi: kpi.margin.<voice>_pct_revenue
      default_aggregation: avg_3y
      validation_range: [0, 1]
```

### 2. Pre-populate

Per ogni (voice_id, method_config, assumption), per ogni anno Y1-Y3:

```python
def populate_default(
    voice_id: str,
    method_id: str,
    assumption_name: str,
    year: str,
    historical_kpis: dict
) -> AssumptionDefault:
    method_spec = method_registry[method_id]
    asm_spec = method_spec.assumptions[assumption_name]
    
    if asm_spec.default_kpi:
        # Resolve template (es. kpi.growth.<voice>_yoy)
        kpi_id = resolve_template(asm_spec.default_kpi, voice_id)
        kpi_value = historical_kpis.get(kpi_id, {}).get("default_for_projection")
        
        if kpi_value is not None:
            return AssumptionDefault(
                value=kpi_value,
                source="default_kpi",
                kpi_id=kpi_id,
                calibration_score=historical_kpis[kpi_id]["calibration_score"]
            )
    
    # Fallback se KPI non calcolabile
    return AssumptionDefault(
        value=asm_spec.fallback_value or 0,
        source="fallback",
        calibration_score=0
    )
```

Tutti gli anni Y1, Y2, Y3 hanno default = stesso valore (flat). Drift verso target = lasciato all'utente.

### 3. Validation runtime

Quando utente modifica un'assumption, sistema applica RP_xxx in tempo reale (warning visivo, non block):
- Range plausibility (RP_001-022)
- Cross-period continuity (CP_002-008)

Esempi:
- Utente mette `growth_rate.Y1 = 2.50` (250%) → warning RP_022 "volume growth fuori range plausibile"
- Utente mette `dso.Y1 = 400` → warning RP_004

### 4. Drift e curve

Pilot v1.1 supporta solo:
- **Flat**: stesso valore Y1, Y2, Y3
- **Linear drift**: utente mette valore Y1 e Y3, Y2 interpolato
- **Custom**: utente mette valore esplicito per ogni anno

UI permette di scegliere quale curve usare per ogni assumption.

### 5. Persistence

Tabella `assumptions`:
```json
{
  "id": "uuid",
  "project_id": "uuid",
  "voice_id": "pl.rev.gross.product_sales",
  "method_id": "historical_avg_growth",
  "assumption_name": "growth_rate",
  "year": "Y1",
  "value": 0.10,
  "source": "default_kpi | user_input",
  "default_kpi_id": "kpi.growth.pl.rev.gross.product_sales_yoy",
  "validation_range": [-0.5, 2.0],
  "user_modified_at": null
}
```

## API

### `POST /api/projects/{id}/assumptions/populate-defaults`

Esegue pre-populate per tutti method_configs. Idempotente (sovrascrive valori `source=default_kpi`, lascia intatti `source=user_input`).

**Response 200**:
```json
{
  "populated": 248,  // 207 voci × ~3 assumption media × 3 anni filtrato
  "fallback_used": 12,
  "kpi_default_used": 236
}
```

### `GET /api/projects/{id}/assumptions`

**Response 200**:
```json
{
  "assumptions": [
    {
      "voice_id": "pl.rev.gross.product_sales",
      "method_id": "historical_avg_growth",
      "assumption_name": "growth_rate",
      "values": {"Y1": 0.10, "Y2": 0.10, "Y3": 0.10},
      "source": "default_kpi",
      "calibration_score": 0.7,
      "validation_status": "ok | warning_range | warning_continuity"
    },
    ...
  ]
}
```

### `PATCH /api/projects/{id}/assumptions/{voice_id}/{assumption_name}/{year}`

Body: `{"value": 0.12}`. Cambia valore. `source` auto-set a `user_input`. Trigger validation.

### `POST /api/projects/{id}/assumptions/{voice_id}/{assumption_name}/curve`

Body: `{"curve_type": "linear_drift", "y1": 0.10, "y3": 0.05}`. Applica drift.

## Frontend

### UI

Sidebar destra del progetto, organizzata in box espandibili per famiglia:

```
┌───────────────────────────────────┐
│ Assumptions                        │
├───────────────────────────────────┤
│                                    │
│ ▼ Revenue (12 voices)              │
│   ▼ pl.rev.gross.product_sales    │
│     ↳ method: historical_avg_growth│
│     growth_rate                    │
│     Y1: [10.5%] Y2: [10.5%] Y3:[..]│
│     Default: KPI YoY (●●●○○ calib.)│
│     Curve: ( ) Flat (•) Linear     │
│                                    │
│   ▶ pl.rev.gross.service_revenue  │
│   ▶ pl.rev.gross.subscription     │
│   ...                              │
│                                    │
│ ▶ Costs (24 voices)                │
│ ▶ NWC (12 voices)                  │
│ ▶ Fixed assets (8 voices)          │
│ ▶ Debt (6 voices)                  │
│ ▶ Tax (3 voices)                   │
│ ▶ Other                            │
│                                    │
└───────────────────────────────────┘
```

### Componenti
- shadcn `Accordion` per famiglie
- `Input` numerico con suffisso (% o days o EUR_000)
- `Tooltip` per mostrare KPI source
- `Slider` opzionale per range comuni
- Indicatore calibration score (5 dot)
- Warning icon se validation fallisce

## Acceptance criteria

1. Sistema pre-popola tutte le assumption con default da KPI calcolabili
2. Per KPI non calcolabili, fallback con warning visibile
3. Utente modifica una assumption → validation real-time (range + continuity)
4. Curve flat/linear/custom selezionabile
5. Calibration score visibile per ogni assumption (= score del KPI sorgente)
6. Source indicator: chiaro se default o user input

## Edge cases

- **KPI default = None**: assumption marcata "fallback used", utente deve compilare
- **Range plausibility violato ma utente conferma**: warning permanente, non blocca
- **Cambio metodo dopo populate**: vecchie assumption invalidate, sistema riapplica populate
- **Sector pack saas**: assumption arr_bridge ha schema speciale (5 sub-assumption: new_arr, expansion, contraction, churn rates)

## Test cases

- TC-06-01: populate dopo Flow 03+04+05 → tutte assumption con default
- TC-06-02: utente cambia growth_rate.Y2 = 0.30 → warning RP, salva, source=user_input
- TC-06-03: linear drift Y1=0.10, Y3=0.05 → Y2 = 0.075 calcolato
- TC-06-04: cambio metodo (volume_price → historical_avg_growth) → vecchie assumption volume_price escluse, nuove growth_rate populate
