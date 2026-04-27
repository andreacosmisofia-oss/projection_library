# Flow 00 — Setup iniziale (configurazione progetto)

## Scopo

Step preliminare prima del caricamento bilancio. L'utente fornisce i parametri di configurazione che condizionano tutto il resto: settore, perimetro, currency, country, orizzonte, livello tier ambito.

## Trigger

L'utente clicca "New project" dalla home.

## Input richiesti

| Campo | Tipo | Pilot v1.1 | Note |
|-------|------|------------|------|
| `name` | string | obbligatorio | Nome progetto, libero |
| `company_name` | string | obbligatorio | Nome azienda (per persistence mapping per-azienda) |
| `sector_pack` | enum | obbligatorio | `generic | industrial | saas | retail | real_estate | services` |
| `perimeter` | enum | obbligatorio | `consolidated | legal_entity | cgu` |
| `currency` | enum | forzato a `EUR` | Multi-currency = improvement futuro |
| `country` | string ISO | obbligatorio | Per ETR default (es. `IT` → 24%) |
| `accounting_standard` | enum | forzato a `IFRS` | GAAP locale = improvement futuro |
| `horizon_years` | int | forzato a `3` | Y1-Y3 fisso pilot |
| `tier_level` | enum | obbligatorio | `minimum | standard | advanced` |

## Logica

### 1. Validazione input

- `sector_pack` deve essere uno dei 6 valori validi (registry sector_packs).
- `perimeter` deve essere uno dei 3 valori validi.
- `currency` = "EUR" forzato. Se utente prova altri valori, errore con messaggio "Multi-currency non supportato in pilot v1.1".
- `country` deve essere ISO 3166-1 alpha-2 valido. Default proposto: "IT".
- `tier_level` deve essere uno dei 3 valori. Default proposto: "standard".

### 2. Side effect del sector_pack

Una volta scelto il sector_pack, il sistema **non applica subito** gli override del pack. Gli override vengono applicati al momento della method selection (Milestone 6). In questa fase il sector_pack è solo registrato.

### 3. Side effect del tier_level

Il tier_level condiziona quali voci saranno richieste obbligatoriamente nel bilancio:
- `minimum` (TIER 0+1) → ~28 voci P&L+SP aggregate
- `standard` (TIER 0+1+2) → ~149 voci granulari
- `advanced` (TIER 0+1+2+3) → ~149 voci + driver industriali (TIER 3 base)

I sub-tier method-specific (TIER 4.A-L) vengono attivati dinamicamente in funzione dei metodi scelti, non del tier_level iniziale.

### 4. ETR default per country

Tabella default ETR per pilot v1.1 (configurabile poi):

| Country | ETR default |
|---------|-------------|
| IT | 24.0% (IRES) |
| FR | 25.0% |
| DE | 30.0% |
| UK | 25.0% |
| US | 21.0% |
| ES | 25.0% |
| (default altri) | 25.0% |

L'ETR può essere modificato dall'utente in fase assumption.

## Output

Record nella tabella `projects`:

```json
{
  "id": "uuid",
  "name": "Alpha Plan 2026",
  "company_name": "Alpha SpA",
  "sector_pack": "industrial",
  "perimeter": "consolidated",
  "currency": "EUR",
  "country": "IT",
  "accounting_standard": "IFRS",
  "horizon_years": 3,
  "tier_level": "standard",
  "etr_default": 0.24,
  "created_at": "2026-04-27T16:00:00Z",
  "updated_at": "2026-04-27T16:00:00Z"
}
```

## API

### `POST /api/projects`

**Request body**:
```json
{
  "name": "Alpha Plan 2026",
  "company_name": "Alpha SpA",
  "sector_pack": "industrial",
  "perimeter": "consolidated",
  "country": "IT",
  "tier_level": "standard"
}
```

**Response 201**: oggetto progetto creato (vedi sopra).

**Response 422**: validation error.

### `GET /api/projects/{id}`

Ritorna progetto.

### `PATCH /api/projects/{id}`

Modifica campi non-bloccati. Bloccati per pilot:
- `currency` (forzato EUR)
- `accounting_standard` (forzato IFRS)
- `horizon_years` (forzato 3)

Modificabili: `name`, `sector_pack`, `tier_level`, `country`, `perimeter`.

Attenzione: cambiare `sector_pack` o `tier_level` dopo aver caricato dati invalida i passi successivi (mapping, method selection). Sistema deve avvisare e chiedere conferma.

## Frontend

### UI

Wizard 1 step con form:

```
┌────────────────────────────────────────────────┐
│  New Project                                    │
├────────────────────────────────────────────────┤
│  Project name:    [_______________________]    │
│  Company name:    [_______________________]    │
│                                                 │
│  Sector pack:     [▼ Industrial          ]     │
│                                                 │
│  Perimeter:       (•) Consolidated             │
│                   ( ) Legal entity             │
│                   ( ) CGU                      │
│                                                 │
│  Country:         [▼ Italy (IT)         ]     │
│  Currency:        EUR (fixed in pilot)         │
│  Standard:        IFRS (fixed in pilot)        │
│  Horizon:         3 years (fixed in pilot)     │
│                                                 │
│  Tier level:      ( ) Minimum                  │
│                   (•) Standard                 │
│                   ( ) Advanced                 │
│                                                 │
│  Tier level info:                               │
│  Standard requires P&L+SP granular (~149      │
│  voices). You can upload data with less detail │
│  but some methods will not be available.       │
│                                                 │
│  [ Cancel ]                       [ Create ]   │
└────────────────────────────────────────────────┘
```

### Componenti shadcn/ui
- `Card`, `Input`, `Select`, `RadioGroup`, `Button`, `Form`

## Acceptance criteria

1. Utente clicca "New project" → form si apre.
2. Utente compila tutti i campi obbligatori → "Create" attivo.
3. Click "Create" → POST API → progetto creato → redirect a pagina progetto (Milestone 3 in poi).
4. Validation lato server: input non valido → form mostra errore.
5. Multi-currency: utente prova a settare USD via API → errore 422 con messaggio chiaro.
6. Lista progetti recenti accessibile da home.

## Edge cases

- **Doppio submit**: idempotency key per evitare creazione duplicate (può aspettare a milestone successive).
- **Project name duplicato**: ammesso, utente può avere più piani per stessa azienda.
- **Cambio sector_pack post-creation**: avvisare utente che invaliderà passaggi successivi.

## Test cases

- TC-00-01: crea progetto con tutti campi validi → 201, oggetto in DB.
- TC-00-02: crea progetto con sector_pack invalido → 422.
- TC-00-03: tenta currency=USD → 422 con messaggio "Multi-currency non supportato".
- TC-00-04: PATCH cambia sector_pack → ammesso, ma deve loggare warning.
- TC-00-05: GET lista progetti → ritorna lista paginata.
