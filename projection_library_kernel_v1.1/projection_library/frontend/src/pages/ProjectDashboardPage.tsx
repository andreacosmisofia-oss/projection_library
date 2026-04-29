import { useParams } from 'react-router-dom'

import { DashboardShell } from '@/components/layout/DashboardShell'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { useDashboardStore } from '@/store/dashboardStore'

const PLACEHOLDER_FAMILIES = [
  'Revenue',
  'Costs',
  'NWC',
  'Capex',
  'Debt',
  'Tax',
]

export function ProjectDashboardPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const setRunning = useDashboardStore((s) => s.setRunning)
  const markClean = useDashboardStore((s) => s.markClean)

  const handleRefresh = () => {
    // Phase 3 will wire this to POST /run + invalidate snapshot.
    setRunning(true)
    setTimeout(() => {
      setRunning(false)
      markClean()
    }, 800)
  }

  return (
    <DashboardShell
      projectName={projectId ? `Project ${projectId.slice(0, 8)}` : null}
      sectorPack="industrial"
      qualityScore={null}
      validationCounts={{ block: 0, error: 0, warning: 0, info: 0 }}
      approxApplied={0}
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
          <p className="mt-4 px-2 text-xs text-muted-foreground/70">
            Phase 4 wires real assumption rows.
          </p>
        </div>
      }
    >
      <div className="grid gap-4">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {(['P&L', 'SP', 'CF', 'KPI'] as const).map((label) => (
            <Card key={label}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">{label} mini</CardTitle>
                <CardDescription>placeholder</CardDescription>
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
              Tabs (P&amp;L / SP / CF / Ratios / Validation) arrive in Phase 4.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Project ID: <code className="text-xs">{projectId}</code>
            </p>
          </CardContent>
        </Card>
      </div>
    </DashboardShell>
  )
}
