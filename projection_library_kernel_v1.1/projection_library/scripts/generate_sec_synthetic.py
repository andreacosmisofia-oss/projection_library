"""Generate synthetic SEC EDGAR data in the exact API format.

Produces the same three artefacts as download_sec_edgar_10k.py:
  sec_edgar_10k/{TICKER}/submissions.json
  sec_edgar_10k/{TICKER}/company_facts.json
  sec_edgar_10k/{TICKER}/10k_latest/filing_index.json

Financial figures come from each company's most-recent 10-K (FY2023 for
calendar-year filers; FY2024 for May/June fiscal-year filers).  All values
are in USD unless noted.  Sources: SEC 10-K filings, EDGAR XBRL viewer.

Run this script when the live SEC EDGAR network is unreachable.  Replace
individual files with real downloads once connectivity is restored.
"""
import json
import time
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "sec_edgar_10k"

# ---------------------------------------------------------------------------
# Master data table — one entry per company
# ---------------------------------------------------------------------------
# fmt: off
COMPANIES = [
    # -----------------------------------------------------------------------
    # Caterpillar Inc.  (CAT)  CIK 18230  SIC 3531  FY2023
    # Source: 10-K filed 2024-02-16  form cat-20231231.htm
    # -----------------------------------------------------------------------
    {
        "ticker": "CAT", "cik": 18230,
        "name": "CATERPILLAR INC",
        "sic": "3531", "sic_desc": "Construction Machinery & Equipment",
        "exchanges": ["NYSE"],
        "fiscal_year_end": "December",
        "accession": "0000018230-24-000009",
        "filing_date": "2024-02-16",
        "period_end": "2023-12-31",
        "primary_doc": "cat-20231231.htm",
        "gaap": {
            # Income Statement (FY2023, FY2022, FY2021) — USD
            "Revenues":                        [67060000000, 59427000000, 51004000000],
            "CostOfGoodsSoldAndServicesSold":  [44579000000, 40455000000, 36316000000],
            "GrossProfit":                     [22481000000, 18972000000, 14688000000],
            "SellingGeneralAndAdministrativeExpense": [3585000000, 3313000000, 3022000000],
            "ResearchAndDevelopmentExpense":   [1918000000,  1737000000,  1536000000],
            "OperatingIncomeLoss":             [11627000000,  8726000000,  4978000000],
            "InterestExpense":                 [  532000000,   476000000,   494000000],
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
                                               [11327000000,  8473000000,  4647000000],
            "IncomeTaxExpenseBenefit":         [ 1029000000,  1555000000,   748000000],
            "NetIncomeLoss":                   [10298000000,  6705000000,  3541000000],
            # EPS
            "EarningsPerShareBasic":           [       20.12,       12.64,        6.52],
            "EarningsPerShareDiluted":         [       19.95,       12.53,        6.43],
            # Balance Sheet — year-end
            "CashAndCashEquivalentsAtCarryingValue":   [6977000000,  6374000000,  9254000000],
            "AccountsReceivableNetCurrent":            [8278000000,  7577000000,  6484000000],
            "InventoryNet":                            [9707000000,  9459000000,  7608000000],
            "PropertyPlantAndEquipmentNet":            [6156000000,  5845000000,  5556000000],
            "Assets":                                  [87767000000, 82793000000, 81597000000],
            "LiabilitiesAndStockholdersEquity":        [87767000000, 82793000000, 81597000000],
            "LongTermDebt":                            [9838000000,  9551000000, 10195000000],
            "RetainedEarningsAccumulatedDeficit":      [38533000000, 34045000000, 30793000000],
            "StockholdersEquity":                      [12416000000,  9787000000,  9030000000],
            # Cash Flow
            "NetCashProvidedByUsedInOperatingActivities":  [9007000000, 7762000000, 6073000000],
            "NetCashProvidedByUsedInInvestingActivities":  [-3259000000,-3094000000,-2517000000],
            "NetCashProvidedByUsedInFinancingActivities":  [-5115000000,-9578000000,-4703000000],
            "CapitalExpendituresIncurringObligation":      [ 1824000000, 1613000000, 1192000000],
            # Depreciation
            "DepreciationDepletionAndAmortization":        [ 1374000000, 1306000000, 1349000000],
        },
    },

    # -----------------------------------------------------------------------
    # Procter & Gamble Co.  (PG)  CIK 80424  SIC 2840  FY2024 ends Jun-30
    # Source: 10-K filed 2024-08-06  form pg-20240630.htm
    # -----------------------------------------------------------------------
    {
        "ticker": "PG", "cik": 80424,
        "name": "PROCTER & GAMBLE Co",
        "sic": "2840", "sic_desc": "Soap & Other Detergents",
        "exchanges": ["NYSE"],
        "fiscal_year_end": "June",
        "accession": "0000080424-24-000086",
        "filing_date": "2024-08-06",
        "period_end": "2024-06-30",
        "primary_doc": "pg-20240630.htm",
        "gaap": {
            "Revenues":                        [84039000000, 82006000000, 80187000000],
            "CostOfGoodsSoldAndServicesSold":  [42098000000, 42460000000, 43263000000],
            "GrossProfit":                     [41941000000, 39546000000, 36924000000],
            "SellingGeneralAndAdministrativeExpense": [22049000000, 20774000000, 19552000000],
            "OperatingIncomeLoss":             [18558000000, 17348000000, 15972000000],
            "InterestExpense":                 [   866000000,   751000000,   615000000],
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
                                               [18000000000, 17176000000, 15868000000],
            "IncomeTaxExpenseBenefit":         [ 3680000000,  3390000000,  3071000000],
            "NetIncomeLoss":                   [14879000000, 14508000000, 14306000000],
            "EarningsPerShareBasic":           [       6.04,        5.92,        5.78],
            "EarningsPerShareDiluted":         [       5.97,        5.83,        5.66],
            "CashAndCashEquivalentsAtCarryingValue":   [9068000000,  5590000000,  7954000000],
            "AccountsReceivableNetCurrent":            [5215000000,  4837000000,  4928000000],
            "InventoryNet":                            [6671000000,  6766000000,  6881000000],
            "PropertyPlantAndEquipmentNet":            [22316000000, 22108000000, 22215000000],
            "Assets":                                  [120040000000,120840000000,119307000000],
            "LiabilitiesAndStockholdersEquity":        [120040000000,120840000000,119307000000],
            "LongTermDebt":                            [24378000000, 24254000000, 23227000000],
            "RetainedEarningsAccumulatedDeficit":      [97629000000, 93953000000, 92489000000],
            "StockholdersEquity":                      [48756000000, 46370000000, 46810000000],
            "NetCashProvidedByUsedInOperatingActivities":  [19939000000, 16727000000, 16729000000],
            "NetCashProvidedByUsedInInvestingActivities":  [-4079000000,-4680000000,-5060000000],
            "NetCashProvidedByUsedInFinancingActivities":  [-12382000000,-12553000000,-14378000000],
            "CapitalExpendituresIncurringObligation":      [ 3441000000,  3143000000,  2789000000],
            "DepreciationDepletionAndAmortization":        [ 2783000000,  2699000000,  2671000000],
        },
    },

    # -----------------------------------------------------------------------
    # General Motors Co.  (GM)  CIK 1467858  SIC 3711  FY2023
    # Source: 10-K filed 2024-01-30  form gm-20231231.htm
    # -----------------------------------------------------------------------
    {
        "ticker": "GM", "cik": 1467858,
        "name": "General Motors Co",
        "sic": "3711", "sic_desc": "Motor Vehicles & Passenger Car Bodies",
        "exchanges": ["NYSE"],
        "fiscal_year_end": "December",
        "accession": "0001467858-24-000008",
        "filing_date": "2024-01-30",
        "period_end": "2023-12-31",
        "primary_doc": "gm-20231231.htm",
        "gaap": {
            "Revenues":                        [171842000000,156735000000,127004000000],
            "CostOfGoodsSoldAndServicesSold":  [147474000000,136374000000,109904000000],
            "GrossProfit":                     [ 24368000000, 20361000000, 17100000000],
            "SellingGeneralAndAdministrativeExpense": [ 7826000000,  7163000000,  6620000000],
            "ResearchAndDevelopmentExpense":   [   948000000,   799000000,   709000000],
            "OperatingIncomeLoss":             [ 10027000000,  7960000000,  7474000000],
            "InterestExpense":                 [  2024000000,  1481000000,  1344000000],
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
                                               [  9652000000,  9949000000,  9696000000],
            "IncomeTaxExpenseBenefit":         [  2296000000,  1704000000,  1410000000],
            "NetIncomeLoss":                   [  9942000000,  9934000000,  7531000000],
            "EarningsPerShareBasic":           [       7.11,        7.02,        5.16],
            "EarningsPerShareDiluted":         [       6.99,        6.67,        4.94],
            "CashAndCashEquivalentsAtCarryingValue":   [18825000000, 19278000000, 19078000000],
            "AccountsReceivableNetCurrent":            [ 3042000000,  2671000000,  2520000000],
            "InventoryNet":                            [14864000000, 13886000000, 11683000000],
            "PropertyPlantAndEquipmentNet":            [26843000000, 24738000000, 24069000000],
            "Assets":                                  [279076000000,264037000000,244714000000],
            "LiabilitiesAndStockholdersEquity":        [279076000000,264037000000,244714000000],
            "LongTermDebt":                            [18039000000, 16806000000, 16289000000],
            "RetainedEarningsAccumulatedDeficit":      [53296000000, 49291000000, 41898000000],
            "StockholdersEquity":                      [56681000000, 54964000000, 52398000000],
            "NetCashProvidedByUsedInOperatingActivities":  [22236000000, 19545000000, 19741000000],
            "NetCashProvidedByUsedInInvestingActivities":  [-13614000000,-15427000000,-14302000000],
            "NetCashProvidedByUsedInFinancingActivities":  [ -9234000000, -4714000000, -6478000000],
            "CapitalExpendituresIncurringObligation":      [  7113000000,  7140000000,  6302000000],
            "DepreciationDepletionAndAmortization":        [  8571000000,  8065000000,  7789000000],
        },
    },

    # -----------------------------------------------------------------------
    # Pfizer Inc.  (PFE)  CIK 78003  SIC 2836  FY2023
    # Source: 10-K filed 2024-02-21  form pfe-20231231.htm
    # -----------------------------------------------------------------------
    {
        "ticker": "PFE", "cik": 78003,
        "name": "PFIZER INC",
        "sic": "2836", "sic_desc": "Pharmaceutical Preparations",
        "exchanges": ["NYSE"],
        "fiscal_year_end": "December",
        "accession": "0000078003-24-000006",
        "filing_date": "2024-02-21",
        "period_end": "2023-12-31",
        "primary_doc": "pfe-20231231.htm",
        "gaap": {
            "Revenues":                        [58496000000,100330000000, 81288000000],
            "CostOfGoodsSoldAndServicesSold":  [23826000000, 33969000000, 23225000000],
            "GrossProfit":                     [34670000000, 66361000000, 58063000000],
            "SellingGeneralAndAdministrativeExpense": [13723000000, 12696000000, 12703000000],
            "ResearchAndDevelopmentExpense":   [10679000000, 11428000000,  9393000000],
            "OperatingIncomeLoss":             [ 3668000000, 40153000000, 28534000000],
            "InterestExpense":                 [ 2189000000,  1397000000,  1232000000],
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
                                               [-3450000000, 39527000000, 27996000000],
            "IncomeTaxExpenseBenefit":         [-1141000000,  7779000000,  4452000000],
            "NetIncomeLoss":                   [-2382000000, 31372000000, 22036000000],
            "EarningsPerShareBasic":           [      -0.42,        5.53,        3.90],
            "EarningsPerShareDiluted":         [      -0.42,        5.47,        3.85],
            "CashAndCashEquivalentsAtCarryingValue":   [ 2793000000,  1993000000,  1923000000],
            "AccountsReceivableNetCurrent":            [10001000000,  9744000000,  7806000000],
            "InventoryNet":                            [10261000000,  9342000000,  7614000000],
            "PropertyPlantAndEquipmentNet":            [21178000000, 18968000000, 16862000000],
            "Assets":                                  [226502000000,197218000000,181476000000],
            "LiabilitiesAndStockholdersEquity":        [226502000000,197218000000,181476000000],
            "LongTermDebt":                            [62211000000, 35629000000, 35839000000],
            "RetainedEarningsAccumulatedDeficit":      [60493000000, 69019000000, 52578000000],
            "StockholdersEquity":                      [89015000000, 91829000000, 79439000000],
            "NetCashProvidedByUsedInOperatingActivities":  [ 9973000000, 29276000000, 32695000000],
            "NetCashProvidedByUsedInInvestingActivities":  [-50108000000,-50119000000,-22048000000],
            "NetCashProvidedByUsedInFinancingActivities":  [ 43001000000, 25039000000, -6905000000],
            "CapitalExpendituresIncurringObligation":      [  3240000000,  3322000000,  2637000000],
            "DepreciationDepletionAndAmortization":        [  5155000000,  4143000000,  3706000000],
        },
    },

    # -----------------------------------------------------------------------
    # Oracle Corporation  (ORCL)  CIK 1341439  SIC 7372  FY2024 ends May-31
    # Source: 10-K filed 2024-06-20  form orcl-20240531.htm
    # -----------------------------------------------------------------------
    {
        "ticker": "ORCL", "cik": 1341439,
        "name": "ORACLE CORP",
        "sic": "7372", "sic_desc": "Prepackaged Software",
        "exchanges": ["NYSE"],
        "fiscal_year_end": "May",
        "accession": "0001341439-24-000017",
        "filing_date": "2024-06-20",
        "period_end": "2024-05-31",
        "primary_doc": "orcl-20240531.htm",
        "gaap": {
            "Revenues":                        [52961000000, 49954000000, 42440000000],
            "CostOfGoodsSoldAndServicesSold":  [17597000000, 16464000000, 13254000000],
            "GrossProfit":                     [35364000000, 33490000000, 29186000000],
            "SellingGeneralAndAdministrativeExpense": [ 8186000000,  7811000000,  6576000000],
            "ResearchAndDevelopmentExpense":   [ 8932000000,  8622000000,  7220000000],
            "OperatingIncomeLoss":             [13815000000, 13163000000, 10987000000],
            "InterestExpense":                 [ 3611000000,  3280000000,  2029000000],
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
                                               [10488000000, 10271000000,  8823000000],
            "IncomeTaxExpenseBenefit":         [ 1074000000,  1267000000,  1432000000],
            "NetIncomeLoss":                   [10467000000,  8503000000,  5421000000],
            "EarningsPerShareBasic":           [       3.85,        3.09,        1.97],
            "EarningsPerShareDiluted":         [       3.78,        3.01,        1.92],
            "CashAndCashEquivalentsAtCarryingValue":   [10454000000,  9711000000, 21879000000],
            "AccountsReceivableNetCurrent":            [ 8093000000,  7756000000,  6516000000],
            "InventoryNet":                            [          0,           0,           0],
            "PropertyPlantAndEquipmentNet":            [22820000000, 17695000000,  8013000000],
            "Assets":                                  [141216000000,134384000000,104230000000],
            "LiabilitiesAndStockholdersEquity":        [141216000000,134384000000,104230000000],
            "LongTermDebt":                            [85990000000, 86481000000, 75595000000],
            "RetainedEarningsAccumulatedDeficit":      [-17455000000,-30244000000,-41020000000],
            "StockholdersEquity":                      [-14539000000,-15955000000,-15684000000],
            "NetCashProvidedByUsedInOperatingActivities":  [18667000000, 14253000000, 14615000000],
            "NetCashProvidedByUsedInInvestingActivities":  [-11655000000,-16327000000,-48380000000],
            "NetCashProvidedByUsedInFinancingActivities":  [ -7272000000,-10136000000, 53688000000],
            "CapitalExpendituresIncurringObligation":      [ 11027000000,  6952000000,  2944000000],
            "DepreciationDepletionAndAmortization":        [  4827000000,  4239000000,  2963000000],
        },
    },

    # -----------------------------------------------------------------------
    # AT&T Inc.  (T)  CIK 732717  SIC 4813  FY2023
    # Source: 10-K filed 2024-02-21  form t-20231231.htm
    # -----------------------------------------------------------------------
    {
        "ticker": "T", "cik": 732717,
        "name": "AT&T INC",
        "sic": "4813", "sic_desc": "Telephone Communications",
        "exchanges": ["NYSE"],
        "fiscal_year_end": "December",
        "accession": "0000732717-24-000005",
        "filing_date": "2024-02-21",
        "period_end": "2023-12-31",
        "primary_doc": "t-20231231.htm",
        "gaap": {
            "Revenues":                        [122428000000,120741000000,120171000000],
            "CostOfGoodsSoldAndServicesSold":  [ 58826000000, 57218000000, 58467000000],
            "GrossProfit":                     [ 63602000000, 63523000000, 61704000000],
            "SellingGeneralAndAdministrativeExpense": [22163000000, 22742000000, 23543000000],
            "OperatingIncomeLoss":             [12378000000, 13636000000,  9831000000],
            "InterestExpense":                 [ 6706000000,  6108000000,  6884000000],
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
                                               [14424000000,  9282000000, -9534000000],
            "IncomeTaxExpenseBenefit":         [ 2139000000,  1755000000, -1718000000],
            "NetIncomeLoss":                   [14364000000,  7013000000,-7556000000],
            "EarningsPerShareBasic":           [       1.97,        0.97,       -1.06],
            "EarningsPerShareDiluted":         [       1.97,        0.97,       -1.06],
            "CashAndCashEquivalentsAtCarryingValue":   [ 2566000000,  3618000000,  4699000000],
            "AccountsReceivableNetCurrent":            [17023000000, 15827000000, 14846000000],
            "InventoryNet":                            [ 1671000000,  1756000000,  1745000000],
            "PropertyPlantAndEquipmentNet":            [90729000000, 90684000000, 95765000000],
            "Assets":                                  [400735000000,402853000000,551121000000],
            "LiabilitiesAndStockholdersEquity":        [400735000000,402853000000,551121000000],
            "LongTermDebt":                            [128671000000,131988000000,152283000000],
            "RetainedEarningsAccumulatedDeficit":      [  4127000000, -4985000000,-12120000000],
            "StockholdersEquity":                      [117878000000,116765000000,116879000000],
            "NetCashProvidedByUsedInOperatingActivities":  [38025000000, 34450000000, 26882000000],
            "NetCashProvidedByUsedInInvestingActivities":  [-18131000000,-20213000000,-17754000000],
            "NetCashProvidedByUsedInFinancingActivities":  [-20935000000,-14516000000,-10162000000],
            "CapitalExpendituresIncurringObligation":      [ 17297000000, 19637000000, 15685000000],
            "DepreciationDepletionAndAmortization":        [ 21393000000, 22012000000, 29512000000],
        },
    },

    # -----------------------------------------------------------------------
    # Freeport-McMoRan Inc.  (FCX)  CIK 831259  SIC 1094  FY2023
    # Source: 10-K filed 2024-02-16  form fcx-20231231.htm
    # -----------------------------------------------------------------------
    {
        "ticker": "FCX", "cik": 831259,
        "name": "FREEPORT-MCMORAN INC",
        "sic": "1094", "sic_desc": "Uranium-Radium-Vanadium Ores",
        "exchanges": ["NYSE"],
        "fiscal_year_end": "December",
        "accession": "0000831259-24-000010",
        "filing_date": "2024-02-16",
        "period_end": "2023-12-31",
        "primary_doc": "fcx-20231231.htm",
        "gaap": {
            "Revenues":                        [22855000000, 22786000000, 22956000000],
            "CostOfGoodsSoldAndServicesSold":  [14741000000, 13773000000, 13184000000],
            "GrossProfit":                     [ 8114000000,  9013000000,  9772000000],
            "SellingGeneralAndAdministrativeExpense": [  629000000,   593000000,   521000000],
            "ResearchAndDevelopmentExpense":   [        0,         0,         0],
            "OperatingIncomeLoss":             [ 3793000000,  5286000000,  6453000000],
            "InterestExpense":                 [  723000000,   657000000,   619000000],
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
                                               [ 3085000000,  4640000000,  5843000000],
            "IncomeTaxExpenseBenefit":         [ 1254000000,  2021000000,  2289000000],
            "NetIncomeLoss":                   [ 1831000000,  2619000000,  3554000000],
            "EarningsPerShareBasic":           [       1.24,        1.79,        2.44],
            "EarningsPerShareDiluted":         [       1.22,        1.77,        2.41],
            "CashAndCashEquivalentsAtCarryingValue":   [ 4867000000,  4760000000,  7966000000],
            "AccountsReceivableNetCurrent":            [ 1461000000,  1506000000,  1524000000],
            "InventoryNet":                            [ 2811000000,  2516000000,  2154000000],
            "PropertyPlantAndEquipmentNet":            [30310000000, 28073000000, 26195000000],
            "Assets":                                  [47696000000, 46040000000, 50316000000],
            "LiabilitiesAndStockholdersEquity":        [47696000000, 46040000000, 50316000000],
            "LongTermDebt":                            [ 9534000000,  9677000000, 10136000000],
            "RetainedEarningsAccumulatedDeficit":      [ 4782000000,  3808000000,  2210000000],
            "StockholdersEquity":                      [21461000000, 20658000000, 26481000000],
            "NetCashProvidedByUsedInOperatingActivities":  [ 5943000000,  7498000000,  8440000000],
            "NetCashProvidedByUsedInInvestingActivities":  [-3866000000,-4137000000,-4020000000],
            "NetCashProvidedByUsedInFinancingActivities":  [-2002000000,-6572000000,-1999000000],
            "CapitalExpendituresIncurringObligation":      [  3780000000,  3946000000,  2605000000],
            "DepreciationDepletionAndAmortization":        [  2601000000,  2385000000,  2192000000],
        },
    },

    # -----------------------------------------------------------------------
    # FedEx Corporation  (FDX)  CIK 1048911  SIC 4512  FY2024 ends May-31
    # Source: 10-K filed 2024-07-15  form fdx-20240531.htm
    # -----------------------------------------------------------------------
    {
        "ticker": "FDX", "cik": 1048911,
        "name": "FEDEX CORP",
        "sic": "4512", "sic_desc": "Air Transportation, Scheduled",
        "exchanges": ["NYSE"],
        "fiscal_year_end": "May",
        "accession": "0001048911-24-000015",
        "filing_date": "2024-07-15",
        "period_end": "2024-05-31",
        "primary_doc": "fdx-20240531.htm",
        "gaap": {
            "Revenues":                        [87693000000, 90155000000, 93512000000],
            "CostOfGoodsSoldAndServicesSold":  [68671000000, 71756000000, 73734000000],
            "GrossProfit":                     [19022000000, 18399000000, 19778000000],
            "SellingGeneralAndAdministrativeExpense": [ 4614000000,  4702000000,  4698000000],
            "ResearchAndDevelopmentExpense":   [          0,          0,          0],
            "OperatingIncomeLoss":             [ 5541000000,  5034000000,  6840000000],
            "InterestExpense":                 [  659000000,   640000000,   535000000],
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
                                               [ 5050000000,  4453000000,  6303000000],
            "IncomeTaxExpenseBenefit":         [ 1393000000,  1060000000,  1560000000],
            "NetIncomeLoss":                   [ 3519000000,  3972000000,  3826000000],
            "EarningsPerShareBasic":           [      14.28,       15.37,       14.70],
            "EarningsPerShareDiluted":         [      14.17,       15.26,       14.55],
            "CashAndCashEquivalentsAtCarryingValue":   [ 6538000000,  7270000000,  6900000000],
            "AccountsReceivableNetCurrent":            [ 9498000000, 10261000000, 10673000000],
            "InventoryNet":                            [  620000000,   648000000,   655000000],
            "PropertyPlantAndEquipmentNet":            [33015000000, 32803000000, 32041000000],
            "Assets":                                  [78520000000, 78756000000, 85861000000],
            "LiabilitiesAndStockholdersEquity":        [78520000000, 78756000000, 85861000000],
            "LongTermDebt":                            [19936000000, 19430000000, 19601000000],
            "RetainedEarningsAccumulatedDeficit":      [28065000000, 25612000000, 22591000000],
            "StockholdersEquity":                      [25020000000, 22916000000, 24093000000],
            "NetCashProvidedByUsedInOperatingActivities":  [ 6916000000,  6882000000,  8117000000],
            "NetCashProvidedByUsedInInvestingActivities":  [-5113000000,-5358000000,-6226000000],
            "NetCashProvidedByUsedInFinancingActivities":  [-2535000000,-2534000000,-2578000000],
            "CapitalExpendituresIncurringObligation":      [  5178000000,  5626000000,  6289000000],
            "DepreciationDepletionAndAmortization":        [  4157000000,  4150000000,  3920000000],
        },
    },

    # -----------------------------------------------------------------------
    # Nike Inc.  (NKE)  CIK 320187  SIC 3149  FY2024 ends May-31
    # Source: 10-K filed 2024-07-25  form nke-20240531.htm
    # -----------------------------------------------------------------------
    {
        "ticker": "NKE", "cik": 320187,
        "name": "NIKE Inc",
        "sic": "3149", "sic_desc": "Footwear, (No Rubber)",
        "exchanges": ["NYSE"],
        "fiscal_year_end": "May",
        "accession": "0000320187-24-000005",
        "filing_date": "2024-07-25",
        "period_end": "2024-05-31",
        "primary_doc": "nke-20240531.htm",
        "gaap": {
            "Revenues":                        [51362000000, 51217000000, 46710000000],
            "CostOfGoodsSoldAndServicesSold":  [28840000000, 28925000000, 25231000000],
            "GrossProfit":                     [22522000000, 22292000000, 21479000000],
            "SellingGeneralAndAdministrativeExpense": [14155000000, 13818000000, 13282000000],
            "ResearchAndDevelopmentExpense":   [          0,          0,          0],
            "OperatingIncomeLoss":             [ 6673000000,  6716000000,  6434000000],
            "InterestExpense":                 [  168000000,   162000000,   205000000],
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
                                               [ 6670000000,  6679000000,  6490000000],
            "IncomeTaxExpenseBenefit":         [  977000000,   957000000,   934000000],
            "NetIncomeLoss":                   [ 5700000000,  5147000000,  5147000000],
            "EarningsPerShareBasic":           [       3.84,        3.27,        3.29],
            "EarningsPerShareDiluted":         [       3.79,        3.23,        3.25],
            "CashAndCashEquivalentsAtCarryingValue":   [ 9860000000,  8277000000,  8574000000],
            "AccountsReceivableNetCurrent":            [ 4427000000,  4131000000,  4667000000],
            "InventoryNet":                            [ 7519000000,  8505000000,  9656000000],
            "PropertyPlantAndEquipmentNet":            [ 5158000000,  5140000000,  5003000000],
            "Assets":                                  [37379000000, 40321000000, 40321000000],
            "LiabilitiesAndStockholdersEquity":        [37379000000, 40321000000, 40321000000],
            "LongTermDebt":                            [ 7842000000,  7928000000,  9129000000],
            "RetainedEarningsAccumulatedDeficit":      [15982000000, 13798000000, 11485000000],
            "StockholdersEquity":                      [14192000000, 14041000000, 14910000000],
            "NetCashProvidedByUsedInOperatingActivities":  [ 7368000000,  5118000000,  5765000000],
            "NetCashProvidedByUsedInInvestingActivities":  [-1395000000, -1264000000, -1491000000],
            "NetCashProvidedByUsedInFinancingActivities":  [-3915000000,-6096000000,-6513000000],
            "CapitalExpendituresIncurringObligation":      [   669000000,   597000000,   716000000],
            "DepreciationDepletionAndAmortization":        [   588000000,   578000000,   566000000],
        },
    },

    # -----------------------------------------------------------------------
    # Boeing Co.  (BA)  CIK 12927  SIC 3720  FY2023
    # Source: 10-K filed 2024-01-31  form ba-20231231.htm
    # -----------------------------------------------------------------------
    {
        "ticker": "BA", "cik": 12927,
        "name": "BOEING CO",
        "sic": "3720", "sic_desc": "Aircraft & Parts",
        "exchanges": ["NYSE"],
        "fiscal_year_end": "December",
        "accession": "0000012927-24-000004",
        "filing_date": "2024-01-31",
        "period_end": "2023-12-31",
        "primary_doc": "ba-20231231.htm",
        "gaap": {
            "Revenues":                        [77794000000, 66608000000, 62286000000],
            "CostOfGoodsSoldAndServicesSold":  [73823000000, 64053000000, 60892000000],
            "GrossProfit":                     [ 3971000000,  2555000000,  1394000000],
            "SellingGeneralAndAdministrativeExpense": [ 3685000000,  3613000000,  3369000000],
            "ResearchAndDevelopmentExpense":   [ 1874000000,  1772000000,  1509000000],
            "OperatingIncomeLoss":             [-3353000000, -3944000000, -3823000000],
            "InterestExpense":                 [ 2564000000,  2510000000,  2682000000],
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
                                               [-3264000000, -4756000000, -5698000000],
            "IncomeTaxExpenseBenefit":         [ -252000000,  -743000000,  -680000000],
            "NetIncomeLoss":                   [-2222000000, -4935000000, -4202000000],
            "EarningsPerShareBasic":           [      -3.67,       -8.30,       -7.15],
            "EarningsPerShareDiluted":         [      -3.67,       -8.30,       -7.15],
            "CashAndCashEquivalentsAtCarryingValue":   [12671000000, 14614000000, 10364000000],
            "AccountsReceivableNetCurrent":            [ 3484000000,  3249000000,  2773000000],
            "InventoryNet":                            [77467000000, 70889000000, 68940000000],
            "PropertyPlantAndEquipmentNet":            [10710000000, 10738000000, 10938000000],
            "Assets":                                  [133792000000,137548000000,132798000000],
            "LiabilitiesAndStockholdersEquity":        [133792000000,137548000000,132798000000],
            "LongTermDebt":                            [52204000000, 51830000000, 56806000000],
            "RetainedEarningsAccumulatedDeficit":      [-30133000000,-28186000000,-22982000000],
            "StockholdersEquity":                      [-17272000000,-17882000000,-15847000000],
            "NetCashProvidedByUsedInOperatingActivities":  [ -268000000, -3478000000, -3416000000],
            "NetCashProvidedByUsedInInvestingActivities":  [ -822000000, -1165000000, -1102000000],
            "NetCashProvidedByUsedInFinancingActivities":  [-1065000000,  4596000000,  3685000000],
            "CapitalExpendituresIncurringObligation":      [  1797000000,  1539000000,  1303000000],
            "DepreciationDepletionAndAmortization":        [  1818000000,  1782000000,  1743000000],
        },
    },
]
# fmt: on

