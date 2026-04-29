import { useEffect } from 'react'
import { useParams } from 'react-router-dom'

import { useOverrides } from '@/api/useOverrides'
import { useProject } from '@/api/useProject'
import { useQuality } from '@/api/useQuality'
import { useRun } from '@/api/useRun'
import { useSnapshot } from '@/api/useSnapshot'
import { useLatestValidation } from '@/api/useValidation'
import { EmptyState } from '@/components/common/EmptyState'
import { DashboardShell } from '@/components/layout/DashboardShell'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import type { ValidationCounts } from '@/components/layout/Bottombar'
import { useDashboardStore } from '@/store/dashboardStore'

const PLACEHOLDER_FAMILIES = [
  'Revenue',
  'Costs',
  'NWC',
  'Capex',
  'Debt',
  'Tax',
]

const ZERO_COUNTS: ValidationCounts = {
  block: 0,
  error: 0,
  warning: 0,
  info: 0,
}

function toCounts(
  summary: Partial<ValidationCounts> | undefined,
): ValidationCounts {
  if (!summary) return ZERO_COUNTS
  return {
    block: summary.block ?? 0,
    error: summary.error ?? 0,
    warning: summary.warning ?? 0,
    info: summary.info ?? 0,
  }
}

export function ProjectDashboardPage() {
  const { projectId } = useParams<{ projectId: string }>()

  const project = useProject(projectId)
  const snapshot = useSnapshot(projectId)
  const validation = useLatestValidation(projectId)
  const quality = useQuality(projectId)
  const overrides = useOverrides(projectId)
  const run = useRun(projectId)

  const setRunning = useDashboardStore((s) => s.setRunning)
  const markClean = useDashboardStore((s) => s.markClean)

  useEffect(() => {
    setRunning(run.isPending)
  }, [run.isPending, setRunning])

  useEffect(() => {
    if (snapshot.data) {
      markClean(snapshot.data.run_timestamp)
    }
  }, [snapshot.data, markClean])

  const handleRefresh = () => {
    run.mutate()
  }

  const counts = toCounts(
    validation.data?.summary as Partial<ValidationCounts> | undefined,
  )
  const approxApplied = snapshot.data?.approximation_log.length ?? 0
  const hasNoSnapshot = snapshot.isFetched && snapshot.data === null

  return (
    <DashboardShell
      projectName={project.data?.name ?? null}
      sectorPack={project.data?.sector_pack ?? null}
      qualityScore={quality.data?.score_total ?? null}
      validationCounts={counts}
      approxApplied={approxApplied}
      onRefresh={handleRefresh}
      sidebar={
        <div className="space-y-1 p-3">
          <p className="px-2 text-xs font-semibold uppercase text-muted-foreground">
            Assumptions
          </p>
          {PLACEHOLDER_FAMILIES.map((family) => (
            <div
              key={family}
              className="rounded-md px-2 py-2 text-sm hover:bg-accent"
            >
              <span className="text-muted-foreground">▸</span>{' '}
              <span className="font-medium">{family}</span>
            </div>
          ))}
          <div className="px-2 pt-4 text-xs text-muted-foreground/70">
            Overrides: {overrides.data?.count ?? 0} active
          </div>
          <p className="mt-4 px-2 text-xs text-muted-foreground/70">
            Phase 4 wires real assumption rows.
          </p>
        </div>
      }
    >
      {hasNoSnapshot ? (
        <EmptyState
          title="No snapshot yet"
          description="Run the engine to generate the first projection."
          action={
            <Button onClick={handleRefresh} disabled={run.isPending}>
              {run.isPending ? 'Running…' : 'Run engine'}
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {(['P&L', 'SP', 'CF', 'KPI'] as const).map((label) => (
              <Card key={label}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">{label} mini</CardTitle>
                  <CardDescription>
                    {snapshot.isLoading ? 'Loading…' : 'placeholder'}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-muted-foreground">
                    Wired in Phase 4.
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Main area</CardTitle>
              <CardDescription>
                Tabs (P&amp;L / SP / CF / Ratios / Validation) arrive in
                Phase 4.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              <div>
                Project ID: <code className="text-xs">{projectId}</code>
              </div>
              <div>
                Latest snapshot:{' '}
                <code className="text-xs">
                  {snapshot.data?.id ?? '—'}
                </code>{' '}
                ({snapshot.data?.status ?? '—'})
              </div>
              {run.isError && (
                <div className="text-rose-700">
                  Run failed:{' '}
                  {run.error instanceof Error
                    ? run.error.message
                    : 'unknown error'}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </DashboardShell>
  )
}
