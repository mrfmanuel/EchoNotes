import { render } from '@testing-library/react'
import { createMemoryRouter } from 'react-router'
import App from '../App'
import { routes } from '../routes'
import { createMockClient, type MockApiClient } from './mockClient'

/** Renders the real routes at `path` with a mocked API client and an in-memory router. */
export function renderApp(path: string, client: MockApiClient = createMockClient()) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const view = render(<App client={client} router={router} />)
  return { ...view, router, client }
}
