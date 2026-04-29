import { cn } from '@/lib/utils'

interface DirtyIndicatorProps {
  isDirty: boolean
  className?: string
}

export function DirtyIndicator({ isDirty, className }: DirtyIndicatorProps) {
  return (
    <div
      className={cn(
        'inline-flex items-center gap-1.5 text-xs font-medium',
        className,
      )}
    >
      <span
        className={cn(
          'h-2 w-2 rounded-full',
          isDirty ? 'bg-amber-500' : 'bg-emerald-500',
        )}
        aria-hidden
      />
      <span className={isDirty ? 'text-amber-700' : 'text-emerald-700'}>
        {isDirty ? 'Model dirty' : 'Model in sync'}
      </span>
    </div>
  )
}
