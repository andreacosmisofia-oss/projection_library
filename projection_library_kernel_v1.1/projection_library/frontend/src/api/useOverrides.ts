import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type {
  Override,
  OverrideCreatePayload,
  OverrideList,
} from '@/types/override'

export function overridesQueryKey(projectId: string | undefined) {
  return ['overrides', projectId] as const
}

export function useOverrides(projectId: string | undefined) {
  return useQuery({
    queryKey: overridesQueryKey(projectId),
    queryFn: async () => {
      const { data } = await api.get<OverrideList>(
        `/api/projects/${projectId}/overrides`,
      )
      return data
    },
    enabled: !!projectId,
  })
}

/**
 * POST /api/projects/{id}/overrides — auto-triggers a run on the
 * backend, so we invalidate everything snapshot-derived.
 */
export function useCreateOverride(projectId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: OverrideCreatePayload) => {
      const { data } = await api.post<Override>(
        `/api/projects/${projectId}/overrides`,
        payload,
      )
      return data
    },
    onSuccess: () => {
      if (!projectId) return
      qc.invalidateQueries({ queryKey: overridesQueryKey(projectId) })
      qc.invalidateQueries({ queryKey: ['snapshot', projectId] })
      qc.invalidateQueries({ queryKey: ['validation-latest', projectId] })
      qc.invalidateQueries({ queryKey: ['quality', projectId] })
    },
  })
}

export function useDeactivateOverride(projectId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (overrideId: string) => {
      const { data } = await api.patch<Override>(
        `/api/projects/${projectId}/overrides/${overrideId}`,
        { is_active: false },
      )
      return data
    },
    onSuccess: () => {
      if (!projectId) return
      qc.invalidateQueries({ queryKey: overridesQueryKey(projectId) })
      qc.invalidateQueries({ queryKey: ['snapshot', projectId] })
      qc.invalidateQueries({ queryKey: ['validation-latest', projectId] })
      qc.invalidateQueries({ queryKey: ['quality', projectId] })
    },
  })
}
