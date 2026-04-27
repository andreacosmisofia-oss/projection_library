# Audit Report — Projection Library Spec v1.1
**M1.0 COMPLETATA — 2026-04-27**

## §8 Numeri ufficiali

| Entità | Numero ufficiale |
|--------|-----------------|
| Voci modello (02_voices) | 246 |
| Metodi (01_methods sez. A) | 62 |
| Derived rules (01_methods sez. B) | 19 |
| KPI catalogati (03_kpis) | 84 (di cui 4 template parametrici) |
| Validation rules (05_validation) | 73 |

## §8.2 Enum nature (normalizzati)

| Valore Excel | Valore normalizzato |
|---|---|
| driver | driver |
| driver (placeholder) | driver_placeholder |
| driver (slot) | driver_slot |
| derived | derived |
| derived (identity) | derived_identity |
| reference | reference |
| placeholder | placeholder |

## §8.3 Normalizzazione calc_phase

Valori compositi splittati in calc_phase_proxy + calc_phase_final.

| Valore Excel | proxy | final |
|---|---|---|
| E1 | null | E1 |
| E2 | null | E2 |
| E3 | null | E3 |
| E3.1 | null | E3_1 |
| E4 | null | E4 |
| E5 | null | E5 |
| E6 | null | E6 |
| E7 | null | E7 |
| E7.5 | null | E7_5 |
| E8 | null | E8 |
| E1 proxy / E3 final | E1 | E3 |
| E1 proxy / E3.1 final | E1 | E3_1 |
| E4 proxy / E8 check | E4 | E8 |
| E7.5 final (E3 proxy) | E3 | E7_5 |

## §9 Note di normalizzazione per ingestion

- 01_methods, complexity: "simple" → rimappare a "low"
- 02_voices, nature: valori compositi → rimappare secondo §8.2
- 02_voices, calc_phase: valori compositi → splittare secondo §8.3
