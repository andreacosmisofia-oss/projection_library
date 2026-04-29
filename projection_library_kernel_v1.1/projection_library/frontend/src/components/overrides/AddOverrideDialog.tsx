import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { useCreateOverride } from '@/api/useOverrides'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

const FormSchema = z.object({
  voice_id: z.string().min(1, 'voice_id is required'),
  year: z.string().min(1, 'year is required'),
  delta_amount: z
    .string()
    .min(1, 'delta_amount is required')
    .refine((v) => Number.isFinite(Number(v)), {
      message: 'must be a number',
    })
    .refine((v) => Number(v) !== 0, {
      message: 'delta_amount cannot be zero',
    }),
  nature: z.enum(['organic', 'one_shot']),
  user_note: z.string().max(1024).optional(),
})

type FormValues = z.infer<typeof FormSchema>

interface AddOverrideDialogProps {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  initialVoiceId?: string
  yearOptions?: string[]
}

export function AddOverrideDialog({
  projectId,
  open,
  onOpenChange,
  initialVoiceId,
  yearOptions,
}: AddOverrideDialogProps) {
  const create = useCreateOverride(projectId)

  const form = useForm<FormValues>({
    resolver: zodResolver(FormSchema),
    defaultValues: {
      voice_id: initialVoiceId ?? '',
      year: yearOptions?.[0] ?? '',
      delta_amount: '',
      nature: 'organic',
      user_note: '',
    },
  })

  useEffect(() => {
    if (open) {
      form.reset({
        voice_id: initialVoiceId ?? '',
        year: yearOptions?.[0] ?? '',
        delta_amount: '',
        nature: 'organic',
        user_note: '',
      })
    }
  }, [open, initialVoiceId, yearOptions, form])

  const onSubmit = form.handleSubmit(async (values) => {
    await create.mutateAsync({
      voice_id: values.voice_id,
      year: values.year,
      delta_amount: Number(values.delta_amount),
      nature: values.nature,
      user_note: values.user_note?.trim() || null,
    })
    onOpenChange(false)
  })

  const errors = form.formState.errors

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add override</DialogTitle>
          <DialogDescription>
            Adds a delta on top of the engine result. Triggers a refresh
            on save.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="voice_id">Voice</Label>
            <Input
              id="voice_id"
              placeholder="e.g. pl.rev.gross.product_sales"
              {...form.register('voice_id')}
            />
            {errors.voice_id && (
              <p className="text-xs text-destructive">
                {errors.voice_id.message}
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="year">Year</Label>
              {yearOptions && yearOptions.length > 0 ? (
                <select
                  id="year"
                  className={cn(
                    'flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
                  )}
                  {...form.register('year')}
                >
                  {yearOptions.map((y) => (
                    <option key={y} value={y}>
                      {y}
                    </option>
                  ))}
                </select>
              ) : (
                <Input id="year" placeholder="Y3" {...form.register('year')} />
              )}
              {errors.year && (
                <p className="text-xs text-destructive">
                  {errors.year.message}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="delta_amount">Delta amount</Label>
              <Input
                id="delta_amount"
                type="number"
                step="any"
                {...form.register('delta_amount')}
              />
              {errors.delta_amount && (
                <p className="text-xs text-destructive">
                  {errors.delta_amount.message}
                </p>
              )}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Nature</Label>
            <div className="flex gap-2">
              {(['organic', 'one_shot'] as const).map((opt) => (
                <label
                  key={opt}
                  className="flex flex-1 items-center justify-center gap-2 rounded-md border bg-background px-3 py-2 text-sm shadow-sm has-[:checked]:border-primary has-[:checked]:bg-primary/5"
                >
                  <input
                    type="radio"
                    value={opt}
                    {...form.register('nature')}
                  />
                  <span>{opt}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="user_note">Note (optional)</Label>
            <Textarea
              id="user_note"
              rows={2}
              placeholder="Why this override?"
              {...form.register('user_note')}
            />
          </div>

          {create.isError && (
            <p className="text-xs text-destructive">
              Save failed:{' '}
              {create.error instanceof Error
                ? create.error.message
                : 'unknown error'}
            </p>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={create.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? 'Saving…' : 'Save & refresh'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
