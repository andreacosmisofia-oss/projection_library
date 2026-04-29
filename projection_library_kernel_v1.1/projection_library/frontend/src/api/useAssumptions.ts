import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { useDashboardStore } from '@/store/dashboardStore'
import type {
  AssumptionCurvePayload,
  AssumptionList,
  AssumptionPatchPayload,
  AssumptionRow,
  PopulateReport,
} from '@/types/assumption'

export function assumptionsQueryKey(projectId: string | undefined) {
  return ['assumptions', projectId] as const
}

export function useAssumptions(projectId: string | undefined) {
  return useQuery({
    queryKey: assumptionsQueryKey(projectId),
    queryFn: async () => {
      const { data } = await api.get<AssumptionList>(
        `/api/projects/${projectId}/assumptions`,
      )
      return data
    },
    enabled: !!projectId,
  })
}

/**
 * POST /api/projects/{id}/assumptions/populate-defaults
 *
 * Idempotent: existing user_input rows are preserved. Marks the model
 * dirty so the user knows a Refresh is needed (the populate may have
 * filled new rows or replaced KPI defaults).
 */
export function usePopulateAssumptions(projectId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post<PopulateReport>(
        `/api/projects/${projectId}/assumptions/populate-defaults`,
      )
      return data
    },
    onSuccess: () => {
      if (!projectId) return
      qc.invalidateQueries({ queryKey: assumptionsQueryKey(projectId) })
      useDashboardStore.getState().markDirty()
    },
  })
}

/**
 * PATCH /api/projects/{id}/assumptions/{voice_id}/{assumption_name}/{year}
 *
 * Single-year edit. Source flips to user_input server-side. The
 * snapshot/quality queries are NOT invalidated: the engine has not
 * re-run yet — that's gated by the explicit Refresh action.
 */
export function useUpdateAssumption(projectId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: AssumptionPatchPayload) => {
      const { voice_id, assumption_name, year, value } = payload
      const { data } = await api.patch<AssumptionRow>(
        `/api/projects/${projectId}/assumptions/${encodeURIComponent(
          voice_id,
        )}/${encodeURIComponent(assumption_name)}/${year}`,
        { value },
      )
      return data
    },
    onSuccess: () => {
      if (!projectId) return
      qc.invalidateQueries({ queryKey: assumptionsQueryKey(projectId) })
      useDashboardStore.getState().markDirty()
    },
  })
}

/**
 * POST /api/projects/{id}/assumptions/{voice_id}/{assumption_name}/curve
 *
 * Applies a flat / linear_drift / custom shape. Same dirty semantics
 * as the per-year PATCH.
 */
export function useApplyCurve(projectId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: AssumptionCurvePayload) => {
      const { voice_id, assumption_name, curve_type, y1, y3 } = payload
      const { data } = await api.post<AssumptionRow>(
        `/api/projects/${projectId}/assumptions/${encodeURIComponent(
          voice_id,
        )}/${encodeURIComponent(assumption_name)}/curve`,
        { curve_type, y1, y3 },
      )
      return data
    },
    onSuccess: () => {
      if (!projectId) return
      qc.invalidateQueries({ queryKey: assumptionsQueryKey(projectId) })
      useDashboardStore.getState().markDirty()
    },
  })
}
