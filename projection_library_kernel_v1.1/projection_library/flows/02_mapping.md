# Flow 02 — Mapping voci utente → voice_registry

## Scopo

Tradurre le voci del bilancio dell'utente (label libere) nelle voci canoniche del voice_registry del sistema (207 voci con `voice_id` strutturato). Il mapping è il prerequisito per validation, KPI calc, engine.

## Trigger

Dopo upload bilancio (Flow 01), utente arriva alla pagina mapping.

## Input

- `raw_voices` del progetto (output Flow 01)
- `voice_registry` (statico, da YAML)
- Mapping per-azienda esistente (se presente)

## Logica

### 1. Auto-suggest

`domain/intake/mapper.py`:

```python
def auto_suggest_mapping(
    raw_voices: list[RawVoice],
    sector_pack: str,
    company_name: str
) -> list[MappingSuggestion]:
    """
    Per ogni raw_voice, propone candidati voice_id ordinati per confidence.
    """
```

#### Strategie di matching (in ordine di priorità)

**a. Persistenza per azienda**
Se esiste mapping confermato per `company_name` precedente, usa direttamente quello con confidence = 1.0. L'utente vede icona "from previous project" e può confermare o cambiare.

**b. Synonym table**
Tabella statica (in `registries/voice_synonyms.yaml`) con sinonimi noti italiano + inglese:

```yaml
- voice_id: pl.rev.gross.product_sales
  synonyms_it: ["ricavi delle vendite", "ricavi vendite prodotti", "vendite prodotti", "ricavi prodotti"]
  synonyms_en: ["product sales", "product revenue", "sales of products", "merchandise sales"]
- voice_id: pl.cogs.materials.raw
  synonyms_it: ["acquisti materie prime", "materie prime", "costi per materiali"]
  synonyms_en: ["raw materials", "materials", "cost of materials"]
# ... per ogni voce
```

Match esatto (case-insensitive, accenti normalizzati) → confidence = 0.95.

**c. Fuzzy match**
Levenshtein distance / token-based similarity tra `voice_user_label` e ogni `voice.label_canonical` o synonym. Confidence = similarity ratio (0-1). Soglia minima per proporre = 0.6.

**d. Section hint**
Se `voice_user_section` è presente (es. "P&L", "SP_assets"), filtra candidati per sezione corrispondente. Boosta confidence di +0.1 per match in sezione, penalizza di -0.2 per mismatch.

**e. Sector pack hint**
Filtra voci attive nel sector pack scelto. Voci disabled dal pack escluse dai candidati.

#### Output per voce

```json
{
  "user_label": "Ricavi delle vendite",
  "user_section": "P&L",
  "candidates": [
    {"voice_id": "pl.rev.gross.product_sales", "confidence": 0.95, "reason": "synonym_match"},
    {"voice_id": "pl.rev.gross.service_revenue", "confidence": 0.45, "reason": "fuzzy"},
    {"voice_id": "pl.rev.gross_total", "confidence": 0.40, "reason": "fuzzy"}
  ]
}
```

### 2. Conferma utente

Utente vede tabella con auto-suggest. Per ogni voce può:
- Confermare il top-1 (default)
- Selezionare un altro candidato dal dropdown
- Marcare come "Skip" (voce non mappata, sarà esclusa dal piano)
- Mappare a una voce non in candidates (search libero nel voice_registry)

### 3. Validation post-mapping

Prima di confermare il mapping completo, sistema verifica:

- **Voci obbligatorie TIER 1**: alcune voci sono indispensabili (es. `pl.rev.net` o `pl.rev.gross_total` o singole voci che sommando danno gross_total). Se nessuna voce utente è mappata su voci che permettono di derivare un revenue totale, errore.
- **Quadratura macro**: se utente ha mappato voci asset e voci liability, sistema verifica che esista almeno una voce di equity. Senza equity, SP non quadra.
- **Cross-mapping**: una raw_voice mappata su una sola voice_id. Una voice_id può ricevere multiple raw_voices se utente esplicitamente vuole sommarle (caso: il bilancio utente ha 3 sotto-voci di "Acquisti materie prime" che vanno aggregate in `pl.cogs.materials.raw`).

### 4. Aggregazione multipla

Se più raw_voices mappano sulla stessa voice_id, sistema le **somma algebricamente** quando computa il valore della voice_id. UX: tabella mapping mostra "3 voices → pl.cogs.materials.raw" con espandibile.

### 5. Sign convention normalization

Sign convention IFRS Alternativa B richiede costi negativi, ricavi positivi.

Se utente carica bilancio con costi positivi (alcune aziende lo fanno), sistema:
- Detect: voci mappate su `pl.cogs.*`, `pl.opex.*`, `pl.da.*`, `pl.financial.interest_expense`, `pl.tax.*` se valori positivi → suggerisce flip
- Mostra all'utente: "Detected costs as positive values. Flip sign convention? [Yes / No]"
- Se Yes, applica `value = -abs(value)` durante storage finale (tabella `mapped_values`)
- Se No, lascia come da utente (DI_011 bloccherà più tardi)

### 6. Persistence

