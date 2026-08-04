# ch-label-extractor

Estrae coppie (etichetta testuale, tag XBRL) dai bilanci bulk di Companies House (UK).
L'output è un dizionario `etichetta → tag` da usare come riferimento per il parser di
piani dei conti.

## Struttura

```
src/ch_labels/
  recon.py      # ricognizione indice bulk senza download
  fetch.py      # scarica un pacchetto giornaliero o mensile in raw/
  extract.py    # estrae fatti da iXBRL/XBRL
  aggregate.py  # produce il dizionario finale
  taxonomy.py   # scarica e parsa la tassonomia FRC

raw/            # ZIP originali (esclusi da git)
out/            # parquet e CSV estratti (esclusi da git)
ref/            # tassonomia FRC scaricata
tests/          # unit test (no rete, no file)
```

## Installazione

```bash
pip install -e .
```

Dipendenze: `lxml`, `polars`, `httpx`, `tqdm`, `rich`

## Flusso operativo

### 1. Ricognizione (nessun download)
```bash
python -m ch_labels.recon
```
Elenca i pacchetti disponibili con date e URL.

### 2. Download

**Punto di partenza consigliato — file giornaliero (~30 MB):**
```bash
python -m ch_labels.fetch --daily
```

**File mensile (~500 MB–2,4 GB):**
```bash
python -m ch_labels.fetch --monthly
# oppure con nome esplicito:
python -m ch_labels.fetch --monthly October2024
```

I file vengono salvati in `raw/`. Il download supporta ripresa (Range header).

### 3. Estrazione fatti
```bash
python -m ch_labels.extract
# oppure su un file specifico:
python -m ch_labels.extract Accounts_Bulk_Data-2025-07-01.zip
```
Processa il ZIP in `raw/` e scrive `out/facts_<nome>.parquet`.

Schema del parquet:
| colonna | tipo | note |
|---|---|---|
| label | str | testo come appare nel documento |
| tag | str | `prefix:LocalName` con namespace prefix |
| value | str | valore del fatto |
| unit | str | valuta/unità (GBP, shares, …) |
| period | str | data istante o intervallo `YYYY-MM-DD/YYYY-MM-DD` |
| doc_type | str | full / abridged / filleted / micro / small / unknown |
| company_size | str | micro / small / medium / large / unknown |
| source_file | str | nome del file XML all'interno del ZIP |

### 4. Aggregazione → dizionario
```bash
python -m ch_labels.aggregate
```
Legge tutti i `facts_*.parquet` in `out/` e scrive:
- `out/dictionary.parquet` — coppie (label, tag) con frequenze
- `out/dictionary.csv` — stessa cosa in CSV

Schema dizionario:
| colonna | tipo | note |
|---|---|---|
| label | str | etichetta testuale |
| tag | str | tag XBRL |
| freq | int | occorrenze di questa coppia esatta |
| tag_freq | int | occorrenze totali del tag (tutte le etichette) |
| label_rank | int | rango dell'etichetta per questo tag (1 = più frequente) |

### 5. Tassonomia FRC
```bash
python -m ch_labels.taxonomy
```
Scarica e parsa la tassonomia FRC in `ref/`:
- `ref/frc_taxonomy.zip` — ZIP originale
- `ref/taxonomy_concepts.csv` — concetti con tipo e period_type
- `ref/taxonomy_labels.json` — etichette standard per concetto

---

## Fonti dati

### Companies House Bulk Accounts Data

**Tre portali di download** (accesso pubblico, nessuna autenticazione):

| Portale | URL | Contenuto |
|---|---|---|
| Giornaliero | `https://download.companieshouse.gov.uk/en_accountsdata.html` | ultimi 60 giorni |
| Mensile (12 mesi) | `https://download.companieshouse.gov.uk/en_monthlyaccountsdata.html` | ultimi 12 mesi |
| Storico dal 2008 | `https://download.companieshouse.gov.uk/historicmonthlyaccountsdata.html` | archivio completo |