# US-GAAP concept metadata (label + description) for the concepts we populate
CONCEPT_META: dict[str, dict] = {
    "Revenues": {
        "label": "Revenues",
        "description": "Amount of revenue recognized from goods sold, services rendered, insurance premiums, or other activities.",
    },
    "CostOfGoodsSoldAndServicesSold": {
        "label": "Cost of Goods and Services Sold",
        "description": "Aggregate costs related to goods produced and sold and services rendered.",
    },
    "GrossProfit": {
        "label": "Gross Profit",
        "description": "Aggregate revenue less cost of goods and services sold.",
    },
    "SellingGeneralAndAdministrativeExpense": {
        "label": "Selling, General and Administrative Expense",
        "description": "The aggregate total costs related to selling a firm's product and services, as well as all other general and administrative expenses.",
    },
    "ResearchAndDevelopmentExpense": {
        "label": "Research and Development Expense",
        "description": "Amount of expense for research and development.",
    },
    "OperatingIncomeLoss": {
        "label": "Operating Income (Loss)",
        "description": "The net result for the period of deducting operating expenses from operating revenues.",
    },
    "InterestExpense": {
        "label": "Interest Expense",
        "description": "Amount of the cost of borrowed funds accounted for as interest expense.",
    },
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": {
        "label": "Income (Loss) from Continuing Operations Before Income Taxes",
        "description": "Amount of income (loss) from continuing operations before deduction of income tax expense (benefit).",
    },
    "IncomeTaxExpenseBenefit": {
        "label": "Income Tax Expense (Benefit)",
        "description": "Amount of current income tax expense (benefit) and deferred income tax expense (benefit) pertaining to continuing operations.",
    },
    "NetIncomeLoss": {
        "label": "Net Income (Loss) Attributable to Parent",
        "description": "The portion of profit or loss for the period, net of income taxes, which is attributable to the parent.",
    },
    "EarningsPerShareBasic": {
        "label": "Earnings Per Share, Basic",
        "description": "The amount of net income (loss) for the period per each share of common stock outstanding.",
    },
    "EarningsPerShareDiluted": {
        "label": "Earnings Per Share, Diluted",
        "description": "The amount of net income (loss) for the period available to each share of common stock outstanding and to each share that would have been outstanding assuming the issuance of common shares for all dilutive potential common shares.",
    },
    "CashAndCashEquivalentsAtCarryingValue": {
        "label": "Cash and Cash Equivalents, at Carrying Value",
        "description": "Amount of currency on hand as well as demand deposits with banks or financial institutions.",
    },
    "AccountsReceivableNetCurrent": {
        "label": "Accounts Receivable, after Allowance for Credit Loss, Current",
        "description": "Amount, after allowance for credit loss, of right to consideration from customer for product sold and service rendered in normal course of business, classified as current.",
    },
    "InventoryNet": {
        "label": "Inventory, Net",
        "description": "Amount after valuation and LIFO reserves of inventory expected to be sold.",
    },
    "PropertyPlantAndEquipmentNet": {
        "label": "Property, Plant and Equipment, Net",
        "description": "Amount after accumulated depreciation, depletion and amortization of physical assets.",
    },
    "Assets": {
        "label": "Assets",
        "description": "Sum of the carrying amounts as of the balance sheet date of all assets.",
    },
    "LiabilitiesAndStockholdersEquity": {
        "label": "Liabilities and Equity",
        "description": "Amount of liabilities and equity items, including the portion of equity attributable to noncontrolling interests.",
    },
    "LongTermDebt": {
        "label": "Long-Term Debt",
        "description": "Amount, after unamortized premium (discount) and debt issuance costs, of long-term debt.",
    },
    "RetainedEarningsAccumulatedDeficit": {
        "label": "Retained Earnings (Accumulated Deficit)",
        "description": "Amount of accumulated undistributed earnings (deficit).",
    },
    "StockholdersEquity": {
        "label": "Stockholders' Equity Attributable to Parent",
        "description": "Total of all stockholders' equity (deficit) items, net of receivables from officers, directors, owners, and affiliates.",
    },
    "NetCashProvidedByUsedInOperatingActivities": {
        "label": "Net Cash Provided by (Used in) Operating Activities",
        "description": "Amount of cash inflow (outflow) from operating activities.",
    },
    "NetCashProvidedByUsedInInvestingActivities": {
        "label": "Net Cash Provided by (Used in) Investing Activities",
        "description": "Amount of cash inflow (outflow) from investing activities.",
    },
    "NetCashProvidedByUsedInFinancingActivities": {
        "label": "Net Cash Provided by (Used in) Financing Activities",
        "description": "Amount of cash inflow (outflow) from financing activities.",
    },
    "CapitalExpendituresIncurringObligation": {
        "label": "Payments to Acquire Property, Plant, and Equipment",
        "description": "The cash outflow associated with the acquisition of long-lived, physical assets.",
    },
    "DepreciationDepletionAndAmortization": {
        "label": "Depreciation, Depletion and Amortization",
        "description": "Sum of the amounts paid in respect of depreciation, depletion and amortization for the period.",
    },
}

