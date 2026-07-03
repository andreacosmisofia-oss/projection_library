# Power Query — Bilancio DERA Abstract

Query M per estrarre **Conto Economico (IS)** e **Stato Patrimoniale (BS)** dal file:

```
C:\Users\andre\OneDrive\12. COASE\01a. AALTO\2026q1\dera abstract.xlsx
```

## File

| File | Scopo |
|---|---|
| `00_Discover_Sheets.pq` | Elenca tutti i fogli — **parti sempre da qui** |
| `01_IS_IncomeStatement.pq` | Estrae il foglio IS/P&L/Conto Economico |
| `02_BS_BalanceSheet.pq` | Estrae il foglio BS/Stato Patrimoniale |
| `03_Combined_IS_BS.pq` | IS + BS in un'unica tabella (per pivot/modello dati) |

## Come usare in Excel

1. Apri Excel → **Dati → Recupera dati → Da altre origini → Query vuota**
2. Si apre Power Query Editor → **Home → Editor avanzato**
3. Cancella il contenuto e incolla il codice del file `.pq` desiderato
4. Clicca **Fine** e poi **Chiudi e carica**

## Come usare in Power BI Desktop

1. **Home → Trasforma dati → Editor Power Query**
2. **Home → Nuova origine → Query vuota**
3. **Visualizza → Editor avanzato** → incolla il codice
4. **Chiudi e applica**

## Flusso consigliato

```
1. Esegui 00_Discover_Sheets  →  vedi i nomi esatti dei fogli
2. Se i nomi non corrispondono ai candidati predefiniti,
   aggiorna la lista "Candidates" in 01_IS o 02_BS
3. Carica 01_IS e 02_BS come "Solo connessione"
4. Usa 03_Combined per l'analisi aggregata
```

## Cosa fa ogni query

- **Auto-detect intestazione**: salta le righe vuote iniziali e usa
  la prima riga con ≥ 2 valori come header
- **Pulizia righe vuote**: elimina le righe completamente nulle
- **Tag "Conto"**: aggiunge una colonna `Conto` = `"IS"` o `"BS"`
  per distinguere i due conti quando uniti
- **Fallback multipli**: prova EN e IT per i nomi dei fogli
