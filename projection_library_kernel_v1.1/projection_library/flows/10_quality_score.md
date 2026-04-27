# Flow 10 — Quality Score (calcolo + visualizzazione)

## Scopo

Quantificare la "qualità" del piano in un singolo numero 0-100 + 4 sub-score, per dare all'utente un'idea sintetica di quanto affidabile è la proiezione che sta guardando.

Il quality score **non è un giudizio sul business** — è un giudizio sulla **robustezza analitica** del modello: quanti dati storici, quanto completi, quanto coerenti, quanto i metodi sono ben calibrati sui dati disponibili.

## Trigger

- Calcolato automaticamente dopo Flow 03 (validation + KPI storici), prima ancora di method selection
- Ricalcolato automaticamente dopo:
  - Modifica balance (Path 9.3)
  - Method selection completata (Flow 04)
  - Driver intake completato (Flow 05)
- Visibile sempre in topbar (Flow 08), aggiornato dopo ogni run

## Formula score totale

```
quality_score = (
    0.25 × score_history +
    0.30 × score_completeness +
    0.20 × score_consistency +
    0.25 × score_method_calibration
)
```

Range: 0-100. Pesi confermati da utente (Q2).

## Sub-score

### 1. Score history (peso 25%)

Misura quanti anni storici LFL sono disponibili.

```
years_lfl_count = numero anni in [Y-3, Y-2, Y-1, Y0] con lfl_flag = true

score_history =
  100 se years_lfl_count >= 4
  90  se years_lfl_count == 3
  70  se years_lfl_count == 2
  40  se years_lfl_count == 1   (solo Y0)
  0   se years_lfl_count == 0   (impossibile, Y0 obbligatorio)
```

Anni flaggati `not LFL` contribuiscono **a metà peso**: contano 0.5 invece di 1.0 nel computo. Esempio: Y-3 LFL + Y-2 not-LFL + Y-1 LFL + Y0 LFL → count = 3 + 0.5 = 3.5 → score interpolato tra 90 e 100 = 95.

### 2. Score completeness (peso 30%)

Misura quanto granulare è il bilancio rispetto a ciò che il sistema è in grado di gestire (TIER level).

```
required_voices = voci_attive_per_tier_level
mapped_voices_count = voci con mapping confermato (non skipped)
mapped_voices_in_required = mapped che intersecano required

base_completeness = mapped_voices_in_required / required_voices

# Penalty: voci critiche skipped (revenue, cogs aggregato, cash, equity)
critical_voices_missing = count voci skipped tra critical_set
critical_penalty = critical_voices_missing × 10

score_completeness = max(0, base_completeness × 100 - critical_penalty)
```

Il `critical_set` include: 
- almeno una voce revenue gross o net
- almeno una voce COGS (puntuale o aggregata)
- bs.nfp.cash o equivalent
- bs.equity (almeno share_capital o retained_earnings)
- almeno un asset class (FA tangible o NWC)

### 3. Score consistency (peso 20%)

Misura quante validation issue ci sono nel report storico (Flow 03 + post-mapping).

```
validation_block_count = count issue severity=block
validation_error_count = count issue severity=error
validation_warning_count = count issue severity=warning

# Block presenti = score 0 (block bloccano avanzamento, ma se utente bypassa via fix manuale)
if validation_block_count > 0:
    score_consistency = 0
else:
    base = 100
    base -= validation_error_count × 8     # ogni error costa 8 punti
    base -= validation_warning_count × 2   # ogni warning costa 2 punti
    score_consistency = max(0, base)
```

### 4. Score method calibration (peso 25%)

Misura quanto bene i metodi scelti sono "alimentati" dai dati disponibili.

```
total_voices_with_method = count method_configs attivi
weighted_calibration = 0
total_weight = 0

for each method_config:
    voice_weight = 1.0  # tutti voci pesano uguale (semplificazione pilot)
    
    # calibration component:
    # - 1.0 se metodo ha tutti driver disponibili e KPI default ha calibration_score >= 0.7
    # - 0.7 se metodo applicabile con fallback (qualche driver mancante o calib_score 0.4-0.7)
    # - 0.4 se metodo applicabile ma con calibrazione debole (calib_score < 0.4 o solo Y0)
    # - 0.0 se metodo non applicabile (skipped/not_applicable)
    
    calibration_component = compute_calibration_component(method_config)
    weighted_calibration += voice_weight × calibration_component
    total_weight += voice_weight

if total_weight == 0:
    score_method_calibration = 0
else:
    score_method_calibration = (weighted_calibration / total_weight) × 100
```

`compute_calibration_component(method_config)`:
- Verifica disponibilità di tutti i driver dichiarati nel metodo (in `drivers` table)
- Verifica `calibration_score` del KPI di default (se metodo basato su KPI)
- Verifica `calibration_min_history` del metodo vs anni LFL disponibili

## Soglie e classificazione

```
score >= 90 → "Full"           (verde scuro)
score 70-89 → "Solid"           (verde)
score 50-69 → "Acceptable"      (giallo)
score 30-49 → "Directional"     (arancione)
score < 30  → "Insufficient"    (rosso)
```

Soglie confermate da utente (Q2).

Conseguenze comportamentali (output presentation):

- **Full / Solid**: nessuna disclaimer particolare nell'output
- **Acceptable**: footer con disclaimer "Plan based on limited historical data — directional view"
- **Directional**: disclaimer rinforzato "Limited historical baseline — outputs must be validated against management knowledge"
- **Insufficient**: warning rosso permanente "Plan quality below threshold — engine outputs are highly uncertain"