Tabella `mappings`:
```json
{
  "id": "uuid",
  "project_id": "uuid",
  "voice_user_label": "Ricavi delle vendite",
  "voice_user_section": "P&L",
  "voice_id_system": "pl.rev.gross.product_sales",
  "confidence": 0.95,
  "auto_suggested": true,
  "confirmed_by_user": true,
  "skipped": false
}
```

E tabella per-azienda `company_mappings` (chiave `company_name + voice_user_label`):
```json
{
  "id": "uuid",
  "company_name": "Alpha SpA",
  "voice_user_label": "Ricavi delle vendite",
  "voice_id_system": "pl.rev.gross.product_sales",
  "last_used_at": "2026-04-27..."
}
```

Quando utente conferma mapping, sistema upserta in `company_mappings` per riuso futuro.

## API

### `POST /api/projects/{id}/mapping/suggest`

Esegue auto-suggest, ritorna oggetto mapping suggerito:

```json
{
  "suggestions": [
    {
      "user_label": "Ricavi delle vendite",
      "user_section": "P&L",
      "candidates": [...]
    },
    ...
  ],
  "stats": {
    "total_voices": 87,
    "high_confidence": 65,    // > 0.85
    "medium_confidence": 15,  // 0.6-0.85
    "low_confidence": 5,      // < 0.6
    "no_match": 2
  }
}
```

### `PUT /api/projects/{id}/mapping`

Body: lista mapping confermati dall'utente.
```json
{
  "mappings": [
    {"user_label": "Ricavi delle vendite", "voice_id_system": "pl.rev.gross.product_sales", "skipped": false},
    {"user_label": "Voce esoterica", "voice_id_system": null, "skipped": true},
    ...
  ],
  "sign_flip_applied": true
}
```

Sistema valida (validation post-mapping), salva, ritorna risultato:
```json
{
  "saved": 87,
  "validation_issues": [],
  "ready_for_validation": true
}
```

### `GET /api/projects/{id}/mapping`

Ritorna mapping corrente.

## Frontend

### UI

```
┌────────────────────────────────────────────────────────────┐
│  Step 2 of 6: Map balance voices                            │
│  Mapped 65/87 voices automatically. Please review.         │
├────────────────────────────────────────────────────────────┤
│                                                              │
│  Filters: [▼ All confidence] [▼ All sections] [Search...]   │
│                                                              │
│  ┌─────────────────────────┬──────────────────────┬───────┐│
│  │ User voice              │ → Mapped to          │ Conf. ││
│  ├─────────────────────────┼──────────────────────┼───────┤│
│  │ Ricavi delle vendite    │ pl.rev.gross.        │ ●●●●● ││
│  │ (P&L)                   │ product_sales [▼]    │ 95%   ││
│  ├─────────────────────────┼──────────────────────┼───────┤│
│  │ Acquisti materie prime  │ pl.cogs.materials.   │ ●●●●● ││
│  │ (P&L)                   │ raw [▼]              │ 92%   ││
│  ├─────────────────────────┼──────────────────────┼───────┤│
│  │ Other revenue items     │ pl.rev.gross.other   │ ●●●○○ ││
│  │ (P&L)                   │ [▼]                  │ 65%   ││
│  ├─────────────────────────┼──────────────────────┼───────┤│
│  │ Voce esoterica          │ [Search... ▼]        │ ----- ││
│  │ (—)                     │ [ Skip this voice ]  │       ││
│  └─────────────────────────┴──────────────────────┴───────┘│
│                                                              │
│  Sign convention detected: costs as positive                │
│  ☑ Auto-flip costs to negative                              │
│                                                              │
│  Validation issues: 0                                        │
│                                                              │
│  [ ← Back ]                                  [ Confirm → ]  │
└────────────────────────────────────────────────────────────┘
```

### Componenti
- TanStack Table per la tabella mapping
- shadcn `Select` con search per dropdown voice_id
- Indicatore confidence: 5 dot colorati (verde/giallo/rosso)
- shadcn `Alert` per validation issues

## Acceptance criteria

1. Auto-suggest produce candidati per >80% delle voci comuni
2. Persistenza per-azienda funziona: secondo upload stessa azienda → mapping pre-confermato
3. Utente può modificare suggerimento, fare skip, fare aggregazione multipla
4. Sign flip detection funziona per casi standard
5. Validation post-mapping intercetta voci mancanti TIER 1
6. Confirm salva in DB e attiva Flow 03

## Edge cases

- **Voce con label vuota o numerica**: skippata in auto-suggest, utente la vede in lista come "Unrecognized" e può mappare manualmente
- **Stesso voice_id per più raw_voice**: ammesso (aggregazione), UI mostra count
- **Tutte voci skip**: errore "Mapping non valido, almeno revenue + costs + cash necessari"
- **Sector pack richiede voci specifiche** (es. saas richiede `pl.rev.gross.subscription`): se non mappata, warning ma non block

## Test cases

- TC-02-01: upload bilancio sample → suggest produce ≥80% confidence ≥0.85
- TC-02-02: secondo upload stessa company → tutte le mapping confermate auto da `company_mappings`
- TC-02-03: skip di tutte le voci P&L → validation block "no revenue mapped"
- TC-02-04: 3 voci mappate alla stessa voice_id → aggregazione corretta in valori
- TC-02-05: bilancio con costi positivi → detect + flip applicato → valori negativi nel storage