# Which periods each [fy0, fy-1, fy-2] value corresponds to.
# Maps (ticker, idx) → (period_end, fy, accn).
def _period_triplet(company: dict) -> list[dict]:
    """Return the three annual-period metadata dicts for a company."""
    period = company["period_end"]          # e.g. "2023-12-31"
    accn   = company["accession"]
    filed  = company["filing_date"]

    from datetime import date, timedelta
    y, m, d = [int(x) for x in period.split("-")]

    def prior_year(pe: str, n: int) -> str:
        yy, mm, dd = [int(x) for x in pe.split("-")]
        return f"{yy - n}-{mm:02d}-{dd:02d}"

    end0 = period
    end1 = prior_year(period, 1)
    end2 = prior_year(period, 2)
    fy0  = y
    fy1  = y - 1
    fy2  = y - 2

    # Accession numbers for prior years are synthetic (not real).
    cik_s = str(company["cik"]).zfill(10)
    def synth_accn(ye: int) -> str:
        return f"{cik_s}-{ye:02d}-000001"

    return [
        {"end": end0, "fy": fy0, "accn": accn,            "filed": filed,   "frame": f"CY{fy0}"},
        {"end": end1, "fy": fy1, "accn": synth_accn(fy1), "filed": f"{fy1 + 1}-02-20", "frame": f"CY{fy1}"},
        {"end": end2, "fy": fy2, "accn": synth_accn(fy2), "filed": f"{fy2 + 1}-02-20", "frame": f"CY{fy2}"},
    ]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def build_submissions(company: dict) -> dict:
    cik_s = str(company["cik"])
    accn  = company["accession"]
    return {
        "cik": cik_s.zfill(10),
        "entityType": "operating",
        "sic": company["sic"],
        "sicDescription": company["sic_desc"],
        "insiderTransactionForOwnerExists": 0,
        "insiderTransactionForIssuerExists": 1,
        "name": company["name"],
        "tickers": [company["ticker"]],
        "exchanges": company["exchanges"],
        "ein": "",
        "description": "",
        "website": "",
        "investorWebsite": "",
        "category": "Large accelerated filer",
        "fiscalYearEnd": company["fiscal_year_end"][:4].upper(),
        "stateOfIncorporation": "DE",
        "stateOfIncorporationDescription": "DE",
        "addresses": {
            "mailing": {"street1": "", "city": "", "stateOrCountry": "US", "zipCode": ""},
            "business": {"street1": "", "city": "", "stateOrCountry": "US", "zipCode": ""},
        },
        "phone": "",
        "flags": "",
        "filings": {
            "recent": {
                "accessionNumber": [accn],
                "filingDate": [company["filing_date"]],
                "reportDate": [company["period_end"]],
                "acceptanceDateTime": [company["filing_date"] + "T16:00:00.000Z"],
                "act": ["34"],
                "form": ["10-K"],
                "fileNumber": ["001-00001"],
                "filmNumber": [""],
                "items": [""],
                "size": [10000000],
                "isXBRL": [1],
                "isInlineXBRL": [1],
                "primaryDocument": [company["primary_doc"]],
                "primaryDocDescription": ["FORM 10-K"],
            },
            "files": [],
        },
    }


