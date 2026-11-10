import { useEffect, useState } from 'react'
import { useApi } from '../api/context'
import { formatBuildInfo } from '../lib/format'

/**
 * Footer with the running version, commit and environment, read once from `/api/health`
 * (US-17 AC4). If the request fails the footer renders nothing, so the page keeps working.
 */
export function AppFooter() {
  const api = useApi()
  const [buildInfo, setBuildInfo] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api.getHealth().then(
      (health) => {
        if (active) setBuildInfo(formatBuildInfo(health))
      },
      () => {
        // Health is informational here: a failure must never break the page.
      },
    )
    return () => {
      active = false
    }
  }, [api])

  if (!buildInfo) return null
  return (
    <footer className="app-footer">
      <span className="app-footer-build">{buildInfo}</span>
    </footer>
  )
}
