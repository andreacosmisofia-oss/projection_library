import { useQuery } from '@tanstack/react-query'
import axios from 'axios'

import { api } from '@/lib/api'
import type { SnapshotDetail } from '@/types/snapshot'

/**
 * GET /api/projects/{id}/snapshot/latest
 *
 * The backend returns 404 when the engine has never run for this
 * project. We translate that into `data === null` so the UI can render
 * an empty-state CTA without treating it as a real error.
 */
export function useSnapshot(projectId: string | undefined) {
  return useQuery({
    queryKey: ['snapshot', projectId],
    queryFn: async (): Promise<SnapshotDetail | null> => {
      try {
        const { data } = await api.get<SnapshotDetail>(
          `/api/projects/${projectId}/snapshot/latest`,
        )
        return data
      } catch (err) {
        if (axios.isAxiosError(err) && err.response?.status === 404) {
          return null
        }
        throw err
      }
    },
    enabled: !!projectId,
  })
}
