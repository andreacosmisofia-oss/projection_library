# Flow 04 — Method selection (modalità expert + guided + ambition level)

## Scopo

L'utente sceglie il metodo di proiezione per ogni voce del modello. Il sistema pre-popola i default, l'utente conferma o modifica.

## Trigger

Dopo validation storica + KPI calc (Flow 03). Sistema pre-popola, utente arriva a pagina method selection.

## Modalità

3 modalità non mutuamente esclusive:

### Modalità Expert

Tabella completa: 207 voci × dropdown metodo. Default precompilato. Utente vede e modifica liberamente.

Per power user che sa già cosa vuole. Modalità default switch nella UI.

### Modalità Guided

Questionario dinamico per famiglia voce. Sistema chiede domande tipo:
- *"I tuoi ricavi sono prevalentemente: (a) prodotti fisici venduti a volume, (b) servizi a tempo, (c) abbonamenti, (d) contratti pluriennali?"*
- *"Per i costi del venduto, hai dati di volumi e prezzi unitari? (a) Sì per la maggior parte, (b) Solo per alcuni, (c) No"*
- *"Per il NWC, stai pianificando miglioramenti DSO/DIO/DPO?"*

In base alle risposte, sistema seleziona metodi e li applica alle voci. Utente vede risultato e può finalizzare o switchare a expert.

Per advisor non-power-user, junior, partner non-finance.

### Ambition level (Bronze/Silver/Gold)

Per ogni `sector_pack`, il sistema calcola **3 livelli di ambizione**:

- **Gold**: tutti i metodi sector-specific sono applicabili (es. SaaS gold = arr_bridge per subscription, cohort_buildup per customer modeling, ecc.)
- **Silver**: alcuni metodi sector-specific applicabili, fallback su standard per il resto
- **Bronze**: solo metodi standard, sector-specific tutti in fallback

Calcolo automatico in base ai dati caricati (TIER level + driver disponibili). Utente vede 3 card con:
- Score (% completion verso gold)
- Cosa manca per salire al livello superiore (lista driver da fornire)
- Pulsante "Apply this level"

Se utente sceglie Silver e vuole salire a Gold, deve tornare al Flow 05 (driver intake) per fornire i driver mancanti.

## Logica

### 1. Pre-populate default

Per ogni `voice_id` attiva (escluse skipped in mapping, escluse disabled da sector_pack):

```python
def determine_default_method(voice: VoiceSpec, sector_pack: SectorPack) -> str:
    # 1. Override da sector pack (se presente)
    if voice.voice_id in sector_pack.method_overrides:
        return sector_pack.method_overrides[voice.voice_id]
    # 2. Default da voice_registry
    return voice.default_method
```

### 2. Compatibility check

Per ogni `(voice_id, method_id)` configurato, calcola compatibility:

```python
def check_compatibility(
    voice_id: str,
    method_id: str,
    available_data: AvailableData
) -> CompatibilityResult:
    """
    Returns one of:
    - 'available': metodo applicabile, tutti i dati ci sono
    - 'available_with_fallback': metodo applicabile ma calibrazione su pochi anni
    - 'requires_drivers': mancano driver TIER 3-4, devono essere caricati
    - 'not_applicable': impossibile (es. arr_bridge senza subscription voice mappata)
    """
```

Logica:
- Verifica metodo esiste in registry e applicable_voices include voice_id
- Verifica se il sector è compatibile (`method.applicable_sectors`)
- Verifica calibration_min_history vs anni storici disponibili
- Verifica driver TIER 3-4 disponibili (lookup in `drivers` table)
- Verifica voci dipendenti (per ratio: denominator voice mappata?)

### 3. Guided mode logic

Questionario gerarchico per famiglia. Esempio per revenue:

```yaml
- question_id: revenue_main_type
  text: "Qual è la fonte principale dei ricavi?"
  options:
    - id: products
      text: "Vendita di prodotti"
      implies_methods:
        pl.rev.gross.product_sales: volume_price
        pl.rev.gross.service_revenue: manual_zero  # disable
    - id: services
      text: "Servizi a tempo"
      implies_methods:
        pl.rev.gross.service_revenue: headcount_unit_cost
        pl.rev.gross.product_sales: manual_zero
    - id: subscription
      text: "Abbonamenti / SaaS"
      implies_methods:
        pl.rev.gross.subscription: arr_bridge
        ...
      sets_sector_pack_hint: saas
    - id: project
      text: "Contratti pluriennali / progetto"
      implies_methods:
        pl.rev.gross.project_contract: backlog_conversion
```

