import type { ReactNode } from 'react'

import { Bottombar, type ValidationCounts } from './Bottombar'
import { Topbar } from './Topbar'

interface DashboardShellProps {
  projectName: string | null
  sectorPack: string | null
  qualityScore: number | null
  validationCounts: ValidationCounts
  approxApplied: number
  onRefresh?: () => void
  sidebar: ReactNode
  children: ReactNode
}

export function DashboardShell({
  projectName,
  sectorPack,
  qualityScore,
  validationCounts,
  approxApplied,
  onRefresh,
  sidebar,
  children,
}: DashboardShellProps) {
  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <Topbar
        projectName={projectName}
        sectorPack={sectorPack}
        qualityScore={qualityScore}
        onRefresh={onRefresh}
      />

      <div className="flex flex-1 min-h-0">
        <aside className="w-80 shrink-0 overflow-y-auto border-r bg-muted/20">
          {sidebar}
        </aside>
        <main className="flex-1 overflow-y-auto p-4">{children}</main>
      </div>

      <Bottombar counts={validationCounts} approxApplied={approxApplied} />
    </div>
  )
}
