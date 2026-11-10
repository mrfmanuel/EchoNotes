import type { ReactNode } from 'react'
import type { ApiClient } from './client'
import { ApiContext } from './context'

interface ApiProviderProps {
  client: ApiClient
  children: ReactNode
}

export function ApiProvider({ client, children }: ApiProviderProps) {
  return <ApiContext value={client}>{children}</ApiContext>
}
