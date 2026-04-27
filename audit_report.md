# Audit Report — Projection_Library_Spec_v1.1.xlsx

Generato da `scripts/audit_excel.py` su `Projection_Library_Spec_v1.1.xlsx`
(`projection_library_kernel_v1.1/projection_library/`).

> **Nota di rettifica (versione corrente).** I conteggi di una versione
> precedente di questo report (247 voci e 74 regole) includevano per errore
> le righe footer `Totali: …` di ciascun foglio, che non sono dati ma
> metadati di sintesi. Lo script ora le filtra (insieme ad altre note che
> iniziano con `•`, `Note`, `Conteggio`). I numeri definitivi di seguito
> riportati coincidono con quanto i fogli stessi dichiarano nei loro footer
> `Totali`.

## 1. Conteggio righe dati per sheet

Esclusi titoli, sotto-titoli, righe vuote e righe note (prefissi
`•` / `Totali` / `Note` / `Conteggio`).

| Sheet                  | Righe totali | Colonne | Header | Righe dati |
| ---------------------- | -----------: | ------: | -----: | ---------: |
| 00_index               |           50 |       4 |      3 |         45 |
| 01_methods             |           97 |      10 |      4 |         83 |
| 02_voices              |          252 |      10 |      4 |    **246** |
| 03_kpis                |           95 |       8 |      4 |     **84** |
| 04_dependencies        |           54 |       7 |      4 |         46 |
| 05_validation          |           79 |       8 |      4 |     **73** |
| 06_tier_matrix         |           40 |       6 |      4 |         35 |
| 07_sector_packs        |           53 |       7 |      5 |         41 |
| 08_approximations      |           26 |       8 |      4 |         16 |
| 09_exclusions_roadmap  |           47 |       8 |      4 |         35 |
| 10_decisions_log       |           90 |       6 |      4 |         81 |

Su `01_methods` le 83 righe includono i 62 metodi della Sezione A, i 19
derived rules della Sezione B e 2 righe di intestazione di sezione
("Sezione A" / "Sezione B") che non vengono filtrate dai prefissi note.

## 2. 01_methods — split per sezione (definitivo)

Lo sheet non contiene una colonna `type`: la separazione tra metodi e
derived rules è fatta con i marker testuali "Sezione A" / "Sezione B",
ognuna con il proprio header.

| Sezione                                                | Header | Righe dati |
| ------------------------------------------------------ | -----: | ---------: |
| Sezione A — Method Registry (62 metodi di proiezione)  |      4 |     **62** |
| Sezione B — Derived Rules (19 regole contabili)        |     69 |     **19** |
| **Totale archetipi**                                   |        |     **81** |

Coerente con il titolo del foglio: `62 method_id + 19 derived_rule (81 archetipi)`.

## 3. 02_voices — count definitivo per `nature`

Totale righe dati reali: **246** (coincide con il footer del foglio
`Totali: 246 voci catalogate`). Tutte le 7 categorie di `nature`
rappresentano voci effettive del modello.

| nature                  | righe |
| ----------------------- | ----: |
| `derived`               |   108 |
| `driver`                |   103 |
| `reference`             |    23 |
| `placeholder`           |     8 |
| `driver (placeholder)`  |     2 |
| `driver (slot)`         |     1 |
| `derived (identity)`    |     1 |
| **Totale**              |**246**|

### Valori unici `calc_phase` (14)

`E1`, `E2`, `E3`, `E3.1`, `E4`, `E5`, `E6`, `E7`, `E7.5`, `E8`,
`E1 proxy / E3 final`, `E1 proxy / E3.1 final`,
`E4 proxy / E8 check`, `E7.5 final (E3 proxy)`

## 4. 03_kpis — count definitivo

**84 KPI catalogati** (header in riga 4, footer note escluse).

Lo sheet stesso lo conferma in due note finali:
- `Totali: 84 KPI catalogati (template parametrici instanziati on-demand)`
- `• Conteggio: 87 KPI come da Step 5 (questo elenco mostra 84 record incluse template).`

