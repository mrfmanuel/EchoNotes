import { useCallback, useEffect, useState } from 'react'

export type LoadState<T> =
  | { status: 'loading' }
  | { status: 'error'; error: unknown }
  | { status: 'ready'; data: T }

export interface UseLoadResult<T> {
  state: LoadState<T>
  /** Fetch again (e.g. "Try again" after an error). */
  reload: () => void
  /** Replace the loaded data locally (after a successful mutation). */
  setData: (data: T) => void
}

/** Runs `loader` whenever `key` changes and tracks loading / error / ready. */
export function useLoad<T>(loader: () => Promise<T>, key: string): UseLoadResult<T> {
  const [state, setState] = useState<LoadState<T>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let active = true
    setState({ status: 'loading' })
    loader().then(
      (data) => active && setState({ status: 'ready', data }),
      (error: unknown) => active && setState({ status: 'error', error }),
    )
    return () => {
      active = false
    }
    // `loader` is recreated on every render; `key` and `attempt` decide when to refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt])

  const reload = useCallback(() => setAttempt((n) => n + 1), [])
  const setData = useCallback((data: T) => setState({ status: 'ready', data }), [])
  return { state, reload, setData }
}
