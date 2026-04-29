import { useMemo, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type {
  HistoricalValidationReport,
  LatestValidationReport,
  Severity,
  ValidationIssue,
} from '@/types/validation'

interface ValidationPanelProps {
  latest: LatestValidationReport | null
  historical: HistoricalValidationReport | null
}

const ALL_SEVERITIES: ReadonlyArray<Severity> = [
  'block',
  'error',
  'warning',
  'info',
]

const SEVERITY_BADGE: Record<Severity, 'destructive' | 'warning' | 'secondary'> =
  {
    block: 'destructive',
    error: 'destructive',
    warning: 'warning',
    info: 'secondary',
  }

const SEVERITY_RANK: Record<Severity, number> = {
  block: 0,
  error: 1,
  warning: 2,
  info: 3,
}

function countBy(issues: ValidationIssue[]): Record<Severity, number> {
  const out: Record<Severity, number> = { block: 0, error: 0, warning: 0, info: 0 }
  for (const i of issues) out[i.severity] += 1
  return out
}

export function ValidationPanel({ latest, historical }: ValidationPanelProps) {
  const [activeFilter, setActiveFilter] = useState<Severity | 'all'>('all')
  const [source, setSource] = useState<'latest' | 'historical'>('latest')

  const issues = useMemo<ValidationIssue[]>(() => {
    if (source === 'latest') return latest?.issues ?? []
    return historical?.issues ?? []
  }, [latest, historical, source])

  const counts = useMemo(() => countBy(issues), [issues])

  const filtered = useMemo(() => {
    const base =
      activeFilter === 'all'
        ? issues
        : issues.filter((i) => i.severity === activeFilter)
    return [...base].sort(
      (a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity],
    )
  }, [issues, activeFilter])

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1 rounded-md border bg-muted/30 p-1 text-xs">
          <button
            type="button"
            onClick={() => setSource('latest')}
            className={cn(
              'rounded px-2 py-1 transition-colors',
              source === 'latest'
                ? 'bg-background shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            Engine run
          </button>
          <button
            type="button"
            onClick={() => setSource('historical')}
            className={cn(
              'rounded px-2 py-1 transition-colors',
              source === 'historical'
                ? 'bg-background shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            Historical intake
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-1">
          <Button
            size="sm"
            variant={activeFilter === 'all' ? 'default' : 'outline'}
            onClick={() => setActiveFilter('all')}
          >
            All ({issues.length})
          </Button>
          {ALL_SEVERITIES.map((sev) => (
            <Button
              key={sev}
              size="sm"
              variant={activeFilter === sev ? 'default' : 'outline'}
              onClick={() => setActiveFilter(sev)}
              disabled={counts[sev] === 0}
            >
              {sev} ({counts[sev]})
            </Button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
          No issues for this filter.
        </p>
      ) : (
        <ul className="divide-y rounded-md border">
          {filtered.map((issue, idx) => (
            <li
              key={`${issue.rule_id}:${idx}`}
              className="flex flex-col gap-1 p-3 text-sm"
            >
              <div className="flex items-center gap-2">
                <Badge variant={SEVERITY_BADGE[issue.severity]}>
                  {issue.severity}
                </Badge>
                <code className="text-xs text-muted-foreground">
                  {issue.rule_id}
                </code>
                {issue.voice_id && (
                  <code className="text-xs text-muted-foreground">
                    @{issue.voice_id}
                  </code>
                )}
                {issue.year && (
                  <code className="text-xs text-muted-foreground">
                    {issue.year}
                  </code>
                )}
              </div>
              <p>{issue.message}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
