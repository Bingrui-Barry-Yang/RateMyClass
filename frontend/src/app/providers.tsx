import { QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { createQueryClient } from '@/lib/query-client'

/** App-wide context providers. Add theme/auth providers here as later stages need them. */
export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient)
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}
