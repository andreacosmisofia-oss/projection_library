import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { ProjectList } from '@/types/project'

export function useProjects() {
  return useQuery({
    queryKey: ['projects'],
    queryFn: async () => {
      const { data } = await api.get<ProjectList>('/api/projects')
      return data
    },
  })
}
