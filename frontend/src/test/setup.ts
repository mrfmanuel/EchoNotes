import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Every test starts from the same global state, whichever file ran before it in the worker:
// real timers, no leftover `vi.spyOn` spies (e.g. window.confirm) and no stubbed globals.
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
