import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { Voice, VoiceList } from '@/types/voice'

/**
 * GET /api/registry/voices — voices are static across the session
 * (registry loaded at server startup), so we can keep them cached for
 * the lifetime of the page.
 */
export function useVoices() {
  return useQuery({
    queryKey: ['registry', 'voices'],
    queryFn: async () => {
      const { data } = await api.get<VoiceList>('/api/registry/voices')
      return data
    },
    staleTime: Infinity,
  })
}

/** Build a Map<voice_id, Voice> for fast lookups in tables and the sidebar. */
export function indexVoices(voices: Voice[] | undefined): Map<string, Voice> {
  const map = new Map<string, Voice>()
  if (!voices) return map
  for (const v of voices) map.set(v.voice_id, v)
  return map
}
