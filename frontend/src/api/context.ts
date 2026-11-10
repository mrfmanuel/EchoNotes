import { createContext, useContext } from 'react'
import type { ApiClient } from './client'

export const ApiContext = createContext<ApiClient | null>(null)

/** The API client provided by `<ApiProvider>` (tests inject a mock through it). */
export function useApi(): ApiClient {
  const client = useContext(ApiContext)
  if (!client) throw new Error('useApi must be used inside <ApiProvider>')
  return client
}
