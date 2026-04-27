# Flow 01 — Data Intake (caricamento bilancio)

## Scopo

L'utente carica il bilancio gestionale dell'azienda (almeno Y0 actual). Il sistema parsa il file, estrae voci e valori per anno, presenta tabella di anteprima.

## Trigger

Dopo creazione progetto (Flow 00), utente arriva alla pagina del progetto e vede CTA "Upload balance".

## Casistiche supportate

Il pilot v1.1 gestisce 3 casistiche per il bilancio caricato:

### Case 1 — Solo gestionale (default, atteso 70%+ utenti)

Utente carica un file Excel/CSV con il bilancio gestionale dell'azienda. Granularità tipicamente media-alta (TIER 2). Dati orientati al management, non riconciliati con civilistico.

Percorso: utente carica file → parsing → mapping (Flow 02) → validation (Flow 03) → procede.

### Case 2 — Gestionale + Civilistico (advisor con due fonti)

Utente carica entrambi. Il civilistico serve per:
- Validation cross-source (Δ Net Income, Δ Total Equity)
- Estrazione dati fiscali più affidabili (current tax, DTA/DTL, NOL)

Il sistema **non riconcilia automaticamente**. Mostra solo le differenze. L'utente decide se intervenire.

### Case 3 — Solo civilistico (caso limite)

Utente non ha gestionale, solo bilancio civilistico. Casistica realistica per piccole imprese o aziende con cui l'advisor non ha relazione interna stretta.

Conseguenze automatiche:
- Granularità limitata a TIER 1 (P&L+SP aggregato)
- Solo metodi RATIO base, EXTRAPOLATION, MANUAL disponibili
- Quality score atteso < 50/100
- Output qualità "directional only"

Pilot v1.1 supporta i 3 casi ma **Milestone 3 implementa solo Case 1**. Case 2 e 3 sono Milestone 3.b.

## Formato di upload

### Excel template (atteso)

File `.xlsx` con un singolo sheet o più sheet (P&L, SP, CF separati ammessi). Convenzione minima:

| voice_label | voice_section | Y-3 | Y-2 | Y-1 | Y0 |
|---|---|---:|---:|---:|---:|
| Ricavi delle vendite | P&L | 1500 | 1700 | 1900 | 2100 |
| Costo del venduto | P&L | -800 | -890 | -990 | -1100 |
| ... | | | | | |

**Convenzioni**:
- `voice_label` libero, in italiano o inglese
- `voice_section` indicativa: `P&L`, `SP_assets`, `SP_liabilities`, `SP_equity`, `CF_operating`, `CF_investing`, `CF_financing` (se utente la fornisce, aiuta il mapper)
- Anni: minimo Y0. Anni precedenti opzionali, valori vuoti = `null`. Un anno è "presente" se almeno una voce ha valore non-null per quell'anno.
- Valori numerici, in unità (no migliaia/milioni implicit). Sign convention come l'utente lo ha (sistema lo normalizza in mapping).
- Nessun limite formale al numero di voci.

### CSV alternativo

Stesso schema, separatore `;` o `,`. Encoding UTF-8.

### File template scaricabile

Sistema fornisce template Excel scaricabile dalla UI di upload, con esempio precompilato.

## Logica

### 1. Upload file

L'utente carica via drag-drop o selezione file. Backend riceve multipart/form-data.

### 2. Parsing

`domain/intake/parser.py`:

```python
def parse_balance(file_bytes: bytes, source_type: str) -> ParsedBalance:
    """
    source_type: 'gestionale' | 'civilistico' | 'both'
    """
    # 1. Detect format (xlsx/csv/xls)
    # 2. Read all sheets (se xlsx)
    # 3. Identify header row (cerca colonne 'voice_label', 'voice_section', anni)
    # 4. Estrai righe non-empty
    # 5. Identifica anni presenti (colonne con almeno un valore non-null)
    # 6. Normalizza:
    #    - Numeri (rimuovi spazi, virgole come separatore decimale, etc.)
    #    - Voice_section a uppercase con prefissi standard
    # 7. Ritorna ParsedBalance
```

### 3. Validation upload

Subito dopo parsing, controlli sintattici:
- Almeno 1 voce con valore Y0 non-null → altrimenti errore "Y0 obbligatorio"
- Almeno 5 voci totali → altrimenti errore "bilancio troppo ridotto"
- Nessuna duplicazione di voice_label nello stesso voice_section → altrimenti warning

### 4. Persistence

Record in `balances`:
```json
{
  "id": "uuid",
  "project_id": "uuid",
  "source_type": "gestionale",
  "uploaded_at": "...",
  "raw_filename": "alpha_balance_2025.xlsx",
  "years_present": ["Y-1", "Y0"],
  "voice_count": 87
}
```

E records in `raw_voices`:
```json
[
  {"id": "...", "balance_id": "...", "voice_user_label": "Ricavi delle vendite", "voice_user_section": "P&L", "amount": 2100, "year": "Y0"},
  {"id": "...", "balance_id": "...", "voice_user_label": "Ricavi delle vendite", "voice_user_section": "P&L", "amount": 1900, "year": "Y-1"},
  ...
]
```

## Output

