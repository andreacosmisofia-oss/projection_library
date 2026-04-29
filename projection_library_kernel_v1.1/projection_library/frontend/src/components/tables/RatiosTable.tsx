import type { SnapshotDetail } from '@/types/snapshot'

import { compareYears, formatNumber } from '@/lib/snapshot'

interface RatiosTableProps {
  snapshot: SnapshotDetail
}

type KpiPayload = Record<string, number | null> | number | null

export function RatiosTable({ snapshot }: RatiosTableProps) {
  const kpis = snapshot.projected_kpis as Record<string, KpiPayload>
  const entries = Object.entries(kpis)

  if (entries.length === 0) {
    return (
      <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
        No projected KPIs in this snapshot.
      </p>
    )
  }

  // Collect every year that appears across the KPI payloads.
  const yearSet = new Set<string>()
  for (const [, payload] of entries) {
    if (payload && typeof payload === 'object') {
      for (const k of Object.keys(payload)) yearSet.add(k)
    }
  }
  const years = [...yearSet].sort(compareYears)

  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-xs uppercase text-muted-foreground">
          <tr>
            <th className="sticky left-0 bg-muted/40 px-3 py-2 text-left font-medium">
              KPI
            </th>
            {years.length > 0 ? (
              years.map((y) => (
                <th key={y} className="px-3 py-2 text-right font-medium">
                  {y}
                </th>
              ))
            ) : (
              <th className="px-3 py-2 text-right font-medium">value</th>
            )}
          </tr>
        </thead>
        <tbody>
          {entries.map(([kpiId, payload]) => (
            <tr key={kpiId} className="border-t">
              <td className="sticky left-0 bg-background px-3 py-1.5">
                <code className="text-xs text-muted-foreground">{kpiId}</code>
              </td>
              {years.length > 0 ? (
                years.map((y) => {
                  let v: number | null = null
                  if (payload && typeof payload === 'object') {
                    const candidate = (payload as Record<string, number | null>)[y]
                    v = typeof candidate === 'number' ? candidate : null
                  }
                  return (
                    <td
                      key={y}
                      className="px-3 py-1.5 text-right tabular-nums"
                    >
                      {formatNumber(v)}
                    </td>
                  )
                })
              ) : (
                <td className="px-3 py-1.5 text-right tabular-nums">
                  {formatNumber(typeof payload === 'number' ? payload : null)}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