### Composizione: 80 KPI concreti + 4 template parametrici

I 4 template si istanziano on-demand su ogni voce dello stesso tipo (non
sono KPI placeholder o draft, sono pattern):

| kpi_id template                            | famiglia |
| ------------------------------------------ | -------- |
| `kpi.growth.<voice>_yoy`                   | growth   |
| `kpi.growth.<voice>_cagr_3y`               | growth   |
| `kpi.margin.<cogs_voice>_pct_revenue`      | margin   |
| `kpi.margin.<opex_voice>_pct_revenue`      | margin   |

### Distribuzione per `famiglia`

| famiglia        | righe |
| --------------- | ----: |
| margin          |    17 |
| nwc_days        |    14 |
| growth          |    10 |
| capex           |     9 |
| leverage        |     9 |
| sector_specific |     9 |
| return          |     4 |
| provisions      |     4 |
| tax             |     3 |
| employee        |     3 |
| equity          |     2 |
| **Totale**      |**84** |

## 5. 05_validation — distribuzione `severity` (definitivo)

**73 regole catalogate** (titolo, footer e dati concordi).

| Severity      | Righe |
| ------------- | ----: |
| warning       |    31 |
| error         |    26 |
| block         |    14 |
| info          |     2 |
| **Totale**    | **73**|

La riga "senza severity" segnalata nelle versioni precedenti era in realtà
il footer `Totali: 73 regole catalogate`, ora correttamente filtrato. Non
esistono regole con `severity` mancante.

## 6. Incongruenze rilevate (versione definitiva)

| # | Sheet         | Dichiarato (titolo)                                                | Effettivo  | Delta | Note |
| - | ------------- | ------------------------------------------------------------------ | ---------: | ----: | ---- |
| 1 | 02_voices     | "Voice Registry — 207 voci modello (P&L 69 + SP 106 + CF 32)"      |        246 |   +39 | Il footer del foglio dichiara 246 voci, in linea con i dati. Il titolo di testa (207) è disallineato. |
| 2 | 02_voices     | 4 categorie di `nature` (driver / derived / reference / placeholder) |          7 |    +3 | Le varianti `driver (slot)`, `driver (placeholder)`, `derived (identity)` sono voci reali del modello ma non sono dichiarate nel titolo. |
| 3 | 03_kpis       | "KPI Registry — 87 KPI catalogati"                                 |         84 |    −3 | Il foglio mostra 84 record (di cui 4 template). Lo sheet stesso documenta che il titolo "87" è il conteggio di Step 5 mentre il foglio elenca 84 archetipi. Da riconciliare: titolo o spec. |
| 4 | 05_validation | "Validation Rules Registry — 73 regole in 7 categorie"             |         73 |     0 | Coerente (titolo, footer, dati). |
| 5 | 01_methods    | "62 method_id + 19 derived_rule (81 archetipi)"                    |     62 + 19 |     0 | Coerente. |

## 7. Azioni suggerite

1. **02_voices**: aggiornare il titolo del foglio da "207 voci modello" a
   "246 voci modello" (oppure rivedere lo scope se il target era davvero
   207). Il sub-titolo "94 driver + 93 derived + 12 reference + 8 placeholder"
   va riallineato (i conteggi attuali per categoria sono nella sezione 3).
2. **02_voices `nature`**: decidere se mantenere le 3 varianti
   (`driver (slot)`, `driver (placeholder)`, `derived (identity)`) come
   categorie distinte o se normalizzarle nelle 4 originali; in entrambi i
   casi documentarlo nel titolo del foglio.
3. **03_kpis**: scegliere se allineare il titolo a 84 KPI catalogati o se
   completare il foglio fino a 87 record. Documentare esplicitamente i 4
   template parametrici.
4. **Pipeline**: eseguire `scripts/audit_excel.py` come pre-check ad ogni
   modifica strutturale del workbook per intercettare drift tra titolo,
   footer e dati.
