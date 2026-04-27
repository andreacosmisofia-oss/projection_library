# Flow 09 — Iteration paths + Override layer

## Scopo

Dopo prima esecuzione, l'utente itera modificando assumption, metodi, dati storici, oppure applicando override. Documentare i 3 + 1 path di modifica.

## I 4 path di iterazione

### Path 9.1 — Modifica assumption (più comune)

**Scenario**: utente vede output, vuole cambiare growth, DSO, capex, ecc.

**Impact**: solo Y1-Y3, nessun ricalcolo storico.

**Flusso**:
1. Utente modifica valore in sidebar (Flow 08)
2. PATCH `/assumptions/...` salva
3. UI marca "Model dirty"
4. Utente preme Refresh (può modificare più assumption insieme prima di refresh)
5. POST `/run` → engine ri-esegue tutte le 11 fasi per tutti gli anni Y1-Y3
6. Nuovo snapshot, UI aggiornata

**Tempo**: ~2s end-to-end.

### Path 9.2 — Modifica metodo

**Scenario**: utente cambia il metodo di proiezione per una voce. Es. da `pct_net_revenue` a `volume_price`.

**Impact**: cambio metodo può richiedere driver nuovi (Flow 05) e nuove assumption (Flow 06).

**Flusso**:
1. Utente cambia metodo via expert mode UI o context menu su voce
2. PUT `/methods/{voice_id}` salva
3. Sistema valuta compatibility:
   - Se nuovo metodo richiede driver mancanti → utente reindirizzato a Flow 05 con lista driver da fornire
   - Se nuovo metodo ha assumption diverse dal precedente → vecchie assumption per quella voce eliminate, nuove pre-popolate (Flow 06)
4. Quando tutti i prerequisiti soddisfatti, "Model dirty" → utente preme Refresh
5. POST `/run` → snapshot aggiornato

**Tempo**: variabile, dipende se serve driver upload.

### Path 9.3 — Modifica dato storico

**Scenario**: utente realizza che un valore storico è sbagliato (es. typo nel bilancio caricato, riclassifica scoperta).

**Impact**: re-validation completa, ricalcolo KPI, possibile re-mapping se voce nuova.

**Flusso**:
1. Utente modifica raw_voice value (UI: tabella balance editabile per Y0)
2. PATCH `/balance/{balance_id}/voice/{raw_voice_id}` salva
3. Sistema invalida automaticamente:
   - Validation report storico
   - KPI storici (perché basati su quei valori)
   - Quality score
   - Tutti gli snapshot (perché engine usa anchor Y0)
4. Sistema re-esegue automaticamente:
   - `validate-historical`
   - `kpi-historical`
   - `quality-score`
5. Se validation block → utente bloccato, deve fixare prima di re-run engine
6. Se OK → utente preme Refresh, nuovo run engine

**Tempo**: ~5s end-to-end (validation + KPI + run).

### Path 9.4 — Override (sempre disponibile)

**Scenario**: utente vuole modificare il valore proiettato di una voce specifica, by-passando il metodo.

**Impact**: applicato dopo l'esecuzione engine, propagation policy controlla la cascata.

Vedi sezione **Override Layer** sotto.

## Override Layer

### Concetto: overlay, non rerun

Un override è un **delta** che si somma al `base_value` di una voce in un anno specifico. Il sistema mantiene separati `base_value` (output dei metodi) e `override_delta` (somma overlay attivi); il valore finale `effective_value = base + delta`.

```python
override = {
    "voice_id": "pl.rev.gross.product_sales",
    "year": "Y3",
    "delta_amount": 2000,
    "nature": "organic",
    "override_policy_class": "revenue_organic",
    "is_active": True
}
```

**Principio architetturale**: l'engine NON viene ri-eseguito quando un override viene aggiunto/rimosso. Il `base_value` è invariante: dipende solo da metodi + assumption + dati storici. L'override è un livello sopra, applicato durante la risoluzione dei valori.

