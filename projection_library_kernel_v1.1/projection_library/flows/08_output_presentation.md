# Flow 08 — Output presentation (dashboard Koyfin-style)

## Scopo

Dashboard interattiva che mostra il piano integrato in tempo reale (refresh on demand). Permette navigazione tra P&L, SP, CF, KPI, validation report con drill-down progressivo.

## Trigger

Dopo run engine (Flow 07). Utente entra in pagina progetto.

## Architettura UI

### Layout principale

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                        │
│ [Project name]  [Quality: 75/100●●●○]  [Sector: Industrial]   [Refresh] [⋮]  │
├──────────────────────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────┐ ┌─────────────────────────────────────────────┐│
│ │ SIDEBAR ASSUMPTIONS       │ │ MAIN AREA — DASHBOARD                       ││
│ │                           │ │                                              ││
│ │ ▼ Revenue                 │ │ ┌────────────────┐ ┌────────────────┐      ││
│ │   product_sales           │ │ │ P&L (mini)     │ │ SP (mini)      │      ││
│ │   Y1: [10.5%] ...         │ │ │                │ │                │      ││
│ │ ▼ Costs                   │ │ │ rev: ~2,300    │ │ FA: ~1,500     │      ││
│ │   ...                     │ │ │ ebitda: 450    │ │ NWC: 200       │      ││
│ │ ▼ NWC                     │ │ │ ebit: 350      │ │ NFP: -800      │      ││
│ │ ▼ Capex                   │ │ │ ni: 250        │ │ Eq: 900        │      ││
│ │ ▼ Debt                    │ │ └────────────────┘ └────────────────┘      ││
│ │ ▼ Tax                     │ │                                              ││
│ │                           │ │ ┌────────────────┐ ┌────────────────┐      ││
│ │ ▼ Overrides (3 active)    │ │ │ CF (mini)      │ │ KPI snapshot   │      ││
│ │   • +2,000 rev Y3 [organic]│ │ │                │ │                │      ││
│ │   • -500 opex Y2          │ │ │ CF op: 350     │ │ EBITDA m: 19%  │      ││
│ │   ...                     │ │ │ CF inv: -150   │ │ ND/EBITDA: 1.8x│      ││
│ │                           │ │ │ CF fin: -100   │ │ DSO: 65 days   │      ││
│ │                           │ │ │ Cash: 250      │ │ ROE: 12%       │      ││
│ │                           │ │ └────────────────┘ └────────────────┘      ││
│ │                           │ │                                              ││
│ │                           │ │ TABS: [P&L] [SP] [CF] [Ratios] [Validation] ││
│ │                           │ │                                              ││
│ │                           │ │ ┌──────────────────────────────────────────┐││
│ │                           │ │ │ Selected tab — detailed table             │││
│ │                           │ │ │                                            │││
│ │                           │ │ │ (P&L detailed o SP detailed o CF detailed │││
│ │                           │ │ │  o ratio table o validation report)       │││
│ │                           │ │ │                                            │││
│ │                           │ │ └──────────────────────────────────────────┘││
│ └──────────────────────────┘ └─────────────────────────────────────────────┘│
├──────────────────────────────────────────────────────────────────────────────┤
│ BOTTOMBAR                                                                     │
│ ⛔ 0  🔴 2 errors  🟡 5 warnings  🔵 1 info  | Approx: 3 applied | Last: 14:32│
└──────────────────────────────────────────────────────────────────────────────┘
```

### Componenti chiave

#### 1. Topbar

- **Project name + quality score badge**: badge colorato (verde 70+, giallo 50-69, rosso <50)
- **Sector pack indicator**
- **Refresh button**: trigger `POST /run` + reload snapshot
- **Menu**: `[⋮]` con opzioni: Export Excel, Settings, Delete project

#### 2. Sidebar assumption (left)

Ogni famiglia (Revenue, Costs, NWC, Capex, Debt, Tax) è un accordion espandibile. Dentro, ogni voce ha:
- Voice label
- Method indicator
- Input Y1, Y2, Y3 (con type adatto: % o days o EUR_000)
- Calibration score badge
- Curve selector (flat/linear/custom)
- Validation warning icon se fuori range

**Interazione**: cambio valore → debounced (~500ms), poi salva su DB. Refresh non automatico (deferred). Indicatore visivo "model out of sync, click Refresh".

#### 3. Mini widget centrali (4 card)

**P&L mini**: Y0 vs Y3, voci principali (rev, ebitda, ebit, ni). Click → tab P&L detailed.

**SP mini**: Y0 vs Y3, FA, NWC, NFP, Equity. Click → tab SP detailed.

**CF mini**: Y3 only, CF op/inv/fin/cash close. Click → tab CF detailed.

**KPI snapshot**: 4-6 KPI chiave (EBITDA margin, ND/EBITDA, DSO, ROE, etc). Click → tab Ratios.

#### 4. Tabs (main area)

**Tab P&L**: tabella completa P&L Y-1, Y0, Y1, Y2, Y3 con tutte voci attive. Drill-down per sezione (gross/net/ebitda/ebit/ni) con accordion.

Per ogni cell:
- Hover → tooltip con method applicato + assumption + formula
- Right-click → context menu (override here, edit assumption, etc.)
- Color coding: blu (input/anchor), nero (calculated), grigio (subtotal)

**Tab SP**: tabella SP Y0, Y1, Y2, Y3 (no Y-1 perché spesso Y-1 è incompleto), gerarchica per famiglia (FA, NWC, NFP, Equity).

**Tab CF**: tabella CF Y1, Y2, Y3 (Y0 = anchor balance, no CF storico).

**Tab Ratios**: tabella KPI prospettici Y1-Y3, raggruppati per famiglia. Mini-grafici trend recharts inline.

**Tab Validation**: lista issue raggruppata per severity. Filtri per categoria. Export CSV.

#### 5. Bottombar

- Validation summary (counts per severity)
- Approximation count
- Last run timestamp
- Indicatore "model dirty" (assumption modificate ma non Refresh-ed)

### Refresh policy

**Deferred**: utente preme Refresh esplicitamente.

Eccezione: dopo override creato/disattivato, refresh automatico (perché override richiede propagazione ed è un'azione "intenzionale" dell'utente).

Indicatori visivi:
- "Model in sync" (verde) → ultima run = ultime modifiche
- "Model dirty" (giallo) → assumption modificate dopo ultima run
- Tasto "Refresh" sempre cliccabile, abilita disabled quando run in corso

## Data flow

### Initial load

```
1. GET /api/projects/{id}/snapshot/latest → carica snapshot
2. Render dashboard con dati
3. GET /api/projects/{id}/assumptions → popola sidebar
4. GET /api/projects/{id}/overrides → popola override list
```

### Modifica assumption

```
1. User cambia valore in sidebar
2. PATCH /api/projects/{id}/assumptions/... → save
3. UI mostra "Model dirty" nel bottombar
4. User clicca Refresh
5. POST /api/projects/{id}/run → run + new snapshot
6. UI rilegge snapshot e aggiorna widget centrali
```

### Override

```
1. User clicca "Add override" o right-click su cella
2. Modal "Add override" con: voice, year, delta, nature (organic/one_shot)
3. POST /api/projects/{id}/overrides → save + auto-trigger run
4. UI ricarica snapshot
```

## API consumer perspective

Il backend espone già tutto il necessario in Flow 06, 07, 09. Il frontend è puro consumer di:
- `GET /snapshot/latest` per dati
- `GET /assumptions` per sidebar
- `PATCH /assumptions/...` per modifiche
- `POST /run` per refresh
- CRUD `/overrides`
- `GET /validation-report/historical` e validation incluso in snapshot

## Frontend tech specifics

### State management (Zustand)

```typescript
interface DashboardState {
  project: Project | null
  snapshot: Snapshot | null
  assumptions: Assumption[]
  overrides: Override[]
  
