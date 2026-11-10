import { useState } from 'react'
import { createBrowserRouter, RouterProvider, type DataRouter } from 'react-router'
import { ApiProvider } from './api/ApiProvider'
import { createApiClient, type ApiClient } from './api/client'
import { routes } from './routes'

interface AppProps {
  /** Defaults to the same-origin fetch client; tests pass a mock. */
  client?: ApiClient
  /** Defaults to a browser router; tests pass a memory router. */
  router?: DataRouter
}

function App({ client, router }: AppProps) {
  const [apiClient] = useState(() => client ?? createApiClient())
  const [appRouter] = useState(() => router ?? createBrowserRouter(routes))
  return (
    <ApiProvider client={apiClient}>
      <RouterProvider router={appRouter} />
    </ApiProvider>
  )
}

export default App