```python
def resolve_voice_value(voice_id: str, year: str, state: ModelState) -> float:
    """
    Single source of truth. Tutti i consumer (formula evaluator, derived rules,
    validation, CF identity, output) chiamano questa funzione.
    """
    base = state.base_values[voice_id][year]
    delta = sum(
        ov.delta_amount
        for ov in state.overrides
        if ov.voice_id == voice_id and ov.year == year and ov.is_active
    )
    return base + delta
```

### Pattern execution con override

Quando utente aggiunge un override:

1. **Salva override** in tabella `overrides`
2. **Identifica voci dipendenti** dal voice_id overridden via `voice_dependencies.yaml`
3. **Ricalcola base_value** di queste voci dipendenti applicando `resolve_voice_value` agli input (che ora ritornano effective values)
4. **Itera fino a fixed point** (tipicamente 3-5 iterazioni; max iterazioni configurabile, default 10)
5. **Cash si auto-aggiusta** via CF identity — anche cash usa `resolve_voice_value`
6. **Aggiorna snapshot** in DB:
   - `snapshot_values.base_value` aggiornato per voci dipendenti ricalcolate
   - `snapshot_values.override_delta` aggiornato per la voce overridden
   - `snapshot_values.value = base + delta` derivato

### Differenza organic vs one_shot

Le due nature differiscono **solo** per quali voci dipendenti ricevono propagazione, governato dalla **override policy matrix** (`registries/override_policy.yaml`).

Per ogni voice_id, una `override_policy_class` definisce:
- `organic_propagation_targets`: voci dipendenti che assorbono il delta in modalità organic
- `one_shot_propagation_targets`: voci dipendenti che assorbono il delta anche in modalità one_shot (sempre cash via CF identity, eventualmente altre)

Esempio policy class `revenue_organic`:

```yaml
- policy_class: revenue_organic
  applies_to_voices_pattern: "pl.rev.gross.*"
  one_shot_allowed: true
  organic_propagation_targets:
    - "pl.cogs.*"            # via metodo COGS attivo
    - "bs.nwc.ar.*"          # via DSO
    - "pl.tax.current"       # via ETR
    - "bs.nwc.cit_payable"   # via tax accrual
  one_shot_propagation_targets:
    - "bs.nfp.cash"          # sempre, via CF identity
  cf_treatment: "operating_cf"
  tax_treatment: "applies_etr_unless_flag_off"
  affects_future_years: false
```

In **organic mode**: `propagate(voice_id)` itera ricalcolando tutte le voci che match `organic_propagation_targets` PLUS `one_shot_propagation_targets`.

In **one_shot mode**: `propagate(voice_id)` itera ricalcolando SOLO le voci che match `one_shot_propagation_targets`. Le altre voci dipendenti rimangono al loro base_value (delta non assorbito).

In entrambi i casi cash si aggiusta perché è in `one_shot_propagation_targets` per ogni policy class.

Vedi `flows/11_override_policy_matrix.md` per la matrice completa.

### Override su voci derived/subtotal

Pilot v1.1 **non ammette** override hard su voci con `nature = derived` o `derived_identity` (subtotali, identità contabili).

Esempio: utente vuole forzare `pl.ebitda.final[Y2]`. Sistema risponde:
> "EBITDA è derived_identity = gross_profit + opex + provisions. Per modificare EBITDA, applica override su una delle componenti."

Soft override = guidance verso modifica di componente.

Le voci con `nature = derived` sono protette tramite check in `POST /overrides` (validation che rifiuta delta con messaggio chiaro).

### Lista override persistente

Tutti gli override creati sono **persistenti** in DB. Sono visibili in sidebar dedicata (Flow 08).

Operazioni:
- **Disattiva** (`is_active = false`) → rimosso dal calcolo, conservato in DB. Trigger ricalcolo base_value voci dipendenti.
- **Riattiva** → re-applicato.
- **Elimina definitivo** → hard delete. Trigger ricalcolo.

Combinazioni multiple coesistono: l'engine somma tutti i delta attivi per voce/anno.

### Esempio walk-through completo

**Stato iniziale** (post engine run, no override):
```
base_values:
  pl.rev.gross.product_sales[Y3] = 2,500
  pl.cogs.materials.raw[Y3] = -1,000  (calcolato come pct_net_revenue)
  bs.nwc.ar.trade_gross[Y3] = 450     (calcolato come dso × rev / 365)
  bs.nfp.cash[Y3] = 250
overrides: []
```

