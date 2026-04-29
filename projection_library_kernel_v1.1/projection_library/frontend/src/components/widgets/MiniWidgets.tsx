import type { SnapshotDetail, SnapshotValue } from '@/types/snapshot'

import { MiniCard, type MiniCardLine } from './MiniCard'
import { compareYears } from '@/lib/snapshot'

interface MiniWidgetsProps {
  snapshot: SnapshotDetail | null | undefined
  onOpenTab: (tab: 'pl' | 'sp' | 'cf' | 'ratios') => void
}

const PL_HIGHLIGHTS: ReadonlyArray<{ label: string; voiceId: string; emphasis?: boolean }> = [
  { label: 'Revenue (gross)', voiceId: 'pl.rev.gross_total' },
  { label: 'EBITDA', voiceId: 'pl.ebitda', emphasis: true },
  { label: 'EBIT', voiceId: 'pl.ebit' },
  { label: 'Net income', voiceId: 'pl.net_income', emphasis: true },
]

const SP_HIGHLIGHTS: ReadonlyArray<{ label: string; voiceId: string; emphasis?: boolean }> = [
  { label: 'Tangible FA', voiceId: 'bs.fa.tangible.net_close' },
  { label: 'Intangible FA', voiceId: 'bs.fa.intangible.net_close' },
  { label: 'Borrowings', voiceId: 'bs.nfp.borrowings.total_close' },
  { label: 'Equity', voiceId: 'bs.equity.total_close', emphasis: true },
]

const CF_HIGHLIGHTS: ReadonlyArray<{ label: string; voiceId: string; emphasis?: boolean }> = [
  { label: 'CF operating', voiceId: 'cf.operating.total' },
  { label: 'CF investing', voiceId: 'cf.investing.total' },
  { label: 'CF financing', voiceId: 'cf.financing.total' },
  { label: 'Cash close', voiceId: 'cf.cash_close', emphasis: true },
]

function valueAt(
  snapshot: SnapshotDetail | null | undefined,
  voiceId: string,
  year: string | null,
): number | null {
  if (!snapshot || !year) return null
  const match = snapshot.values.find(
    (v: SnapshotValue) => v.voice_id === voiceId && v.year === year,
  )
  return match?.value ?? null
}

function latestProjectionYear(
  snapshot: SnapshotDetail | null | undefined,
): string | null {
  if (!snapshot) return null
  const years = new Set<string>()
  for (const v of snapshot.values) years.add(v.year)
  const sorted = [...years].sort(compareYears)
  return sorted.length ? sorted[sorted.length - 1]! : null
}

function buildLines(
  snapshot: SnapshotDetail | null | undefined,
  highlights: ReadonlyArray<{ label: string; voiceId: string; emphasis?: boolean }>,
  year: string | null,
): MiniCardLine[] {
  return highlights.map((h) => ({
    label: h.label,
    value: valueAt(snapshot, h.voiceId, year),
    emphasis: h.emphasis,
  }))
}

function topKpis(
  snapshot: SnapshotDetail | null | undefined,
  year: string | null,
  limit = 4,
): MiniCardLine[] {
  if (!snapshot || !year) return []
  const kpis = snapshot.projected_kpis as Record<
    string,
    Record<string, number | null> | number | null
  >
  const lines: MiniCardLine[] = []
  for (const [kpiId, payload] of Object.entries(kpis)) {
    if (lines.length >= limit) break
    let v: number | null = null
    if (payload && typeof payload === 'object') {
      const candidate = (payload as Record<string, number | null>)[year]
      v = typeof candidate === 'number' ? candidate : null
    } else if (typeof payload === 'number') {
      v = payload
    }
    lines.push({ label: kpiId, value: v })
  }
  return lines
}

export function MiniWidgets({ snapshot, onOpenTab }: MiniWidgetsProps) {
  const targetYear = latestProjectionYear(snapshot)
  const yearLabel = targetYear ?? '—'

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
      <MiniCard
        title="P&L"
        description={`${yearLabel} highlights`}
        lines={buildLines(snapshot, PL_HIGHLIGHTS, targetYear)}
        onClick={() => onOpenTab('pl')}
      />
      <MiniCard
        title="SP"
        description={`${yearLabel} balance sheet`}
        lines={buildLines(snapshot, SP_HIGHLIGHTS, targetYear)}
        onClick={() => onOpenTab('sp')}
      />
      <MiniCard
        title="CF"
        description={`${yearLabel} cash flow`}
        lines={buildLines(snapshot, CF_HIGHLIGHTS, targetYear)}
        onClick={() => onOpenTab('cf')}
      />
      <MiniCard
        title="KPI snapshot"
        description={`${yearLabel} ratios`}
        lines={topKpis(snapshot, targetYear)}
        footer={
          snapshot && Object.keys(snapshot.projected_kpis).length === 0
            ? 'No projected KPIs in snapshot.'
            : undefined
        }
        onClick={() => onOpenTab('ratios')}
      />
    </div>
  )
}
