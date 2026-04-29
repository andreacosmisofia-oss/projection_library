import { DirtyIndicator } from '@/components/common/DirtyIndicator'
import { useDashboardStore } from '@/store/dashboardStore'

export interface ValidationCounts {
  block: number
  error: number
  warning: number
  info: number
}

interface BottombarProps {
  counts: ValidationCounts
  approxApplied: number
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return '—'
  }
}

export function Bottombar({ counts, approxApplied }: BottombarProps) {
  const isModelDirty = useDashboardStore((s) => s.isModelDirty)
  const lastRunAt = useDashboardStore((s) => s.lastRunAt)

  return (
    <footer className="flex h-10 items-center justify-between border-t bg-muted/40 px-4 text-xs text-muted-foreground">
      <div className="flex items-center gap-4">
        <span className="inline-flex items-center gap-1">
          <span className="text-muted-foreground">⛔</span>
          <span className="font-medium">{counts.block}</span>
        </span>
        <span className="inline-flex items-center gap-1 text-rose-700">
          <span className="h-2 w-2 rounded-full bg-rose-500" />
          {counts.error} errors
        </span>
        <span className="inline-flex items-center gap-1 text-amber-700">
          <span className="h-2 w-2 rounded-full bg-amber-500" />
          {counts.warning} warnings
        </span>
        <span className="inline-flex items-center gap-1 text-sky-700">
          <span className="h-2 w-2 rounded-full bg-sky-500" />
          {counts.info} info
        </span>
        <span className="text-muted-foreground/70">|</span>
        <span>Approx: {approxApplied} applied</span>
      </div>

      <div className="flex items-center gap-4">
        <DirtyIndicator isDirty={isModelDirty} />
        <span>Last run: {formatTime(lastRunAt)}</span>
      </div>
    </footer>
  )
}
