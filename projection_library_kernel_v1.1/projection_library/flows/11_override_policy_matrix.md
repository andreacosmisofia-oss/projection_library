# Flow 11 — Override Policy Matrix (specifica)

## Scopo

Documentazione della matrice che governa il comportamento degli override per voice category. È la fonte di verità per il file `registries/override_policy.yaml` che sarà generato in Step 2 (Milestone 1.5).

## Concetto

Ogni voice_id appartiene a una **policy_class**. La policy_class definisce:

1. Se la voce è overridable (alcune voci derived non lo sono)
2. Se l'override può essere `one_shot`
3. Quali voci dipendenti assorbono il delta in modalità organic
4. Quali voci dipendenti assorbono il delta anche in modalità one_shot
5. CF treatment (su quale linea CF impatta)
6. Tax treatment (se applica ETR)
7. Se affetta i futuri anni

## Matrice policy classes

### `revenue_organic`

```yaml
policy_class: revenue_organic
applies_to_voices_pattern: "pl.rev.gross.*"  # tutte le voci di ricavo gross
exclude_voices: ["pl.rev.gross_total", "pl.rev.net.proxy", "pl.rev.net.final"]  # subtotali

one_shot_allowed: true

organic_propagation_targets:
  - "pl.cogs.*"             # via metodo COGS attivo (pct_net_revenue, volume_price, etc.)
  - "bs.nwc.ar.*"           # via DSO
  - "bs.nwc.other_current_liab.vat_payable"  # via vat_rate
  - "pl.tax.current"        # via ETR
  - "pl.tax.total"
  - "pl.net_income"
  - "bs.equity.retained_earnings.close"
  - "bs.nwc.cit_payable"

one_shot_propagation_targets:
  - "bs.nfp.cash"           # sempre, via CF identity
  - "cf.net_change_cash"

cf_treatment: "operating_cf_revenue_line"
tax_treatment: "applies_etr_unless_flag_off"
affects_future_years: false
```

### `cogs_organic`

```yaml
policy_class: cogs_organic
applies_to_voices_pattern: "pl.cogs.*"
exclude_voices: ["pl.cogs.total.proxy", "pl.cogs.total.final"]

one_shot_allowed: true

organic_propagation_targets:
  - "bs.nwc.ap.*"            # via DPO
  - "bs.nwc.inventory.*"     # via DIO
  - "pl.gross_profit.final"
  - "pl.ebitda.final"
  - "pl.ebit"
  - "pl.tax.current"
  - "pl.net_income"
  - "bs.equity.retained_earnings.close"

one_shot_propagation_targets:
  - "bs.nfp.cash"
  - "cf.net_change_cash"

cf_treatment: "operating_cf_cogs_line"
tax_treatment: "applies_etr_unless_flag_off"
affects_future_years: false
```

### `opex_one_shot`

```yaml
policy_class: opex_one_shot
applies_to_voices_pattern: "pl.opex.*"
exclude_voices: ["pl.opex.total"]

one_shot_allowed: true

organic_propagation_targets:
  - "pl.ebitda.final"
  - "pl.ebit"
  - "pl.tax.current"
  - "pl.net_income"
  - "bs.equity.retained_earnings.close"
  - "bs.nwc.ap.*"            # se voce opex con accrual

one_shot_propagation_targets:
  - "bs.nfp.cash"
  - "cf.net_change_cash"

cf_treatment: "operating_cf_opex_line"
tax_treatment: "applies_etr_unless_flag_off"
affects_future_years: false
```

### `capex_organic`

```yaml
policy_class: capex_organic
applies_to_voices_pattern: "cf.investing.capex.*"

one_shot_allowed: true

organic_propagation_targets:
  - "bs.fa.tangible.gross_close"
  - "bs.fa.intangible.gross_close"
  - "pl.da.*"               # via depreciation schedule
  - "pl.ebit"
  - "pl.tax.current"
  - "pl.net_income"
  - "bs.equity.retained_earnings.close"

one_shot_propagation_targets:
  - "bs.fa.tangible.gross_close"   # asset si forma sempre, anche one_shot
  - "bs.fa.intangible.gross_close"
  - "bs.nfp.cash"
  - "cf.net_change_cash"

cf_treatment: "investing_cf"
tax_treatment: "no_direct_tax_generates_da_unless_flag_off"
affects_future_years: true                # asset depreciation affects future D&A
note: "one_shot capex genera comunque asset; differenza con organic = no D&A futura ricalcolata se flag off"
```