**Step 1**: utente aggiunge override organic
```
voice = pl.rev.gross.product_sales
year = Y3
delta = +2,000
nature = organic
policy_class = revenue_organic
```

**Sistema esegue**:
- Salva override in DB
- `resolve_voice_value(pl.rev.gross.product_sales, Y3) = 2500 + 2000 = 4500`
- Identifica dipendenti via `voice_dependencies.yaml` + `organic_propagation_targets`:
  - `pl.cogs.materials.raw[Y3]` (via metodo pct_net_revenue che usa pl.rev.net)
  - `bs.nwc.ar.trade_gross[Y3]` (via dso)
  - `pl.tax.current[Y3]` (via etr)
  - `bs.nfp.cash[Y3]` (CF identity)
- Ricalcola base_value di queste voci, usando `resolve_voice_value` per gli input
- Iterazione 1: cogs = -1800, ar = 720, tax = ..., cash = ...
- Iterazione 2: convergenza
- Salva nuovi base_values + override_delta in `snapshot_values`

**Step 2**: utente aggiunge secondo override one_shot
```
voice = pl.opex.ga.travel
year = Y2
delta = -100
nature = one_shot
policy_class = opex_one_shot
```

policy class `opex_one_shot`:
```yaml
organic_propagation_targets: [pl.cogs.*, ...altri opex...]  # ignored in one_shot mode
one_shot_propagation_targets: [bs.nfp.cash]  # solo cash
```

**Sistema esegue**:
- Salva override
- `resolve_voice_value(pl.opex.ga.travel, Y2) = base + (-100)`
- Identifica dipendenti, ma in one_shot mode propaga SOLO a cash
- Ricalcola `bs.nfp.cash[Y2]` e `bs.nfp.cash[Y3]` (cumulato) via CF identity
- Tutte le altre voci dipendenti (es. eventuali ratios) vedono il valore effective tramite resolve_voice_value, ma il loro base_value non viene ricalcolato (non sono in propagation_targets one_shot)

**Step 3**: utente disattiva il primo override
```
PATCH /overrides/{id1} {"is_active": false}
```

**Sistema esegue**:
- `is_active = false` salvato
- Ricalcolo base_value voci dipendenti dal primo override (ora `delta = 0`)
- Snapshot aggiornato: tornato allo stato pre-override 1

### Persistence schema

Tabella `overrides`:

```sql
overrides (
  id UUID PK,
  project_id UUID FK,
  voice_id TEXT NOT NULL,
  year TEXT NOT NULL,        -- 'Y1' | 'Y2' | 'Y3'
  delta_amount NUMERIC NOT NULL,
  nature TEXT NOT NULL,      -- 'organic' | 'one_shot'
  override_policy_class TEXT NOT NULL,  -- da registries/override_policy.yaml
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMP,
  deactivated_at TIMESTAMP NULL,
  user_note TEXT NULL,
  CHECK (nature IN ('organic', 'one_shot')),
  CHECK (year IN ('Y1', 'Y2', 'Y3'))
)
```

Tabella `snapshot_values` (vedi `ARCHITECTURE.md`) traccia separatamente `base_value` e `override_delta` per audit trail.

### Validazione pre-creation

Quando utente prova a creare override, sistema verifica:

1. Voice_id esiste e ha `nature` non in `[derived, derived_identity]` → altrimenti rifiuta
2. Voice_id ha policy_class definita in `override_policy.yaml` → altrimenti rifiuta
3. `nature == one_shot` → policy.one_shot_allowed deve essere true
4. Year ∈ {Y1, Y2, Y3}
5. delta_amount finite e non zero (> qualche soglia minima, es. > 0.01 in unit di lavoro)

Se utente prova a fare override su voce derived, sistema risponde con guidance:
```
"pl.ebitda.final is a derived voice (sum of gross_profit + opex + provisions).
Apply override on one of these components instead:
- pl.rev.* / pl.cogs.* (via gross_profit)
- pl.opex.*
- pl.provisions.*"
```

