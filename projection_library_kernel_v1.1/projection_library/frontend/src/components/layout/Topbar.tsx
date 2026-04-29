import { ChevronLeft, MoreVertical, RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'

import { QualityBadge } from '@/components/common/QualityBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useDashboardStore } from '@/store/dashboardStore'

interface TopbarProps {
  projectName: string | null
  sectorPack: string | null
  qualityScore: number | null
  onRefresh?: () => void
}

export function Topbar({
  projectName,
  sectorPack,
  qualityScore,
  onRefresh,
}: TopbarProps) {
  const isRunning = useDashboardStore((s) => s.isRunning)

  return (
    <header className="flex h-14 items-center justify-between border-b bg-background px-4">
      <div className="flex items-center gap-3">
        <Button asChild variant="ghost" size="icon" aria-label="Back">
          <Link to="/projects">
            <ChevronLeft className="h-4 w-4" />
          </Link>
        </Button>
        <div className="flex items-baseline gap-2">
          <h1 className="text-base font-semibold tracking-tight">
            {projectName ?? '—'}
          </h1>
        </div>
        <QualityBadge score={qualityScore} />
        <Badge variant="outline">Sector: {sectorPack ?? '—'}</Badge>
      </div>

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="default"
          onClick={onRefresh}
          disabled={isRunning}
        >
          <RefreshCw
            className={`mr-2 h-4 w-4 ${isRunning ? 'animate-spin' : ''}`}
          />
          {isRunning ? 'Running…' : 'Refresh'}
        </Button>
        <Button size="icon" variant="ghost" aria-label="More options" disabled>
          <MoreVertical className="h-4 w-4" />
        </Button>
      </div>
    </header>
  )
}
