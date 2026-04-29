import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'

import { useOverrides } from '@/api/useOverrides'
import { useProject } from '@/api/useProject'
import { useQuality } from '@/api/useQuality'
import { useRun } from '@/api/useRun'
import { useSnapshot } from '@/api/useSnapshot'
import {
  useHistoricalValidation,
  useLatestValidation,
} from '@/api/useValidation'
import { indexVoices, useVoices } from '@/api/useVoices'
import { EmptyState } from '@/components/common/EmptyState'
import { DashboardShell } from '@/components/layout/DashboardShell'
import type { ValidationCounts } from '@/components/layout/Bottombar'
import { AddOverrideDialog } from '@/components/overrides/AddOverrideDialog'
import { AssumptionSidebar } from '@/components/sidebar/AssumptionSidebar'
import { MainTabs } from '@/components/tabs/MainTabs'
import { Button } from '@/components/ui/button'
import { MiniWidgets } from '@/components/widgets/MiniWidgets'
import { compareYears } from '@/lib/snapshot'
import { useDashboardStore, type DashboardTab } from '@/store/dashboardStore'

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
  const latestValidation = useLatestValidation(projectId)
  const historicalValidation = useHistoricalValidation(projectId)
  const quality = useQuality(projectId)
  const overrides = useOverrides(projectId)
  const voices = useVoices()
  const run = useRun(projectId)

  const setRunning = useDashboardStore((s) => s.setRunning)
  const markClean = useDashboardStore((s) => s.markClean)
  const setActiveTab = useDashboardStore((s) => s.setActiveTab)

  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false)
  const [overrideVoiceSeed, setOverrideVoiceSeed] = useState<string | undefined>(
    undefined,
  )

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

  const handleAddOverride = (voiceId?: string) => {
    setOverrideVoiceSeed(voiceId)
    setOverrideDialogOpen(true)
  }

  const handleOpenTab = (tab: 'pl' | 'sp' | 'cf' | 'ratios') => {
    setActiveTab(tab as DashboardTab)
  }

  const counts = toCounts(
    latestValidation.data?.summary as Partial<ValidationCounts> | undefined,
  )
  const approxApplied = snapshot.data?.approximation_log.length ?? 0
  const hasNoSnapshot = snapshot.isFetched && snapshot.data === null

  const voicesById = useMemo(
    () => indexVoices(voices.data?.items),
    [voices.data],
  )

  const yearOptions = useMemo(() => {
    if (!snapshot.data) return undefined
    const set = new Set<string>()
    for (const v of snapshot.data.values) set.add(v.year)
    return [...set].sort(compareYears)
  }, [snapshot.data])

  return (
    <>
      <DashboardShell
        projectName={project.data?.name ?? null}
        sectorPack={project.data?.sector_pack ?? null}
        qualityScore={quality.data?.score_total ?? null}
        validationCounts={counts}
        approxApplied={approxApplied}
        onRefresh={handleRefresh}
        sidebar={
          projectId ? (
            <AssumptionSidebar
              projectId={projectId}
              voices={voices.data?.items}
              overrides={overrides.data?.items ?? []}
              onAddOverride={handleAddOverride}
            />
          ) : null
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
        ) : !snapshot.data ? (
          <p className="rounded-md border border-dashed p-10 text-center text-sm text-muted-foreground">
            {snapshot.isLoading
              ? 'Loading snapshot…'
              : snapshot.isError
                ? 'Failed to load snapshot.'
                : '—'}
          </p>
        ) : (
          <div className="space-y-4">
            <MiniWidgets snapshot={snapshot.data} onOpenTab={handleOpenTab} />
            <MainTabs
              snapshot={snapshot.data}
              voicesById={voicesById}
              latestValidation={latestValidation.data ?? null}
              historicalValidation={historicalValidation.data ?? null}
            />
            {run.isError && (
              <p className="text-sm text-destructive">
                Run failed:{' '}
                {run.error instanceof Error
                  ? run.error.message
                  : 'unknown error'}
              </p>
            )}
          </div>
        )}
      </DashboardShell>

      {projectId && (
        <AddOverrideDialog
          projectId={projectId}
          open={overrideDialogOpen}
          onOpenChange={setOverrideDialogOpen}
          initialVoiceId={overrideVoiceSeed}
          yearOptions={yearOptions}
        />
      )}
    </>
  )
}
