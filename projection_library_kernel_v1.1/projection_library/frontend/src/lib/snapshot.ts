import type { SnapshotDetail, SnapshotValue } from '@/types/snapshot'

export type Statement = 'pl' | 'sp' | 'cf'

export interface PivotedRow {
  voiceId: string
  /** Sorted list of year keys present for this voice. */
  years: string[]
  /** Map of year → value (null when no value cell). */
  values: Record<string, number | null>
  /** Map of year → override delta (0 when no override applied). */
  overrideDeltas: Record<string, number>
  /** True when at least one year has a non-zero override delta. */
  hasOverride: boolean
}

export interface PivotedSnapshot {
  rows: PivotedRow[]
  /** Sorted (asc) list of all years present across the snapshot. */
  years: string[]
}

const YEAR_PATTERNS: Array<{ re: RegExp; rank: (m: RegExpMatchArray) => number }> =
  [
    { re: /^Y(-?\d+)$/, rank: (m) => Number(m[1]) },
    { re: /^(\d{4})$/, rank: (m) => Number(m[1]) },
  ]

function yearRank(year: string): number {
  for (const { re, rank } of YEAR_PATTERNS) {
    const m = year.match(re)
    if (m) return rank(m)
  }
  // Fallback: lexicographic.
  return year.codePointAt(0) ?? 0
}

export function compareYears(a: string, b: string): number {
  const ra = yearRank(a)
  const rb = yearRank(b)
  if (ra === rb) return a.localeCompare(b)
  return ra - rb
}

export function statementOf(voiceId: string): Statement | null {
  if (voiceId.startsWith('pl.')) return 'pl'
  // Voice registry uses `bs.*` (balance sheet) for the SP statement.
  if (voiceId.startsWith('bs.') || voiceId.startsWith('sp.')) return 'sp'
  if (voiceId.startsWith('cf.')) return 'cf'
  return null
}

/**
 * Pivot the flat snapshot.values list into one row per voice with year
 * columns. When `statement` is provided, restricts to that group.
 */
export function pivotSnapshot(
  snapshot: SnapshotDetail | null | undefined,
  statement?: Statement,
): PivotedSnapshot {
  if (!snapshot) return { rows: [], years: [] }

  const yearSet = new Set<string>()
  const byVoice = new Map<string, SnapshotValue[]>()

  for (const sv of snapshot.values) {
    if (statement && statementOf(sv.voice_id) !== statement) continue
    yearSet.add(sv.year)
    const list = byVoice.get(sv.voice_id) ?? []
    list.push(sv)
    byVoice.set(sv.voice_id, list)
  }

  const years = [...yearSet].sort(compareYears)

  const rows: PivotedRow[] = [...byVoice.entries()]
    .map(([voiceId, vs]) => {
      const values: Record<string, number | null> = {}
      const overrideDeltas: Record<string, number> = {}
      let hasOverride = false
      for (const v of vs) {
        values[v.year] = v.value
        overrideDeltas[v.year] = v.override_delta
        if (v.override_delta !== 0) hasOverride = true
      }
      const rowYears = vs.map((v) => v.year).sort(compareYears)
      return { voiceId, years: rowYears, values, overrideDeltas, hasOverride }
    })
    .sort((a, b) => a.voiceId.localeCompare(b.voiceId))

  return { rows, years }
}

/**
 * EUR_000-style number formatting: thousands separator + sign, two
 * decimals only when the magnitude is below 100. Returns "—" for null.
 */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const abs = Math.abs(value)
  const fractionDigits = abs < 100 ? 2 : 0
  return value.toLocaleString(undefined, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  })
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(1)}%`
}
