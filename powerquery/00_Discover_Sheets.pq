// ================================================================
// QUERY 0 — DISCOVER: elenca tutti i fogli del file
// Incolla questa query per prima per vedere i nomi esatti dei fogli
// e la struttura del file dera abstract.xlsx
// ================================================================
let
    FilePath = "C:\Users\andre\OneDrive\12. COASE\01a. AALTO\2026q1\dera abstract.xlsx",
    Source   = Excel.Workbook(File.Contents(FilePath), null, true),

    // Mostra nome, tipo (Sheet / DefinedName / Table) e numero di righe
    Overview = Table.SelectColumns(Source, {"Name", "Kind", "Hidden"}),
    Sorted   = Table.Sort(Overview, {{"Kind", Order.Ascending}, {"Name", Order.Ascending}})
in
    Sorted
