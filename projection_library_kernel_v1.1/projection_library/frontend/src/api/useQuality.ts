import { useQuery } from '@tanstack/react-query'
import axios from 'axios'

import { api } from '@/lib/api'
import type { QualityScore } from '@/types/quality'

/**
 * GET /api/projects/{id}/quality-score — returns null when the score
 * has never been computed (404).
 */
export function useQuality(projectId: string | undefined) {
  return useQuery({
    queryKey: ['quality', projectId],
    queryFn: async (): Promise<QualityScore | null> => {
      try {
        const { data } = await api.get<QualityScore>(
          `/api/projects/${projectId}/quality-score`,
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
