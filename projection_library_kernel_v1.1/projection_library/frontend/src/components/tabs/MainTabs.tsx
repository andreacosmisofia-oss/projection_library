import { FsTable } from '@/components/tables/FsTable'
import { RatiosTable } from '@/components/tables/RatiosTable'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ValidationPanel } from '@/components/validation/ValidationPanel'
import { pivotSnapshot } from '@/lib/snapshot'
import type { SnapshotDetail } from '@/types/snapshot'
import type {
  HistoricalValidationReport,
  LatestValidationReport,
} from '@/types/validation'
import type { Voice } from '@/types/voice'
import { useDashboardStore } from '@/store/dashboardStore'

interface MainTabsProps {
  snapshot: SnapshotDetail
  voicesById: Map<string, Voice>
  latestValidation: LatestValidationReport | null
  historicalValidation: HistoricalValidationReport | null
}

export function MainTabs({
  snapshot,
  voicesById,
  latestValidation,
  historicalValidation,
}: MainTabsProps) {
  const activeTab = useDashboardStore((s) => s.activeTab)
  const setActiveTab = useDashboardStore((s) => s.setActiveTab)

  const pl = pivotSnapshot(snapshot, 'pl')
  const sp = pivotSnapshot(snapshot, 'sp')
  const cf = pivotSnapshot(snapshot, 'cf')

  return (
    <Tabs
      value={activeTab}
      onValueChange={(v) => setActiveTab(v as typeof activeTab)}
    >
      <TabsList>
        <TabsTrigger value="pl">P&amp;L</TabsTrigger>
        <TabsTrigger value="sp">SP</TabsTrigger>
        <TabsTrigger value="cf">CF</TabsTrigger>
        <TabsTrigger value="ratios">Ratios</TabsTrigger>
        <TabsTrigger value="validation">Validation</TabsTrigger>
      </TabsList>

      <TabsContent value="pl">
        <FsTable
          rows={pl.rows}
          years={pl.years}
          voicesById={voicesById}
          emptyMessage="No P&L voices in this snapshot."
        />
      </TabsContent>

      <TabsContent value="sp">
        <FsTable
          rows={sp.rows}
          years={sp.years}
          voicesById={voicesById}
          emptyMessage="No balance-sheet voices in this snapshot."
        />
      </TabsContent>

      <TabsContent value="cf">
        <FsTable
          rows={cf.rows}
          years={cf.years}
          voicesById={voicesById}
          emptyMessage="No cash-flow voices in this snapshot."
        />
      </TabsContent>

      <TabsContent value="ratios">
        <RatiosTable snapshot={snapshot} />
      </TabsContent>

      <TabsContent value="validation">
        <ValidationPanel
          latest={latestValidation}
          historical={historicalValidation}
        />
      </TabsContent>
    </Tabs>
  )
}
