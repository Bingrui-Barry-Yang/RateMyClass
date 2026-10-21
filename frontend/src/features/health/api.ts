import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/lib/api/client'

export const healthKeys = { all: ['health'] as const }

export function useHealth() {
  return useQuery({
    queryKey: healthKeys.all,
    queryFn: ({ signal }) => apiGet('/api/health', { signal }),
  })
}