## API

### `POST /api/projects/{id}/overrides`

Body:
```json
{
  "voice_id": "pl.rev.gross.product_sales",
  "year": "Y3",
  "delta_amount": 2000,
  "nature": "organic",
  "user_note": "Big contract win"
}
```

**Response 201**: override creato. Trigger automatico engine run.

### `GET /api/projects/{id}/overrides`

Lista override (active + inactive). Filtro `?active_only=true`.

### `PATCH /api/projects/{id}/overrides/{id}`

Body: `{"is_active": false}`. Trigger run.

### `DELETE /api/projects/{id}/overrides/{id}`

Hard delete. Trigger run.

## Frontend

### Override panel (sidebar bottom)

```
┌──────────────────────────────────────┐
│ Active overrides (3)         [+ Add] │
├──────────────────────────────────────┤
│ ☑ +2,000 rev_product_sales Y3        │
│   organic                            │
│   "Big contract win"          [⋮]   │
├──────────────────────────────────────┤
│ ☑ -100 opex_travel Y2                │
│   one_shot                           │
│   "Cost cut campaign"         [⋮]   │
├──────────────────────────────────────┤
│ ☐ +500 capex Y1                      │
│   organic                            │
│   "Plant upgrade"             [⋮]   │
│   (deactivated)                     │
└──────────────────────────────────────┘
```

### Add override modal

```
┌─────────────────────────────────┐
│ Add override                     │
├─────────────────────────────────┤
│                                  │
│ Voice: [▼ pl.rev.gross...     ] │
│ Year:  ( ) Y1  ( ) Y2  (•) Y3   │
│                                  │
│ Delta amount (EUR 000):          │
│ [ +2000 _________________ ]      │
│                                  │
│ Nature:                          │
│ (•) Organic                      │
│     Costs, AR, taxes propagate  │
│ ( ) One-shot                     │
│     Only this voice + cash      │
│                                  │
│ Note (optional):                 │
│ [ Big contract win Q3 2026 ]     │
│                                  │
│ [ Cancel ]              [ Add ]  │
└─────────────────────────────────┘
```

## Acceptance criteria

### Path 9.1 (assumption modify)
1. Utente modifica assumption → "Model dirty"
2. Refresh → run completo → snapshot updated
3. UI riflette nuovi numeri

### Path 9.2 (method change)
1. Utente cambia metodo → compatibility check
2. Se driver mancanti → reindirizzato a Flow 05
3. Se assumption diverse → vecchie eliminate, nuove pre-popolate
4. Refresh → run

### Path 9.3 (historical modify)
1. Utente modifica balance value Y0 → re-validation auto
2. KPI storici ricalcolati
3. Quality score aggiornato
4. Refresh → run con nuovo anchor

### Path 9.4 (override)
1. Add override organic +2000 ricavi Y3 → auto-run → cogs/ar/cash aggiornati
2. Add override one_shot +5000 ricavi Y2 → auto-run → solo ricavi Y2 + cash
3. Disattiva override → auto-run → modello torna allo stato precedente
4. Multipli override coesistono e si sommano

## Edge cases

- **Override su voce skipped in mapping**: errore 422
- **Override su voce derived/subtotal**: rifiutato con messaggio guidance
- **Override su year non in horizon**: errore 422
- **Override eccessivo che porta a ebt negativo enorme**: ammesso, ma warning visibile
- **Loop di override** (utente disattiva e riattiva): trigger run per ogni cambio, batch se >5 in <1s

## Test cases

- TC-09-01: modifica assumption → refresh → snapshot updated
- TC-09-02: cambio metodo richiede driver → redirect Flow 05
- TC-09-03: modifica balance Y0 → re-validation + re-KPI auto-trigger
- TC-09-04: override organic +2000 rev Y3 → cogs/AR/cash propagated
- TC-09-05: override one_shot +5000 rev Y2 → solo rev + cash, anni successivi invariate
- TC-09-06: override su EBITDA → rifiutato con messaggio
- TC-09-07: 3 override attivi simultaneamente → tutti applicati additivamente
- TC-09-08: disattiva override → snapshot torna senza quel delta
