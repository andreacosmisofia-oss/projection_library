import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

interface QualityBadgeProps {
  score: number | null | undefined
  className?: string
}

function tierFor(score: number): {
  label: string
  className: string
} {
  if (score >= 70) {
    return {
      label: 'good',
      className: 'bg-emerald-100 text-emerald-900 hover:bg-emerald-200',
    }
  }
  if (score >= 50) {
    return {
      label: 'fair',
      className: 'bg-amber-100 text-amber-900 hover:bg-amber-200',
    }
  }
  return {
    label: 'poor',
    className: 'bg-rose-100 text-rose-900 hover:bg-rose-200',
  }
}

export function QualityBadge({ score, className }: QualityBadgeProps) {
  if (score === null || score === undefined) {
    return (
      <Badge variant="outline" className={className}>
        Quality: —
      </Badge>
    )
  }
  const tier = tierFor(score)
  return (
    <Badge className={cn('border-transparent', tier.className, className)}>
      Quality: {Math.round(score)}/100
    </Badge>
  )
}