  // UI state
  activeTab: 'pl' | 'sp' | 'cf' | 'ratios' | 'validation'
  selectedYear: 'Y1' | 'Y2' | 'Y3'
  isModelDirty: boolean
  isRunning: boolean
  
  // Actions
  loadProject: (id: string) => Promise<void>
  refreshModel: () => Promise<void>
  updateAssumption: (...) => Promise<void>
  addOverride: (...) => Promise<void>
}
```

### react-query

Cache con stale-time =0 (dati sempre fetch fresh dopo invalidate):

- `useProject(id)` → GET /projects/{id}
- `useSnapshot(id)` → GET /snapshot/latest
- `useAssumptions(id)` → GET /assumptions
- `useOverrides(id)` → GET /overrides

### Componenti

- shadcn `Card`, `Tabs`, `Accordion`, `Badge`, `Button`, `Tooltip`, `Dialog`, `ContextMenu`
- TanStack Table per tabelle FS (sorting, hierarchical rows)
- recharts per mini-trend charts
- react-hook-form per modal override

## Performance

- Initial load <500ms (single API call snapshot)
- Sidebar render <300ms (~250 assumption con virtualization)
- Tab switch <100ms (data già in memory)
- Refresh end-to-end <3s (run engine 2s + reload UI 1s)

## Acceptance criteria

1. Dashboard carica snapshot, mostra 4 mini widget + tabs
2. Sidebar popolata con tutte assumption, espandibile per famiglia
3. Cambio assumption → "Model dirty" indicator
4. Refresh → run engine → UI aggiornata con nuovi numeri
5. Tab switching senza re-fetch
6. Override add via right-click → modal → save + auto-refresh
7. Validation issues visibili in tab Validation
8. Quality score badge cliccabile → modal con sub-score breakdown

## Edge cases

- **Snapshot mancante** (run mai eseguito): mostra empty state con CTA "Run engine"
- **Run in corso**: disabilita modifiche assumption, spinner sul Refresh button
- **Run failed**: mostra error banner con link a validation report
- **Snapshot enorme** (5+ anni, TIER 3): virtualizzazione tabelle obbligatoria

## Test cases

- TC-08-01: load progetto con snapshot → 4 mini widget popolati
- TC-08-02: tab switch → data shown, no refetch
- TC-08-03: cambio assumption → bottombar "model dirty"
- TC-08-04: refresh → backend chiamato, UI aggiornata
- TC-08-05: override add → modal → save → run automatico
- TC-08-06: drill-down P&L → expand sezione → singole voci visibili
- TC-08-07: hover su cella → tooltip con method/assumption/formula
