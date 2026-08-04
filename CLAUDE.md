# ch-label-extractor

Estrae coppie (etichetta testuale, tag XBRL) dai bilanci bulk di Companies House (UK).
L'output è un dizionario `etichetta → tag` da usare come riferimento per il parser di
piani dei conti.

## Struttura

```
src/ch_labels/
  recon.py      # ricognizione indice bulk senza download
  fetch.py      # scarica un pacchetto mensile in raw/
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
# oppure: ch-recon
```
Elenca i pacchetti mensili disponibili con date e URL. Utile per scegliere cosa scaricare.

### 2. Download un pacchetto
```bash
python -m ch_labels.fetch
# oppure: ch-fetch [nome-parziale]
```
Scarica il pacchetto più recente in `raw/`. Supporta ripresa di download interrotti
(Range header). Un pacchetto mensile pesa indicativamente 3-8 GB.

### 3. Estrazione fatti
```bash
python -m ch_labels.extract
# oppure: ch-extract [nome-zip]
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
# oppure: ch-aggregate
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
# oppure: ch-taxonomy
```
Scarica e parsa la tassonomia FRC in `ref/`:
- `ref/frc_taxonomy.zip` — ZIP originale
- `ref/taxonomy_concepts.csv` — concetti con tipo e period_type
- `ref/taxonomy_labels.json` — etichette standard per concetto

## Fonti dati

### Companies House Bulk Accounts Data
- **Indice**: https://download.companieshouse.gov.uk/en_accountsdata.html
- **Formato nomi**: `Accounts_Monthly_Data-<Month><YYYY>.zip`
- **Contenuto**: ZIP di ZIP; ogni ZIP interno è un deposito (un'azienda).
  Ogni deposito contiene uno o più file XML/XHTML in formato iXBRL o XBRL.
- **Licenza**: Open Government Licence v3.0
  https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/
  Uso commerciale e di ricerca permesso con attribuzione.
- **Dimensione tipica**: 3–8 GB per pacchetto mensile compresso.
- **Cadenza**: aggiornamento mensile; archivi storici disponibili dal 2011 circa.
- **Proporzione iXBRL**: i depositi più recenti (dal 2020 circa) sono
  prevalentemente iXBRL; quelli precedenti sono plain XBRL.

### FRC XBRL Taxonomy
- **URL principale**: https://xbrl.frc.org.uk/taxonomy/current
- **ZIP diretto**: https://xbrl.frc.org.uk/taxonomy/current/taxonomy.zip
- Contiene le tassonomie UK GAAP (FRS 101/102/105), UK-adopted IFRS e
  Charities SORP. Ogni concetto ha un `name` attribute (il tag) e una
  o più etichette standard in inglese.

## Note tecniche

- I depositi iXBRL incorporano i fatti XBRL come attributi `name="prefix:Local"`
  su elementi `<ix:nonNumeric>` e `<ix:nonFraction>`. Il testo visibile
  dell'elemento è l'etichetta del redattore.
- La stessa etichetta appare in molti depositi: la frequenza è il segnale
  di qualità — etichette frequenti sono termine di settore consolidato.
- Non viene fatta nessuna normalizzazione: maiuscole, punteggiatura,
  spazi multipli rimangono intatti. La normalizzazione spetta al consumer
  del dizionario.
- Il filtro `INTERESTING_PREFIXES` in `extract.py` limita l'output ai tag
  di namespace rilevanti (uk-bus, uk-core, uk-direp, frs, hmrc, ifrs, …).
  Modificarlo se si vogliono catturare tag di altre tassonomie.

## Test

```bash
pytest tests/ -v
```

I test non richiedono rete né file reali. Usano un frammento iXBRL sintetico.

## Avvertenza sulla rete

I domini `download.companieshouse.gov.uk`, `www.gov.uk` e `xbrl.frc.org.uk`
devono essere raggiungibili. In ambienti con proxy restrittivi (come i container
Claude Code Remote) questi host potrebbero essere bloccati: eseguire il download
localmente e copiare i file in `raw/` manualmente.
