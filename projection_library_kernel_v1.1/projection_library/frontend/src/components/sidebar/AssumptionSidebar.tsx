import { AlertTriangle, Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
  useAssumptions,
  usePopulateAssumptions,
  useUpdateAssumption,
} from '@/api/useAssumptions'
import { useDeactivateOverride } from '@/api/useOverrides'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { formatNumber } from '@/lib/snapshot'
import { cn } from '@/lib/utils'
import type { AssumptionRow, AssumptionYear } from '@/types/assumption'
import type { Override } from '@/types/override'

interface AssumptionSidebarProps {
  projectId: string
  overrides: Override[]
  onAddOverride: (voiceId?: string) => void
}

interface Family {
  id: string
  label: string
  match: (voiceId: string) => boolean
}

const FAMILIES: ReadonlyArray<Family> = [
  {
    id: 'revenue',
    label: 'Revenue',
    match: (v) => v.startsWith('pl.rev.'),
  },
  {
    id: 'costs',
    label: 'Costs',
    match: (v) =>
      v.startsWith('pl.cogs.') ||
      v.startsWith('pl.opex.') ||
      v.startsWith('pl.provisions.') ||
      v.startsWith('pl.da.') ||
      v.startsWith('pl.impairment.'),
  },
  {
    id: 'nwc',
    label: 'NWC',
    match: (v) => v.startsWith('bs.nwc.'),
  },
  {
    id: 'capex',
    label: 'Capex',
    match: (v) => v.startsWith('bs.fa.'),
  },
  {
    id: 'debt',
    label: 'Debt',
    match: (v) => v.startsWith('bs.nfp.'),
  },
  {
    id: 'tax',
    label: 'Tax',
    match: (v) =>
      v.startsWith('pl.tax.') ||
      v.includes('deferred_tax') ||
      v.startsWith('bs.tax.'),
  },
]

const YEARS: ReadonlyArray<AssumptionYear> = ['Y1', 'Y2', 'Y3']

const DEBOUNCE_MS = 500

function shortVoiceLabel(voiceId: string): string {
  const parts = voiceId.split('.')
  return parts.slice(-2).join('.') || voiceId
}

function calibrationVariant(
  score: number | null,
): NonNullable<BadgeProps['variant']> {
  if (score == null) return 'outline'
  if (score >= 0.7) return 'success'
  if (score >= 0.4) return 'warning'
  return 'destructive'
}

interface FamilyBucket {
  family: Family
  rows: AssumptionRow[]
  overrides: Override[]
}

function bucketize(
  rows: AssumptionRow[],
  overrides: Override[],
): {
  buckets: FamilyBucket[]
  otherRows: AssumptionRow[]
  otherOverrides: Override[]
} {
  const buckets: FamilyBucket[] = FAMILIES.map((f) => ({
    family: f,
    rows: [],
    overrides: [],
  }))
  const otherRows: AssumptionRow[] = []
  for (const r of rows) {
    const idx = FAMILIES.findIndex((f) => f.match(r.voice_id))
    if (idx >= 0) buckets[idx]!.rows.push(r)
    else otherRows.push(r)
  }
  const otherOverrides: Override[] = []
  for (const o of overrides) {
    const idx = FAMILIES.findIndex((f) => f.match(o.voice_id))
    if (idx >= 0) buckets[idx]!.overrides.push(o)
    else otherOverrides.push(o)
  }
  return { buckets, otherRows, otherOverrides }
}

interface AssumptionInputProps {
  row: AssumptionRow
  year: AssumptionYear
  onCommit: (value: number) => void
}

/**
 * Single Y1/Y2/Y3 input with 500ms debounce. Local state lets the
 * user type freely; commits propagate to the server only after the
 * debounce window. The effect resyncs ``local`` when the canonical
 * value changes externally (populate-defaults, apply-curve), but
 * only if the user isn't mid-edit (heuristic: ``local`` matches the
 * previously seen server value).
 */
function AssumptionInput({ row, year, onCommit }: AssumptionInputProps) {
  const serverValue = row.values[year] ?? 0
  const [local, setLocal] = useState<string>(String(serverValue))
  const lastServerRef = useRef<number>(serverValue)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (
      serverValue !== lastServerRef.current &&
      local === String(lastServerRef.current)
    ) {
      setLocal(String(serverValue))
    }
    lastServerRef.current = serverValue
    // Intentionally exclude `local` from deps: we read it for the
    // mid-edit heuristic but don't want the effect to re-run on
    // every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverValue])

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  const isUserInput = row.source === 'user_input'
  const isFallback = row.source === 'fallback'
  const borderClass = isUserInput
    ? 'border-blue-500 ring-1 ring-blue-200 focus-visible:ring-blue-400'
    : isFallback
      ? 'border-amber-300 border-dashed'
      : 'border-input'

  function handleChange(next: string) {
    setLocal(next)
    if (timerRef.current) clearTimeout(timerRef.current)
    if (next.trim() === '') return
    const parsed = Number(next)
    if (!Number.isFinite(parsed)) return
    if (parsed === serverValue) return
    timerRef.current = setTimeout(() => {
      onCommit(parsed)
    }, DEBOUNCE_MS)
  }

  return (
    <Input
      type="number"
      step="any"
      value={local}
      onChange={(e) => handleChange(e.target.value)}
      className={cn('h-7 px-1.5 text-xs tabular-nums', borderClass)}
      aria-label={`${row.voice_id} ${row.assumption_name} ${year}`}
    />
  )
}