**Pattern URL dei file:**

```
# Giornaliero
https://download.companieshouse.gov.uk/Accounts_Bulk_Data-YYYY-MM-DD.zip

# Mensile
https://download.companieshouse.gov.uk/Accounts_Monthly_Data-[MonthName][Year].zip
# es: Accounts_Monthly_Data-October2024.zip
```

**Dimensioni tipiche:**

| Tipo | Compresso | Non compresso |
|---|---|---|
| Giornaliero | ~30 MB | ~300 MB |
| Mensile (media) | ~500 MB | ~5 GB |
| Mensile (picco: settembre/dicembre) | fino a 2,4 GB | ~24 GB |

**Contenuto di ogni ZIP:**
- ~97% file iXBRL (estensione `.html`) — formato prevalente dal 2011 in poi
- ~3% plain XBRL (estensione `.xml`) — depositi più vecchi
- Struttura: ZIP di ZIP; ogni ZIP interno è un deposito di una società

**Note operative sui file mensili:**
I file mensili hanno avuto problemi di disponibilità da dicembre 2023 per buona parte del 2024.
I file giornalieri non sono mai stati interrotti. Prima di usare i mensili, verificare lo
stato attuale sul forum: `https://forum.companieshouse.gov.uk/c/data-issues/20`

**Licenza:** Open Government Licence v3.0
`https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/`
Uso commerciale, combinazione con altri dati e redistribuzione sono permessi.
Unico obbligo: attribuzione a Companies House con link alla licenza.

### FRC XBRL Taxonomy

Il FRC pubblica suite tassonomiche annuali. Ogni suite copre UK GAAP (FRS 101/102/105),
UK-adopted IFRS, UK SEF e Charities SORP.

| Suite | Stato | URL pagina download |
|---|---|---|
| 2026 | Corrente | `https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/frc-taxonomies/current-frc-taxonomy-suites/2026-frc-taxonomy-suite/` |
| 2025 | Corrente | `https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/frc-taxonomies/current-frc-taxonomy-suites/2025-frc-taxonomy-suite/` |
| Storiche | Archivio | `https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/frc-taxonomies/historical-frc-taxonomy-suites/` |

Il ZIP della tassonomia contiene: file `.xsd` (schemi), `.xml` (linkbase label/presentation/
calculation/definition), `changelog.pdf` e mapping Excel con le variazioni rispetto all'anno
precedente. Non esiste un URL diretto pubblico: il link si trova nella pagina della suite.

Contatto FRC per questioni tecniche: `xbrl@frc.org.uk`

---

## Note tecniche

- I depositi iXBRL incorporano i fatti XBRL come attributo `name="prefix:Local"`
  su elementi `<ix:nonNumeric>` e `<ix:nonFraction>`. Il testo visibile è l'etichetta
  del redattore — non normalizzata, esattamente come la si trova nel documento.
- I file giornalieri (martedì–sabato mattina, ~5.000 depositi/giorno) coprono 3 giorni
  di depositi (il martedì copre sabato + domenica + lunedì).
- Il filtro `INTERESTING_PREFIXES` in `extract.py` limita l'output ai namespace
  rilevanti (uk-bus, uk-core, uk-direp, frs, hmrc, ifrs, …). Modificarlo per
  catturare tag di altre tassonomie.
- Nessuna normalizzazione delle etichette in fase di estrazione: maiuscole, punteggiatura
  e spazi multipli rimangono intatti. La normalizzazione spetta al consumer del dizionario.

## Test

```bash
pytest tests/ -v
```

I test non richiedono rete né file reali (7/7 pass).

## Avvertenza sulla rete

I domini `download.companieshouse.gov.uk` e `frc.org.uk` devono essere raggiungibili.
In ambienti con proxy restrittivi (container Claude Code Remote) questi host sono bloccati
per policy: eseguire i download localmente e copiare i file in `raw/` e `ref/`.