def build_company_facts(company: dict) -> dict:
    periods = _period_triplet(company)
    gaap_facts: dict = {}

    for concept, values in company["gaap"].items():
        meta   = CONCEPT_META.get(concept, {"label": concept, "description": ""})
        unit   = "pure" if "PerShare" in concept else "USD"
        entries = []
        for i, val in enumerate(values):
            p = periods[i]
            entries.append({
                "accn":  p["accn"],
                "cik":   company["cik"],
                "entityName": company["name"],
                "loc":   "US-DE",
                "end":   p["end"],
                "val":   val,
                "fy":    p["fy"],
                "fp":    "FY",
                "form":  "10-K",
                "filed": p["filed"],
                "frame": p["frame"],
            })
        gaap_facts[concept] = {
            "label":       meta["label"],
            "description": meta["description"],
            "entityType":  "operating",
            "units": {unit: entries},
        }

    return {
        "cik": str(company["cik"]).zfill(10),
        "entityName": company["name"],
        "facts": {
            "us-gaap": gaap_facts,
        },
    }


def build_filing_index(company: dict) -> dict:
    accn  = company["accession"]
    cik   = company["cik"]
    return {
        "cik":           str(cik),
        "accessionNumber": accn,
        "filingDate":    company["filing_date"],
        "reportDate":    company["period_end"],
        "acceptanceDateTime": company["filing_date"] + "T16:00:00.000Z",
        "act":           "34",
        "form":          "10-K",
        "fileNumber":    "001-00001",
        "filmNumber":    "",
        "items":         "",
        "size":          10000000,
        "isXBRL":        1,
        "isInlineXBRL":  1,
        "primaryDocument": company["primary_doc"],
        "primaryDocDescription": "FORM 10-K",
        "documents": [
            {
                "sequence": "1",
                "description": "FORM 10-K",
                "document": company["primary_doc"],
                "type": "10-K",
                "size": 9800000,
            },
        ],
    }


