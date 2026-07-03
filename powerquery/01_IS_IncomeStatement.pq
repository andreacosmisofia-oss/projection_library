// ================================================================
// QUERY 1 — IS: Conto Economico
// File: C:\Users\andre\OneDrive\12. COASE\01a. AALTO\2026q1\dera abstract.xlsx
//
// La query tenta i nomi di foglio più comuni (EN + IT).
// Se nessuno corrisponde, aggiorna la variabile SheetName
// con il nome esatto restituito dalla query 00_Discover_Sheets.
// ================================================================
let
    FilePath  = "C:\Users\andre\OneDrive\12. COASE\01a. AALTO\2026q1\dera abstract.xlsx",
    Source    = Excel.Workbook(File.Contents(FilePath), null, true),

    // --- Candidati per il foglio IS (in ordine di preferenza) ---
    Candidates = {"IS", "P&L", "Income Statement", "Profit & Loss",
                  "Profit and Loss", "CE", "Conto Economico", "PL"},

    // Cerca il primo foglio esistente tra i candidati
    FindSheet = List.First(
        List.Select(
            Candidates,
            each List.Contains(Source[Name], _)
        )
    ),

    // Errore esplicito se non trovato (leggi 00_Discover per il nome corretto)
    SheetName = if FindSheet = null
                then error "Foglio IS non trovato. Controlla i nomi con 00_Discover_Sheets."
                else FindSheet,

    RawData   = Source{[Item = SheetName, Kind = "Sheet"]}[Data],

    // Rileva la riga di intestazione: salta le righe iniziali vuote/null
    // cercando la prima riga che ha almeno 2 celle non vuote
    DetectHeaderRow = (tbl as table) as table =>
        let
            Rows       = Table.ToRows(tbl),
            HeaderIdx  = List.PositionOf(
                             Rows,
                             List.First(
                                 List.Select(
                                     Rows,
                                     each List.NonNullCount(
                                              List.Select(_, each _ <> null and _ <> "")
                                          ) >= 2
                                 )
                             )
                         ),
            Trimmed    = Table.Skip(tbl, HeaderIdx),
            Promoted   = Table.PromoteHeaders(Trimmed, [PromoteAllScalars = true])
        in
            Promoted,

    WithHeaders = DetectHeaderRow(RawData),

    // Rinomina la prima colonna "Voce" se è ancora Column1
    FirstCol    = Table.ColumnNames(WithHeaders){0},
    Renamed     = if Text.StartsWith(FirstCol, "Column")
                  then Table.RenameColumns(WithHeaders, {{FirstCol, "Voce"}})
                  else WithHeaders,

    // Rimuove righe completamente vuote
    CleanEmpty  = Table.SelectRows(
                      Renamed,
                      each List.NonNullCount(
                               List.Select(Record.FieldValues(_), each _ <> null and _ <> "")
                           ) > 0
                  ),

    // Aggiunge colonna identificativa del conto
    TaggedIS    = Table.AddColumn(CleanEmpty, "Conto", each "IS", type text),

    // Sposta la colonna tag in prima posizione
    Reordered   = Table.ReorderColumns(
                      TaggedIS,
                      List.Combine({{"Conto"}, List.RemoveItems(Table.ColumnNames(TaggedIS), {"Conto"})})
                  )
in
    Reordered