Sistema raccoglie risposte → applica `implies_methods` → utente vede risultato.

### 4. Ambition level computation

```python
def compute_ambition_levels(project: Project, available_data: AvailableData) -> AmbitionLevels:
    """
    Returns Bronze/Silver/Gold scores.
    """
    pack = sector_packs[project.sector_pack]
    sector_specific_methods = [m for m in pack.method_overrides.values() if m not in standard_methods]
    
    applicable_count = 0
    for method in sector_specific_methods:
        compat = check_compatibility(..., method, available_data)
        if compat == "available":
            applicable_count += 1
    
    coverage = applicable_count / len(sector_specific_methods) if sector_specific_methods else 1.0
    
    if coverage >= 0.85: return Gold
    elif coverage >= 0.50: return Silver
    else: return Bronze
```

Output:
```json
{
  "current_level": "Silver",
  "scores": {"Bronze": 100, "Silver": 70, "Gold": 30},
  "missing_for_silver": [],
  "missing_for_gold": [
    {"method": "cohort_buildup", "missing_drivers": ["driver.saas.cohort_v2024_arpu"]},
    {"method": "pipeline_weighted", "missing_drivers": ["driver.{voice}.pipeline_phase_qualified"]}
  ]
}
```

### 5. Persistence

Tabella `method_configs`:
```json
{
  "id": "uuid",
  "project_id": "uuid",
  "voice_id": "pl.rev.gross.product_sales",
  "method_id": "volume_price",
  "method_technical_code": "M_OPD_001",
  "is_default": false,        // user override flag
  "configured_at": "...",
  "ambition_level": "Silver"  // se applicato via ambition
}
```

## API

### `POST /api/projects/{id}/methods/init`

Pre-popolamento default. Idempotente. Esegue applicazione sector_pack.

**Response 200**: lista method_configs creati.

### `GET /api/projects/{id}/methods`

Ritorna config corrente:

```json
{
  "configs": [
    {"voice_id": "pl.rev.gross.product_sales", "method_id": "volume_price", "compatibility": "requires_drivers"},
    ...
  ],
  "ambition_levels": {...},
  "compatibility_summary": {
    "available": 165,
    "available_with_fallback": 22,
    "requires_drivers": 15,
    "not_applicable": 5
  }
}
```

### `PUT /api/projects/{id}/methods/{voice_id}`

Body: `{"method_id": "..."}`. Cambia metodo per voce. Ricalcola compatibility.

### `POST /api/projects/{id}/methods/apply-ambition`

Body: `{"level": "Silver"}`. Applica metodi sector-specific compatibili con il livello.

### `POST /api/projects/{id}/methods/guided/answer`

Body: `{"question_id": "...", "answer_id": "..."}`. Salva risposta, ricalcola implies_methods.

### `GET /api/projects/{id}/methods/guided/next-question`

Ritorna prossima domanda da fare in modalità guided.

## Frontend

### UI Mode switcher

Tab in alto: `[ Guided ] [ Expert ] [ Ambition ]`

### UI Expert

Tabella con filtro per sezione, colonne:
- Voice ID + label canonica
- Sezione (P&L/SP/CF)
- Method dropdown (filtrato per applicable_voices)
- Compatibility indicator (verde/giallo/rosso)
- Required drivers (se rosso)

### UI Ambition

3 card affiancate (Bronze/Silver/Gold) con:
- Score badge
- Pulsante "Apply"
- Lista cosa manca per salire (link a Flow 05 Driver intake)

### UI Guided

Wizard passo-passo, una domanda alla volta. Progress bar.

## Acceptance criteria

1. Sistema pre-popola default per tutte le voci attive
2. Utente in expert mode può cambiare singola voce, sistema ricalcola compatibility
3. Ambition level computato correttamente in base ai dati
4. Guided mode produce config valida senza che utente veda i 207 voci
5. Cambio metodo che richiede driver mancanti → flag chiaro, link a Flow 05

## Edge cases

- **Sector_pack cambiato dopo method config**: sistema chiede conferma per riapplicare default
- **Voce skipped in mapping**: esclusa da method config
- **Metodo richiesto non in voice_registry.allowed_methods** (raro per bug registry): errore 422

## Test cases

- TC-04-01: init default → tutti voice attivi hanno method_config
- TC-04-02: cambio metodo via expert → DB aggiornato
- TC-04-03: applica ambition Gold con dati insufficienti → fallback automatico a Silver con warning
- TC-04-04: guided mode 5 domande → config valida coerente
- TC-04-05: sector_pack=saas, no driver SaaS caricati → Gold non disponibile, Silver max