interface AssumptionRowEditorProps {
  projectId: string
  row: AssumptionRow
}

function AssumptionRowEditor({ projectId, row }: AssumptionRowEditorProps) {
  const update = useUpdateAssumption(projectId)
  const calibVariant = calibrationVariant(row.calibration_score)
  const showWarning = row.validation_status === 'warning_range'

  return (
    <div className="space-y-1 rounded-md border bg-card px-2 py-1.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <code
            className="truncate text-[11px] text-muted-foreground"
            title={row.voice_id}
          >
            {shortVoiceLabel(row.voice_id)}
          </code>
          <span className="text-[10px] text-muted-foreground">·</span>
          <span className="truncate text-[11px]" title={row.assumption_name}>
            {row.assumption_name}
          </span>
          {showWarning && (
            <AlertTriangle
              className="h-3 w-3 shrink-0 text-amber-600"
              aria-label="value outside plausibility range"
            />
          )}
        </div>
        <Badge
          variant={calibVariant}
          className="px-1.5 py-0 text-[10px] tabular-nums"
          title={
            row.calibration_score == null
              ? 'no calibration (fallback)'
              : `calibration ${row.calibration_score.toFixed(2)}`
          }
        >
          {row.calibration_score == null
            ? '—'
            : row.calibration_score.toFixed(2)}
        </Badge>
      </div>
      <div className="grid grid-cols-3 gap-1">
        {YEARS.map((year) => (
          <AssumptionInput
            key={year}
            row={row}
            year={year}
            onCommit={(value) =>
              update.mutate({
                voice_id: row.voice_id,
                assumption_name: row.assumption_name,
                year,
                value,
              })
            }
          />
        ))}
      </div>
    </div>
  )
}

export function AssumptionSidebar({
  projectId,
  overrides,
  onAddOverride,
}: AssumptionSidebarProps) {
  const assumptions = useAssumptions(projectId)
  const populate = usePopulateAssumptions(projectId)
  const deactivate = useDeactivateOverride(projectId)

  const activeOverrides = useMemo(
    () => overrides.filter((o) => o.is_active),
    [overrides],
  )
  const { buckets, otherRows, otherOverrides } = useMemo(
    () => bucketize(assumptions.data?.items ?? [], activeOverrides),
    [assumptions.data, activeOverrides],
  )

  const totalRows = assumptions.data?.count ?? 0
  const isEmpty = !assumptions.isLoading && totalRows === 0

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex items-center justify-between px-1">
        <p className="text-xs font-semibold uppercase text-muted-foreground">
          Assumptions
        </p>
        <div className="flex items-center gap-1.5">
          <Button
            size="sm"
            variant="outline"
            onClick={() => populate.mutate()}
            disabled={populate.isPending}
            className="h-7 px-2"
            title="Pre-populate Y1/Y2/Y3 from historical KPIs"
          >
            {populate.isPending ? 'Populating…' : 'Populate defaults'}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => onAddOverride()}
            className="h-7 px-2"
          >
            <Plus className="mr-1 h-3 w-3" /> Override
          </Button>
        </div>
      </div>

      {isEmpty && (
        <p className="rounded-md border bg-muted/40 px-2 py-3 text-xs text-muted-foreground">
          No assumptions yet. Click <strong>Populate defaults</strong> to seed
          them from historical KPIs.
        </p>
      )}

      <Accordion
        type="multiple"
        defaultValue={['revenue', 'costs']}
        className="w-full"
      >
        {buckets.map(({ family, rows, overrides: famOverrides }) => (
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
                  {rows.length} {rows.length === 1 ? 'row' : 'rows'}
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
              {rows.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No assumptions in this family.
                </p>
              ) : (
                <div className="space-y-1.5">
                  {rows.map((r) => (
                    <AssumptionRowEditor
                      key={`${r.voice_id}::${r.method_id}::${r.assumption_name}`}
                      projectId={projectId}
                      row={r}
                    />
                  ))}
                </div>
              )}
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>

      {otherRows.length > 0 && (
        <div className="space-y-1.5 rounded-md border bg-muted/30 p-2">
          <p className="text-[10px] uppercase text-muted-foreground">Other</p>
          {otherRows.map((r) => (
            <AssumptionRowEditor
              key={`${r.voice_id}::${r.method_id}::${r.assumption_name}`}
              projectId={projectId}
              row={r}
            />
          ))}
        </div>
      )}

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
