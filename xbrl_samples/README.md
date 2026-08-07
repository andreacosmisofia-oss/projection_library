# XBRL Sample Files

Bilanci e report annuali in formato XBRL per società italiane, raccolti per uso come dati di test della `projection_library`.

## Struttura

```
xbrl_samples/
├── taxonomy_examples/          # File di esempio dalla tassonomia PCI 2018-11-04
│   ├── animeshon_03072020211-31122021.xbrl      # Bilancio reale (micro-impresa)
│   ├── oresteafrica_dimension.xml               # Modello dimensioni tassonomia
│   ├── oresteafrica_mapping.xml                 # Mapping codici cella → concetti XBRL
│   └── oresteafrica_report.xml                  # Schema tassonomia e reporting roles
├── esef/                       # Bilanci ESEF (inline XBRL) società quotate
│   ├── italian_esef_2023_index.csv              # Indice 162 filing ESEF italiani FY2023
│   ├── DOWNLOAD_INSTRUCTIONS.txt               # URL diretti per 10 società target
│   ├── np3fastigheterab-2022-12-31-sv_EXAMPLE.zip  # Esempio struttura ESEF (Svezia)
│   └── sap-2022-12-31-de_EXAMPLE.zip              # Esempio struttura ESEF (Germania)
└── download_esef.py            # Script per scaricare i file ESEF italiani
```

---

## Formato 1 — Bilanci PCI (tassonomia italiana, PMI)

Tassonomia: **PCI 2018-11-04** (InfoCamere namespace `http://www.infocamere.it/itnn/fr/itcc/ci/`)

Obbligatoria per tutte le società italiane soggette al Codice Civile (SRL, SpA, cooperative, ecc.).  
Banche e assicurazioni sono **escluse per legge** da questo corpus.

### File incluso: `animeshon_03072020211-31122021.xbrl`

- **Società:** Animeshon S.r.l. (CF: 03072020211), Gargazzone (BZ)
- **Forma:** Micro-impresa (Art. 2435-ter C.C.) — schema `itcc-ci-micr-2018-11-04.xsd`
- **Periodi:** FY 2021 (corrente) + FY 2020 (confronto)
- **Contenuto:** Dati anagrafici, stato patrimoniale, conto economico, note in HTML
- **Totale attivo FY2021:** €120.027 — Utile d'esercizio: €16.800

### Varianti tassonomia disponibili

| Schema XSD | Applicazione |
|---|---|
| `itcc-ci-ese-2018-11-04.xsd` | Bilancio completo (Art. 2424 C.C.) + Nota Integrativa |
| `itcc-ci-micr-2018-11-04.xsd` | Micro-imprese (Art. 2435-ter C.C.) |
| `itcc-ci-abb-2018-11-04.xsd` | Bilancio abbreviato (Art. 2435-bis C.C.) |
| `itcc-ci-cons-2018-11-04.xsd` | Bilancio consolidato |

### Come ottenere altri bilanci PCI

I bilanci depositati al Registro delle Imprese non sono a scaricamento gratuito pubblico:

- **Singolo bilancio:** acquisto su [registroimprese.it](https://www.registroimprese.it) (~€6–12)
- **Accesso gratuito:** solo per il legale rappresentante via [impresa.italia.it](https://impresa.italia.it) (con SPID/CIE)
- **Accesso bulk B2B:** contratto con InfoCamere — [accessoallebanchedati.registroimprese.it](https://accessoallebanchedati.registroimprese.it)
- **Corpus di ricerca:** ~1 milione di bilanci/anno disponibili via API InfoCamere

---

## Formato 2 — Bilanci ESEF (inline XBRL, società quotate)

Tassonomia: **ESEF / IFRS** (obbligo EU dal FY2021 per tutte le società quotate su mercati regolamentati UE)

Registro pubblico: [filings.xbrl.org](https://filings.xbrl.org) (XBRL International)

### Società italiane con URL confermato (FY2023)

| Società | Settore | LEI | File |
|---|---|---|---|
| Brembo SpA | Componentistica auto | `549300BLWVJN2BAT0A44` | `brembo-2023-esef.zip` |
| Recordati SpA | Farmaceutico | `815600FBF92FD3531704` | `recordati-2023-esef-en.zip` |
| Reply SpA | IT services | `815600DAEFB0388F3521` | `reply-2023-esef.zip` |
| Datalogic SpA | Tecnologia/ottica | `815600A033443037ED66` | `datalogic-2023-esef.zip` |
| Campari Group | Bevande | `213800ED5AN2J56N6Z02` | `campari-2023-esef.zip` |
| Amplifon SpA | Dispositivi medici | `ZYXJDNVM2JI3VBM8G556` | `amplifon-2022-esef.zip` |

### Scaricare i file ESEF

```bash
# Da una rete senza restrizioni
python xbrl_samples/download_esef.py --out-dir xbrl_samples/esef/
```

Lo script scarica tutti i file con URL noto da `filings.xbrl.org` (archivio pubblico XBRL International).

In alternativa, i file sono cercabili su:
- [filings.xbrl.org](https://filings.xbrl.org) → filtro paese: IT
- [emarketstorage.it](https://www.emarketstorage.it/) — OAM italiano
- [1info.it](https://www.1info.it/) — OAM italiano
- Pagine Investor Relations di ciascuna società

### Struttura di un pacchetto ESEF

Vedere `np3fastigheterab-2022-12-31-sv_EXAMPLE.zip` o `sap-2022-12-31-de_EXAMPLE.zip` per la struttura tipo:

```
<lei>-<year>/
├── META-INF/
│   ├── catalog.xml
│   └── taxonomyPackage.xml
├── reports/
│   └── <company>-<year>.xhtml   ← inline XBRL (HTML + tag iXBRL)
└── <company>/                   ← extension taxonomy
    ├── <company>-<year>.xsd
    └── ...
```

---

## Note sulla disponibilità

I bilanci XBRL del Registro delle Imprese (formato PCI) **non sono liberamente accessibili** al pubblico generico — si scaricano a pagamento o con credenziali SPID del rappresentante legale.

I bilanci ESEF delle società quotate italiane sono **pubblici** su `filings.xbrl.org` ma non accessibili da ambienti con proxy restrittivi (dominio bloccato a livello di policy di rete).

L'unico file XBRL PCI reale trovato su GitHub pubblico è il bilancio di Animeshon S.r.l., pubblicato dall'azienda stessa nel proprio repository come esempio di trasparenza.
