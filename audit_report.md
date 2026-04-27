# Audit Report — Projection_Library_Spec_v1.1.xlsx

Generato da `scripts/audit_excel.py` su `Projection_Library_Spec_v1.1.xlsx`
(`projection_library_kernel_v1.1/projection_library/`).

## 1. Conteggio righe dati per sheet

Esclusi titoli, sotto-titoli, righe vuote e note finali. La colonna "Header"
indica la riga in cui inizia l'intestazione delle colonne.

| Sheet                  | Righe totali | Colonne | Header | Righe dati |
| ---------------------- | -----------: | ------: | -----: | ---------: |
| 00_index               |           50 |       4 |      3 |         45 |
| 01_methods             |           97 |      10 |      4 |         91 |
| 02_voices              |          252 |      10 |      4 |        247 |
| 03_kpis                |           95 |       8 |      4 |         90 |
| 04_dependencies        |           54 |       7 |      4 |         46 |
| 05_validation          |           79 |       8 |      4 |         74 |
| 06_tier_matrix         |           40 |       6 |      4 |         35 |
| 07_sector_packs        |           53 |       7 |      5 |         41 |
| 08_approximations      |           26 |       8 |      4 |         21 |
| 09_exclusions_roadmap  |           47 |       8 |      4 |         41 |
| 10_decisions_log       |           90 |       6 |      4 |         85 |

## 2. 01_methods — split per sezione

Lo sheet non contiene una colonna `type`: la separazione tra metodi e
derived rules è fatta con marker testuali "Sezione A" / "Sezione B", ognuna
con il proprio header.

| Sezione                                                | Header | Righe dati |
| ------------------------------------------------------ | -----: | ---------: |
| Sezione A — Method Registry (62 metodi di proiezione)  |      4 |         62 |
| Sezione B — Derived Rules (19 regole contabili)        |     69 |         19 |
| **Totale archetipi**                                   |        |     **81** |

Le 10 righe restanti (91 − 81) sono la sezione "Note operative" finale.

## 3. 02_voices — valori unici

### `nature` (7 valori)

`driver`, `driver (slot)`, `driver (placeholder)`, `derived`,
`derived (identity)`, `reference`, `placeholder`

### `calc_phase` (14 valori)

`E1`, `E2`, `E3`, `E3.1`, `E4`, `E5`, `E6`, `E7`, `E7.5`, `E8`,
`E1 proxy / E3 final`, `E1 proxy / E3.1 final`,
`E4 proxy / E8 check`, `E7.5 final (E3 proxy)`

## 4. 03_kpis

90 righe dati (header in riga 4).

## 5. 05_validation — distribuzione `severity`

| Severity      | Righe |
| ------------- | ----: |
| warning       |    31 |
| error         |    26 |
| block         |    14 |
| info          |     2 |
| *(mancante)*  |     1 |
| **Totale**    |**74** |

## 6. Incongruenze rilevate

| # | Sheet         | Dichiarato (titolo)                                         | Effettivo  | Delta | Note |
| - | ------------- | ----------------------------------------------------------- | ---------: | ----: | ---- |
| 1 | 02_voices     | "Voice Registry — 207 voci modello (P&L 69 + SP 106 + CF 32)" |        247 |   +40 | Riga 3 ribadisce "207 voci totali: 94 driver + 93 derived + 12 reference + 8 placeholder" (somma = 207). Dati reali superano di 40 il valore dichiarato. |
| 2 | 02_voices     | 4 categorie di `nature` (driver / derived / reference / placeholder) |          7 |    +3 | I varianti `driver (slot)`, `driver (placeholder)`, `derived (identity)` non sono menzionati nel titolo. Possibile mappatura: tutti i `driver*` → 94 driver, tutti i `derived*` → 93 derived. Da confermare con un conteggio per categoria. |
| 3 | 03_kpis       | "KPI Registry — 87 KPI catalogati"                          |         90 |    +3 | 3 KPI in più rispetto al titolo. |
| 4 | 05_validation | "Validation Rules Registry — 73 regole in 7 categorie"      |         74 |    +1 | 1 regola in più rispetto al titolo. |
| 5 | 05_validation | Severity attese: `block / error / warning / info`           | 4 + 1 vuota |    +1 | 1 riga ha la colonna `severity` vuota e va corretta o classificata. |
| 6 | 01_methods    | "62 method_id + 19 derived_rule (81 archetipi)"             |     62 + 19 |     0 | Coerente. |

## 7. Azioni suggerite

1. **02_voices**: chiarire se le 247 voci attuali sostituiscono il target 207 o se c'è un sovra-popolamento da bonificare; aggiornare il titolo del foglio in entrambi i casi.
2. **02_voices `nature`**: definire se i suffissi `(slot)`, `(placeholder)`, `(identity)` vanno mantenuti come valori distinti o normalizzati nelle 4 categorie del titolo.
3. **03_kpis**: allineare il titolo a 90 KPI o rimuovere i 3 in eccesso.
4. **05_validation**: identificare la riga senza `severity` e completarla; aggiornare il titolo a 74.
5. Aggiungere lo script `scripts/audit_excel.py` alla pipeline come check di coerenza prima di ogni rilascio.
