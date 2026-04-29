import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { SnapshotSummary } from '@/types/snapshot'

/**
 * POST /api/projects/{id}/run — execute the engine and persist a new
 * snapshot. Invalidates everything snapshot-derived.
 */
export function useRun(projectId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post<SnapshotSummary>(
        `/api/projects/${projectId}/run`,
      )
      return data
    },
    onSuccess: () => {
      if (!projectId) return
      qc.invalidateQueries({ queryKey: ['snapshot', projectId] })
      qc.invalidateQueries({ queryKey: ['validation-latest', projectId] })
      qc.invalidateQueries({ queryKey: ['quality', projectId] })
    },
  })
}
