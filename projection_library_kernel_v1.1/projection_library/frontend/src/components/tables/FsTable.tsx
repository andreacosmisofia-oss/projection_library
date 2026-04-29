import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { formatNumber, type PivotedRow } from '@/lib/snapshot'
import type { Voice } from '@/types/voice'

interface FsTableProps {
  rows: PivotedRow[]
  years: string[]
  voicesById: Map<string, Voice>
  emptyMessage?: string
}

function classify(voiceId: string): 'subtotal' | 'derived' | 'leaf' {
  // Heuristic matches the canonical naming convention used in
  // voice_registry.yaml for subtotals.
  if (
    /\.(total|gross_total|net_close|cash_close|adjusted)(_\w+)?$/.test(voiceId)
  ) {
    return 'subtotal'
  }
  if (/^(pl|cf)\.[a-z_]+\.[a-z_]+$/.test(voiceId)) return 'derived'
  return 'leaf'
}

export function FsTable({
  rows,
  years,
  voicesById,
  emptyMessage = 'No values in snapshot.',
}: FsTableProps) {
  if (rows.length === 0) {
    return (
      <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
        {emptyMessage}
      </p>
    )
  }

  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-xs uppercase text-muted-foreground">
          <tr>
            <th className="sticky left-0 bg-muted/40 px-3 py-2 text-left font-medium">
              Voice
            </th>
            {years.map((y) => (
              <th key={y} className="px-3 py-2 text-right font-medium">
                {y}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const meta = voicesById.get(row.voiceId)
            const kind = classify(row.voiceId)
            return (
              <tr
                key={row.voiceId}
                className={cn(
                  'border-t',
                  kind === 'subtotal' && 'bg-muted/30 font-semibold',
                )}
              >
                <td className="sticky left-0 bg-inherit px-3 py-1.5">
                  <div className="flex items-center gap-2">
                    <code className="text-xs text-muted-foreground">
                      {row.voiceId}
                    </code>
                    {row.hasOverride && (
                      <Badge variant="warning" className="px-1 py-0 text-[10px]">
                        ovr
                      </Badge>
                    )}
                  </div>
                  {meta?.section && (
                    <div className="text-[10px] uppercase text-muted-foreground/70">
                      {meta.section}
                    </div>
                  )}
                </td>
                {years.map((y) => {
                  const v = row.values[y]
                  const delta = row.overrideDeltas[y] ?? 0
                  const overridden = delta !== 0
                  return (
                    <td
                      key={y}
                      className={cn(
                        'px-3 py-1.5 text-right tabular-nums',
                        kind === 'leaf' && 'text-sky-700',
                        kind === 'derived' && 'text-foreground',
                        kind === 'subtotal' && 'text-foreground',
                        overridden && 'text-amber-700',
                        v === null && 'text-muted-foreground/50',
                      )}
                      title={
                        overridden
                          ? `override delta: ${formatNumber(delta)}`
                          : undefined
                      }
                    >
                      {formatNumber(v)}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