Le soglie **non bloccano** l'esecuzione. L'utente è informato e procede.

## Persistence

Tabella `quality_scores`:

```sql
quality_scores (
  id UUID PK,
  project_id UUID FK,
  score_total NUMERIC,
  score_history NUMERIC,
  score_completeness NUMERIC,
  score_consistency NUMERIC,
  score_method_calibration NUMERIC,
  classification TEXT,        -- 'Full' | 'Solid' | 'Acceptable' | 'Directional' | 'Insufficient'
  components_detail JSON,     -- breakdown dettagliato per debug/explain
  computed_at TIMESTAMP
)
```

`components_detail` contiene il calcolo step-by-step:
```json
{
  "history": {
    "years_lfl_count": 3.5,
    "score": 95
  },
  "completeness": {
    "required": 149,
    "mapped_in_required": 134,
    "base": 89.9,
    "critical_missing": 0,
    "score": 90
  },
  "consistency": {
    "blocks": 0,
    "errors": 2,
    "warnings": 5,
    "score": 74
  },
  "method_calibration": {
    "configs": 142,
    "available": 95,
    "available_with_fallback": 35,
    "weak": 12,
    "skipped": 0,
    "weighted_avg": 0.78,
    "score": 78
  }
}
```

## API

### `POST /api/projects/{id}/quality-score`

Esegue calcolo, salva. Idempotente.

**Response 200**:
```json
{
  "score_total": 84,
  "classification": "Solid",
  "sub_scores": {
    "history": 95,
    "completeness": 90,
    "consistency": 74,
    "method_calibration": 78
  },
  "weights": {
    "history": 0.25,
    "completeness": 0.30,
    "consistency": 0.20,
    "method_calibration": 0.25
  },
  "components_detail": {...},
  "computed_at": "..."
}
```

### `GET /api/projects/{id}/quality-score`

Ritorna score corrente.

## Frontend

### Topbar badge

Sempre visibile. Click → modal espanso.

```
[ Quality: 84/100 — Solid ●●●●○ ]
```

Colori:
- Verde scuro: 90+
- Verde: 70-89
- Giallo: 50-69
- Arancione: 30-49
- Rosso: <30

### Modal espanso

```
┌────────────────────────────────────────────────────────┐
│ Quality Score                                           │
├────────────────────────────────────────────────────────┤
│                                                          │
│       ╭──────╮                                          │
│       │  84  │   Solid plan                             │
│       │      │   Outputs reliable for decision-making   │
│       ╰──────╯                                          │
│                                                          │
│  Breakdown:                                              │
│                                                          │
│  History (25% weight)                  95 ●●●●●         │
│   3.5 years LFL available                               │
│   [ Show details ▼ ]                                    │
│                                                          │
│  Completeness (30% weight)             90 ●●●●●         │
│   134 of 149 required voices mapped                     │
│   No critical voices missing                            │
│   [ Show details ▼ ]                                    │
│                                                          │
│  Consistency (20% weight)              74 ●●●○○         │
│   0 blocking issues                                      │
│   2 errors, 5 warnings                                  │
│   [ Show details ▼ ] → tab Validation                   │
│                                                          │
│  Method calibration (25% weight)       78 ●●●●○         │
│   142 method configs                                     │
│   95 fully calibrated                                    │
│   35 with fallback                                       │
│   12 weak calibration                                    │
│   [ Show details ▼ ]                                    │
│                                                          │
│  How to improve:                                         │
│   • Fix 2 accounting errors → +16 points                │
│   • Provide additional driver data → +8 points         │
│                                                          │
└────────────────────────────────────────────────────────┘
```

### Componenti

- shadcn `Dialog`, `Progress`, `Badge`
- Sezione "How to improve" cliccabile (link al flow corrispondente)

## Acceptance criteria

1. Quality score calcolato dopo Flow 03 e visibile in topbar
2. Click su badge → modal con breakdown 4 sub-score
3. Pesi corretti (25/30/20/25)
4. Soglie correttamente applicate (Full/Solid/Acceptable/Directional/Insufficient)
5. "How to improve" suggerisce azioni concrete con punteggio impatto
6. LFL handling: not-LFL anni contano half weight in score_history
7. Score si aggiorna automaticamente dopo cambio dati storici / mapping / method config

## Edge cases

- **Solo Y0 caricato**: history score = 40, total ~50-60, classificazione "Acceptable"
- **Block presente** ma utente bypassa: consistency = 0, totale crolla, classificazione possibilmente "Directional"
- **Tutti metodi MANUAL/zero**: method_calibration alto (no calibrazione richiesta) ma piano poco informativo — accept come trade-off (non penalty extra)
- **Sector pack scelto ma metodi non sector-specific applicati**: accept, score normale
- **Project freshly created (no data)**: score non calcolato, badge mostra "—"

## Test cases

- TC-10-01: 4 anni LFL completi, mapping 100%, 0 issue → score totale ~95+
- TC-10-02: solo Y0, mapping incompleto, 0 issue → score ~50-60, classificazione "Acceptable"
- TC-10-03: dati ottimi ma 5 errors → consistency penalizzato, totale ~70-75
- TC-10-04: not-LFL flag su Y-2 → score_history pesato a metà per quell'anno
- TC-10-05: re-calc dopo cambio mapping → score updated
- TC-10-06: API ritorna `components_detail` per debug