### Response API
```json
{
  "balance_id": "uuid",
  "source_type": "gestionale",
  "years_present": ["Y-1", "Y0"],
  "voice_count": 87,
  "voices": [
    {
      "user_label": "Ricavi delle vendite",
      "user_section": "P&L",
      "values": {"Y-1": 1900, "Y0": 2100}
    },
    ...
  ],
  "validation": {
    "errors": [],
    "warnings": [
      {"code": "DUPLICATE_LABEL", "message": "...", "context": {...}}
    ]
  }
}
```

### LFL flag

Frontend mostra checkbox "Mark Y-1 as not LFL with Y0" per ogni anno storico (esclusi Y0). Se utente marca un anno, viene salvato in `raw_voices.lfl_flag = false` per tutte voci di quell'anno. Conseguenze:
- I KPI calcolati su trend includendo quell'anno saranno marcati con icona di attenzione
- L'anno rimane visibile e usato in calcoli ma con avviso permanente

## API

### `POST /api/projects/{id}/balance/upload`

**Request**: multipart/form-data
- `file`: il file binario
- `source_type`: `gestionale | civilistico | both`

**Response 200**: oggetto sopra descritto.

**Response 422**: parsing error o validation block.

### `GET /api/projects/{id}/balance`

Ritorna balance corrente con voci.

### `DELETE /api/projects/{id}/balance/{balance_id}`

Permette di eliminare un balance e ricaricarne uno nuovo. Cascade delete su `raw_voices` e (se esistente) `mappings` correlati.

### `PATCH /api/projects/{id}/balance/{balance_id}/lfl`

Body:
```json
{"year": "Y-1", "lfl": false}
```

Marca anno come not-LFL.

### `GET /api/projects/{id}/balance/template`

Ritorna file Excel template scaricabile.

## Frontend

### UI Upload

```
┌──────────────────────────────────────────────────┐
│  Project: Alpha Plan 2026                         │
│  Step 1 of 6: Upload balance                     │
├──────────────────────────────────────────────────┤
│                                                   │
│  ┌────────────────────────────────────────────┐  │
│  │                                              │  │
│  │   Drop your balance file here               │  │
│  │   or click to browse                         │  │
│  │                                              │  │
│  │   Supported: .xlsx, .xls, .csv               │  │
│  │                                              │  │
│  │   [ Download template ]                      │  │
│  │                                              │  │
│  └────────────────────────────────────────────┘  │
│                                                   │
│  Source type:                                     │
│  (•) Management (gestionale)                     │
│  ( ) Statutory (civilistico)                     │
│  ( ) Both                                         │
│                                                   │
└──────────────────────────────────────────────────┘
```

### UI Preview post-upload

```
┌──────────────────────────────────────────────────┐
│  Balance uploaded: alpha_balance_2025.xlsx        │
│  Years present: Y-1, Y0   |   87 voices found    │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │ ☐ Mark Y-1 as not LFL with Y0              │ │
│  └─────────────────────────────────────────────┘ │
│                                                   │
│  Preview:                                         │
│  ┌──────────────────────┬─────────┬────────┐    │
│  │ Voice                │ Y-1     │ Y0     │    │
│  ├──────────────────────┼─────────┼────────┤    │
│  │ Ricavi delle vendite │  1,900  │  2,100 │    │
│  │ Costo del venduto    │   (890) │ (1,100)│    │
│  │ ...                  │   ...   │   ...  │    │
│  └──────────────────────┴─────────┴────────┘    │
│                                                   │
│  Warnings: 1 (1 duplicate label found)           │
│                                                   │
│  [ Re-upload ]                  [ Continue → ]   │
└──────────────────────────────────────────────────┘
```

### Componenti
- shadcn `Card`, `Button`, `RadioGroup`, `Alert`
- Upload drag-drop: react-dropzone
- Tabella preview: TanStack Table

## Acceptance criteria

1. Utente carica Excel valido → backend parsa → frontend mostra preview con voci e anni
2. File senza Y0 → errore esplicito
3. File con almeno Y0 e 5+ voci → accept
4. Duplicate labels → warning visibile, non blocca
5. Click "Continue" → naviga a Flow 02 (mapping)
6. Possibilità di re-upload → vecchio balance cancellato, nuovo creato
7. Template scaricabile dalla UI

## Edge cases

- **File corrotto**: errore parsing, messaggio comprensibile
- **File enorme** (>10 MB o >5000 voci): warning di performance, comunque accept
- **Encoding non-UTF-8** (CSV): tentare detection, fallback a latin-1, warning
- **Numeri con separatori italiani** ("1.500,00"): parser deve gestirli
- **Voci con label vuota o numeri come label**: skip riga + warning
- **Sheet multipli in Excel**: leggere tutti, concat. Se sheet name suggerisce sezione (es. "P&L"), usarla per voice_section.

## Test cases

- TC-01-01: upload Excel valido 87 voci 2 anni → success, 87 raw_voices in DB
- TC-01-02: upload file senza Y0 → 422
- TC-01-03: upload CSV con `;` separator e numeri italiani → success
- TC-01-04: upload file con duplicate → success + 1 warning
- TC-01-05: re-upload → vecchio balance e mappings cancellati
- TC-01-06: GET template → ritorna xlsx valido apribile
