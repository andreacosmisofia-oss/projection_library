import { Plus, Trash2 } from 'lucide-react'
import { useMemo } from 'react'

import { useDeactivateOverride } from '@/api/useOverrides'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatNumber } from '@/lib/snapshot'
import type { Override } from '@/types/override'
import type { Voice } from '@/types/voice'

interface AssumptionSidebarProps {
  projectId: string
  voices: Voice[] | undefined
  overrides: Override[]
  onAddOverride: (voiceId?: string) => void
}

interface Family {
  id: string
  label: string
  match: (v: Voice) => boolean
}

const FAMILIES: ReadonlyArray<Family> = [
  {
    id: 'revenue',
    label: 'Revenue',
    match: (v) => v.voice_id.startsWith('pl.rev.'),
  },
  {
    id: 'costs',
    label: 'Costs',
    match: (v) =>
      v.voice_id.startsWith('pl.cogs.') ||
      v.voice_id.startsWith('pl.opex.') ||
      v.voice_id.startsWith('pl.provisions.') ||
      v.voice_id.startsWith('pl.da.') ||
      v.voice_id.startsWith('pl.impairment.'),
  },
  {
    id: 'nwc',
    label: 'NWC',
    match: (v) => v.voice_id.startsWith('bs.nwc.'),
  },
  {
    id: 'capex',
    label: 'Capex',
    match: (v) => v.voice_id.startsWith('bs.fa.'),
  },
  {
    id: 'debt',
    label: 'Debt',
    match: (v) => v.voice_id.startsWith('bs.nfp.'),
  },
  {
    id: 'tax',
    label: 'Tax',
    match: (v) =>
      v.voice_id.startsWith('pl.tax.') ||
      v.voice_id.includes('deferred_tax') ||
      v.voice_id.startsWith('bs.tax.'),
  },
]

interface FamilyBucket {
  family: Family
  voices: Voice[]
  overrides: Override[]
}

function bucketize(
  voices: Voice[] | undefined,
  overrides: Override[],
): { buckets: FamilyBucket[]; otherOverrides: Override[] } {
  const buckets: FamilyBucket[] = FAMILIES.map((f) => ({
    family: f,
    voices: [],
    overrides: [],
  }))
  if (voices) {
    for (const v of voices) {
      const idx = FAMILIES.findIndex((f) => f.match(v))
      if (idx >= 0) buckets[idx]!.voices.push(v)
    }
  }
  const otherOverrides: Override[] = []
  for (const o of overrides) {
    const idx = FAMILIES.findIndex((f) =>
      f.match({ voice_id: o.voice_id } as Voice),
    )
    if (idx >= 0) buckets[idx]!.overrides.push(o)
    else otherOverrides.push(o)
  }
  return { buckets, otherOverrides }
}

export function AssumptionSidebar({
  projectId,
  voices,
  overrides,
  onAddOverride,
}: AssumptionSidebarProps) {
  const activeOverrides = useMemo(
    () => overrides.filter((o) => o.is_active),
    [overrides],
  )
  const { buckets, otherOverrides } = useMemo(
    () => bucketize(voices, activeOverrides),
    [voices, activeOverrides],
  )

  const deactivate = useDeactivateOverride(projectId)

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex items-center justify-between px-1">
        <p className="text-xs font-semibold uppercase text-muted-foreground">
          Assumptions
        </p>
        <Button
          size="sm"
          variant="outline"
          onClick={() => onAddOverride()}
          className="h-7 px-2"
        >
          <Plus className="mr-1 h-3 w-3" /> Override
        </Button>
      </div>

      <Accordion
        type="multiple"
        defaultValue={['revenue', 'costs']}
        className="w-full"
      >
        {buckets.map(({ family, voices: famVoices, overrides: famOverrides }) => (
          <AccordionItem key={family.id} value={family.id}>
            <AccordionTrigger className="px-1">
              <div className="flex w-full items-center justify-between pr-2">
                <span>{family.label}</span>
                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                  {famOverrides.length > 0 && (
                    <Badge
                      variant="warning"
                      className="px-1.5 py-0 text-[10px]"
                    >
                      {famOverrides.length}
                    </Badge>
                  )}
                  {famVoices.length} voices
                </span>
              </div>
            </AccordionTrigger>
            <AccordionContent className="space-y-2 pl-2 pr-1">
              {famOverrides.length > 0 && (
                <div className="space-y-1">
                  <p className="text-[10px] uppercase text-muted-foreground">
                    Active overrides
                  </p>
                  {famOverrides.map((o) => (
                    <div
                      key={o.id}
                      className="flex items-center justify-between rounded-md border bg-amber-50 px-2 py-1 text-xs"
                    >
                      <div className="flex flex-col">
                        <code className="text-muted-foreground">
                          {o.voice_id}
                        </code>
                        <span>
                          {o.year} · {formatNumber(o.delta_amount)} ·{' '}
                          <span className="text-muted-foreground">
                            {o.nature}
                          </span>
                        </span>
                      </div>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-6 w-6"
                        onClick={() => deactivate.mutate(o.id)}
                        disabled={deactivate.isPending}
                        aria-label="Deactivate override"
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
              {famVoices.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No voices loaded yet.
                </p>
              ) : (
                <div className="space-y-0.5">
                  {famVoices.slice(0, 8).map((v) => (
                    <button
                      key={v.voice_id}
                      type="button"
                      onClick={() => onAddOverride(v.voice_id)}
                      className="flex w-full items-center justify-between rounded px-1.5 py-1 text-left text-xs transition-colors hover:bg-accent"
                    >
                      <code className="text-muted-foreground">
                        {v.voice_id}
                      </code>
                      <Plus className="h-3 w-3 opacity-0 group-hover:opacity-100" />
                    </button>
                  ))}
                  {famVoices.length > 8 && (
                    <p className="px-1.5 pt-1 text-[10px] text-muted-foreground/70">
                      …{famVoices.length - 8} more (click + to override any)
                    </p>
                  )}
                </div>
              )}
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>

      {otherOverrides.length > 0 && (
        <div className="space-y-1 rounded-md border bg-amber-50/40 p-2">
          <p className="text-[10px] uppercase text-muted-foreground">
            Other overrides
          </p>
          {otherOverrides.map((o) => (
            <div key={o.id} className="text-xs">
              <code className="text-muted-foreground">{o.voice_id}</code>{' '}
              {o.year} · {formatNumber(o.delta_amount)}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