### `equity_injection_one_shot`

```yaml
policy_class: equity_injection_one_shot
applies_to_voices_pattern: "bs.equity.capital.injection"

one_shot_allowed: true

organic_propagation_targets:
  - "bs.equity.share_capital.close"
  - "bs.equity.total_close"
  - "bs.balance_check"

one_shot_propagation_targets:
  - "bs.equity.share_capital.close"
  - "bs.equity.total_close"
  - "bs.nfp.cash"
  - "cf.net_change_cash"
  - "cf.financing.equity_changes"

cf_treatment: "financing_cf_equity_line"
tax_treatment: "no_tax"
affects_future_years: false
note: "no differenza pratica organic vs one_shot per equity injection"
```

### `debt_drawdown_one_shot` / `debt_repayment_one_shot`

```yaml
policy_class: debt_drawdown_one_shot
applies_to_voices_pattern: "bs.nfp.borrowings.drawdown_*"

one_shot_allowed: true

organic_propagation_targets:
  - "bs.nfp.borrowings.balance_close"
  - "bs.nfp.net_debt"
  - "pl.financial.interest_expense"   # se metodo ricalcola interest su balance_avg
  - "pl.ebt"
  - "pl.tax.current"
  - "pl.net_income"
  - "bs.equity.retained_earnings.close"

one_shot_propagation_targets:
  - "bs.nfp.borrowings.balance_close"
  - "bs.nfp.net_debt"
  - "bs.nfp.cash"
  - "cf.net_change_cash"
  - "cf.financing.debt_changes"

cf_treatment: "financing_cf_debt_line"
tax_treatment: "no_direct_tax_affects_future_interest_unless_flag_off"
affects_future_years: true
```

### `tax_one_shot`

```yaml
policy_class: tax_one_shot
applies_to_voices_pattern: "pl.tax.current"

one_shot_allowed: true

organic_propagation_targets:
  - "pl.tax.total"
  - "pl.net_income"
  - "bs.equity.retained_earnings.close"
  - "bs.nwc.cit_payable"

one_shot_propagation_targets:
  - "bs.nwc.cit_payable"
  - "bs.nfp.cash"
  - "cf.net_change_cash"

cf_treatment: "operating_cf_tax_paid_line"
tax_treatment: "direct_modification_no_etr_recalc"
affects_future_years: false
```

### `nwc_dso_dpo_dio_organic`

```yaml
policy_class: nwc_days_organic
applies_to_voices_pattern: ["bs.nwc.ar.trade_gross", "bs.nwc.ap.trade", "bs.nwc.inventory.*"]

one_shot_allowed: true

organic_propagation_targets:
  - "cf.operating.nwc_change"
  - "bs.nfp.cash"

one_shot_propagation_targets:
  - "cf.operating.nwc_change"
  - "bs.nfp.cash"
  - "cf.net_change_cash"

cf_treatment: "operating_cf_nwc_change"
tax_treatment: "no_tax"
affects_future_years: false
note: "override su NWC = puro working capital adjustment, no impatto P&L"
```

### `provisions_organic`

```yaml
policy_class: provisions_organic
applies_to_voices_pattern: "bs.provisions.*"

one_shot_allowed: true

organic_propagation_targets:
  - "pl.provisions.*"        # accrual flow
  - "pl.ebitda.final"        # se include provisions
  - "pl.tax.current"
  - "pl.net_income"
  - "bs.equity.retained_earnings.close"

one_shot_propagation_targets:
  - "bs.nfp.cash"
  - "cf.net_change_cash"

cf_treatment: "operating_cf_addback_provisions"
tax_treatment: "applies_etr_unless_flag_off"
affects_future_years: false
```

### `not_overridable_derived`

