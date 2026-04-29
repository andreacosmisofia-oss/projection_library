import type { ReactNode } from 'react'

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { formatNumber } from '@/lib/snapshot'

export interface MiniCardLine {
  label: string
  value: number | null | undefined
  /** Visual emphasis for subtotals/totals. */
  emphasis?: boolean
}

interface MiniCardProps {
  title: string
  description?: string
  lines: MiniCardLine[]
  footer?: ReactNode
  onClick?: () => void
  className?: string
}

export function MiniCard({
  title,
  description,
  lines,
  footer,
  onClick,
  className,
}: MiniCardProps) {
  return (
    <Card
      className={cn(
        onClick && 'cursor-pointer transition-colors hover:bg-accent/40',
        className,
      )}
      onClick={onClick}
    >
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{title}</CardTitle>
        {description && (
          <CardDescription className="text-xs">{description}</CardDescription>
        )}
      </CardHeader>
      <CardContent className="space-y-1">
        {lines.length === 0 ? (
          <p className="text-xs text-muted-foreground">No data.</p>
        ) : (
          lines.map((line) => (
            <div
              key={line.label}
              className={cn(
                'flex items-baseline justify-between text-sm',
                line.emphasis && 'font-semibold',
              )}
            >
              <span className="text-muted-foreground">{line.label}</span>
              <span className="tabular-nums">{formatNumber(line.value)}</span>
            </div>
          ))
        )}
        {footer && (
          <div className="pt-2 text-xs text-muted-foreground">{footer}</div>
        )}
      </CardContent>
    </Card>
  )
}