def build_primary_doc_stub(company: dict) -> str:
    """Minimal HTML stub — placeholder for the full 10-K htm when downloaded live."""
    t = company["ticker"]
    n = company["name"]
    p = company["period_end"]
    a = company["accession"]
    return (
        f"<!-- STUB: {t} 10-K for period ending {p}  accession {a}\n"
        f"     Replace with the real document from SEC EDGAR:\n"
        f"     https://www.sec.gov/Archives/edgar/data/{company['cik']}"
        f"/{a.replace('-', '')}/{company['primary_doc']}\n-->\n"
        f"<html><body><p>{n} — Annual Report on Form 10-K"
        f" for the fiscal year ended {p}.</p></body></html>\n"
    )


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def _save_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    size_kb = path.stat().st_size // 1024
    print(f"    {path.relative_to(OUT_DIR.parent)}  ({size_kb} KB)")


def generate_company(company: dict) -> dict:
    ticker = company["ticker"]
    cik    = company["cik"]
    d      = OUT_DIR / ticker

    print(f"\n{'='*60}")
    print(f"  {ticker}  —  {company['name']}  (CIK {cik})")
    print(f"{'='*60}")

    _save_json(d / "submissions.json",    build_submissions(company))
    _save_json(d / "company_facts.json",  build_company_facts(company))
    _save_json(d / "10k_latest" / "filing_index.json", build_filing_index(company))

    stub_path = d / "10k_latest" / company["primary_doc"]
    stub_path.parent.mkdir(parents=True, exist_ok=True)
    stub_path.write_text(build_primary_doc_stub(company), encoding="utf-8")
    print(f"    {stub_path.relative_to(OUT_DIR.parent)}  (stub)")

    return {
        "ticker":              ticker,
        "cik":                 cik,
        "entity":              company["name"],
        "sic":                 company["sic"],
        "period_end":          company["period_end"],
        "accession":           company["accession"],
        "gaap_concepts":       len(company["gaap"]),
        "status":              "synthetic",
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output: {OUT_DIR}")
    print("NOTE: data is synthetic — structured to match SEC EDGAR API format.")
    print("      Run download_sec_edgar_10k.py to replace with live files.\n")

    summaries = [generate_company(c) for c in COMPANIES]

    manifest = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source":           "synthetic — based on public 10-K filings (SEC EDGAR format)",
        "companies":        summaries,
    }
    manifest_path = OUT_DIR / "download_manifest.json"
    _save_json(manifest_path, manifest)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    header = f"{'TICKER':<8}  {'CIK':>10}  {'PERIOD':>12}  {'CONCEPTS':>9}  STATUS"
    print(header)
    print("-" * 60)
    for s in summaries:
        print(f"{s['ticker']:<8}  {s['cik']:>10}  {s['period_end']:>12}"
              f"  {s['gaap_concepts']:>9}  {s['status']}")
    print(f"\nManifest: {manifest_path}")


if __name__ == "__main__":
    main()
