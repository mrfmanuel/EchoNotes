import { useCallback, useEffect, useRef } from 'react'
import { useBlocker } from 'react-router'

export const UNSAVED_CHANGES_MESSAGE = 'You have unsaved changes. Leave this page and discard them?'

/**
 * Warns before leaving with unsaved changes (US-08 AC3): the browser prompt on reload/close
 * (`beforeunload`) and a confirm dialog on in-app navigation (React Router blocker).
 * Call `setBypass(true)` before an intentional navigation (e.g. after deleting) to skip it.
 */
export function useUnsavedChangesWarning(dirty: boolean): { setBypass: (on: boolean) => void } {
  const bypass = useRef(false)
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty && !bypass.current && currentLocation.pathname !== nextLocation.pathname,
  )

  useEffect(() => {
    if (blocker.state !== 'blocked') return
    if (window.confirm(UNSAVED_CHANGES_MESSAGE)) blocker.proceed()
    else blocker.reset()
  }, [blocker])

  useEffect(() => {
    if (!dirty) return
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      // Legacy browsers need returnValue set to show the prompt.
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [dirty])

  const setBypass = useCallback((on: boolean) => {
    bypass.current = on
  }, [])
  return { setBypass }
}
