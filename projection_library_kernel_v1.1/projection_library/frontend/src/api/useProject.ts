import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { Project } from '@/types/project'

export function useProject(projectId: string | undefined) {
  return useQuery({
    queryKey: ['project', projectId],
    queryFn: async () => {
      const { data } = await api.get<Project>(`/api/projects/${projectId}`)
      return data
    },
    enabled: !!projectId,
  })
}
