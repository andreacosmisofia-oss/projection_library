import { useQuery } from '@tanstack/react-query'
import axios from 'axios'

import { api } from '@/lib/api'
import type {
  HistoricalValidationReport,
  LatestValidationReport,
} from '@/types/validation'

/**
 * GET /api/projects/{id}/validation-report/latest — engine-time issues.
 * Returns null when no snapshot exists yet (404).
 */
export function useLatestValidation(projectId: string | undefined) {
  return useQuery({
    queryKey: ['validation-latest', projectId],
    queryFn: async (): Promise<LatestValidationReport | null> => {
      try {
        const { data } = await api.get<LatestValidationReport>(
          `/api/projects/${projectId}/validation-report/latest`,
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

/**
 * GET /api/projects/{id}/validation-report/historical — intake-time
 * issues. Returns null when validation has never been run (404).
 */
export function useHistoricalValidation(projectId: string | undefined) {
  return useQuery({
    queryKey: ['validation-historical', projectId],
    queryFn: async (): Promise<HistoricalValidationReport | null> => {
      try {
        const { data } = await api.get<HistoricalValidationReport>(
          `/api/projects/${projectId}/validation-report/historical`,
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
