import type { RouteObject } from 'react-router'
import { Layout } from './components/Layout'
import { NotFound } from './components/StatusViews'
import { ProjectPage } from './pages/ProjectPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { TranscriptPage } from './pages/TranscriptPage'

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <ProjectsPage /> },
      { path: 'projects/:projectId', element: <ProjectPage /> },
      { path: 'transcripts/:transcriptId', element: <TranscriptPage /> },
      { path: '*', element: <NotFound what="Page" /> },
    ],
  },
]