```yaml
policy_class: not_overridable_derived
applies_to_voices_pattern: ["pl.gross_profit.*", "pl.ebitda.*", "pl.ebit", "pl.ebt", "pl.net_income",
                            "pl.rev.gross_total", "pl.rev.net.*", "pl.cogs.total.*", "pl.opex.total",
                            "pl.tax.total", "pl.financial.total_net",
                            "bs.fa.*.net_close", "bs.fa.*.gross_close",
                            "bs.equity.total_close", "bs.equity.retained_earnings.close",
                            "bs.nwc.operating.*", "bs.nfp.net_debt", "bs.nfp.cash",
                            "bs.total_assets", "bs.total_liabilities_equity", "bs.balance_check",
                            "cf.*.total", "cf.net_change_cash"]

one_shot_allowed: false
overridable: false

guidance_message: |
  Questa voce è derived (calcolata come identità o subtotale).
  Per modificarla, applica override su una delle componenti.
  Vedi voice_dependencies.yaml per la lista delle componenti.
```

## Mapping voice → policy_class

Ogni voce in `voice_registry.yaml` ottiene un campo:

```yaml
- voice_id: pl.rev.gross.product_sales
  ...
  override_policy_class: revenue_organic

- voice_id: pl.ebitda.final
  ...
  override_policy_class: not_overridable_derived
```

Il mapping è generato in M1.5 sulla base dei pattern definiti sopra. Voci ambigue ricevono assegnazione manuale.

## Esempi non triviali

### Capex organic vs one_shot

Caso: utente fa override capex Y2 = +500.

**Organic**:
- capex Y2 += 500
- bs.fa.tangible.gross_close[Y2] += 500
- pl.da.tangible[Y2..Y3] += 500/useful_life (mid-year convention)
- pl.ebit[Y2..Y3] −= D&A delta
- pl.tax.current[Y2..Y3] −= D&A delta × etr
- pl.net_income[Y2..Y3] aggiornato
- bs.equity.retained_earnings cumulato aggiornato
- bs.nfp.cash[Y2..Y3] −= 500 (CF investing) + tax saving cumulato

**One_shot**:
- capex Y2 += 500
- bs.fa.tangible.gross_close[Y2] += 500 (asset si forma sempre)
- pl.da NON ricalcolata (one_shot interrompe propagazione D&A)
- pl.ebit, tax, net_income invariate
- bs.nfp.cash[Y2..Y3] −= 500

Use case one_shot capex: progetto immateriale "tutto cash" che non genera ammortamento ulteriore (es. spese accessorie capitalizzate ma con utile_life già concluso).

### Revenue organic con flag tax_off

Variante: utente fa override revenue +2000 organic, ma con flag `apply_tax = false`.

- revenue +2000
- COGS proportional propaga
- AR via DSO propaga
- Ma pl.tax.current NON cambia (effective_value etr × ebt usa il vecchio ebt)
- Net income aggiornato senza tax delta
- Cash adjusted

Use case: ricavi non tassabili (es. plusvalenze esenti, contributi pubblici fiscalmente neutri).

Implementation: in `POST /overrides`, schema accetta opzionale `flags: {apply_tax: false, apply_da: false, ...}`. La `propagate` legge flags e salta target corrispondenti.

## Validazione policy

In M1.9 (Registry loader), validare:
- Tutte le voci in `voice_registry.yaml` hanno `override_policy_class`
- Ogni `policy_class` esiste in `override_policy.yaml`
- Voci con `nature == derived` hanno `policy_class == not_overridable_derived`
- I pattern non si sovrappongono (una voce non match più di una policy class non-fallback)

## Test cases

- TC-11-01: override revenue +2000 organic → cogs/ar/tax/cash propagati
- TC-11-02: override revenue +2000 one_shot → solo cash propagato, cogs invariata
- TC-11-03: tentativo override pl.ebitda.final → rifiutato con guidance message
- TC-11-04: override capex one_shot → asset si forma, D&A non ricalcolata
- TC-11-05: override revenue +2000 organic con flag apply_tax=false → no tax adjustment
- TC-11-06: 3 override coesistenti (rev, opex, capex) → tutti applicati additivamente
- TC-11-07: disattiva override → propagazione inversa, base_value voci dipendenti tornano allo stato originale