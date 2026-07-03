// ================================================================
// QUERY 3 — COMBINED: IS + BS in un'unica tabella
// Utile per pivot, analisi aggregate, o caricamento in un modello dati.
//
// Prerequisiti: le query 01_IS e 02_BS devono essere già caricate
// come "Query solo connessione" (Connection Only) nel tuo file Excel/PBI.
// In alternativa, usa questa query standalone che ripete la logica.
// ================================================================
let
    FilePath   = "C:\Users\andre\OneDrive\12. COASE\01a. AALTO\2026q1\dera abstract.xlsx",
    Source     = Excel.Workbook(File.Contents(FilePath), null, true),
    SheetNames = Source[Name],

    // --- Helper: carica un foglio dato il primo nome trovato ---
    LoadSheet  = (candidates as list) as table =>
        let
            Found    = List.First(List.Select(candidates, each List.Contains(SheetNames, _))),
            SheetNm  = if Found = null
                       then error "Foglio non trovato: " & Text.Combine(candidates, " / ")
                       else Found,
            Raw      = Source{[Item = SheetNm, Kind = "Sheet"]}[Data],
            Rows     = Table.ToRows(Raw),
            HdrIdx   = List.PositionOf(
                           Rows,
                           List.First(
                               List.Select(
                                   Rows,
                                   each List.NonNullCount(List.Select(_, each _ <> null and _ <> "")) >= 2
                               )
                           )
                       ),
            Trimmed  = Table.Skip(Raw, HdrIdx),
            Headers  = Table.PromoteHeaders(Trimmed, [PromoteAllScalars = true]),
            FirstC   = Table.ColumnNames(Headers){0},
            Renamed  = if Text.StartsWith(FirstC, "Column")
                       then Table.RenameColumns(Headers, {{FirstC, "Voce"}})
                       else Headers,
            Clean    = Table.SelectRows(
                           Renamed,
                           each List.NonNullCount(
                                    List.Select(Record.FieldValues(_), each _ <> null and _ <> "")
                                ) > 0
                       ),
            Tagged   = Table.AddColumn(Clean, "Conto", each SheetNm, type text),
            Result   = Table.ReorderColumns(
                           Tagged,
                           List.Combine({{"Conto"}, List.RemoveItems(Table.ColumnNames(Tagged), {"Conto"})})
                       )
        in
            Result,

    // Carica IS e BS con i rispettivi nomi candidati
    IS_Table   = LoadSheet({"IS", "P&L", "Income Statement", "Profit & Loss",
                             "Profit and Loss", "CE", "Conto Economico", "PL"}),
    BS_Table   = LoadSheet({"BS", "Balance Sheet", "SP", "Stato Patrimoniale",
                             "Bilancio", "B/S", "BalanceSheet"}),

    // Allinea le colonne (aggiunge null per colonne mancanti nell'altro conto)
    AllCols    = List.Union({Table.ColumnNames(IS_Table), Table.ColumnNames(BS_Table)}),
    IS_Aligned = Table.SelectColumns(
                     Table.Combine({IS_Table, Table.FromRecords({[dummy = null]})}),
                     AllCols, MissingField.UseNull
                 ),
    // In realtà Table.Combine gestisce già l'allineamento:
    Combined   = Table.Combine({IS_Table, BS_Table}),

    // Ordina: prima IS, poi BS; poi per Voce
    Sorted     = Table.Sort(Combined, {{"Conto", Order.Ascending}, {"Voce", Order.Ascending}})
in
    Sorted
