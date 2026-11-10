import { useLayoutEffect, useRef } from 'react'

/** Input types where Ctrl+V means "paste text", so the page must not grab the paste. */
const NON_TEXT_INPUT_TYPES = new Set([
  'button',
  'checkbox',
  'color',
  'file',
  'image',
  'radio',
  'range',
  'reset',
  'submit',
])

/** True when `element` is a text input, a textarea or contenteditable (US-13 AC1). */
export function isTextEntry(element: Element | null): boolean {
  if (!element) return false
  if (element instanceof HTMLTextAreaElement) return true
  if (element instanceof HTMLInputElement) return !NON_TEXT_INPUT_TYPES.has(element.type)
  return element instanceof HTMLElement && element.isContentEditable === true
}

/** The first image file in the clipboard data, or null when it holds no image. */
export function imageFromClipboard(data: DataTransfer | null): File | null {
  if (!data) return null
  for (const item of Array.from(data.items ?? [])) {
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) return file
    }
  }
  return Array.from(data.files ?? []).find((file) => file.type.startsWith('image/')) ?? null
}

/** Gives pasted images (often called `image.png` or unnamed) a stable, readable filename. */
export function namePastedImage(file: File): File {
  if (file.name && file.name !== 'image.png') return file
  const ext = file.type.split('/')[1] ?? 'png'
  const extension = ext === 'jpeg' ? 'jpg' : ext
  return new File([file], `pasted-screenshot.${extension}`, { type: file.type })
}

/**
 * Calls `onImage` when the user pastes an image anywhere on the page while no text field is
 * focused (US-13). Pastes without an image are ignored silently (US-13 AC2).
 */
export function usePastedImage(onImage: (file: File) => void, enabled = true): void {
  const callback = useRef(onImage)
  // Layout effects run in the same commit that puts the gallery in the DOM, so the listener
  // (and the latest callback) is in place as soon as the page is visible. Passive effects
  // could run later, and a paste in between was lost (flaky test under CPU load).
  useLayoutEffect(() => {
    callback.current = onImage
  })

  useLayoutEffect(() => {
    if (!enabled) return undefined
    function onPaste(event: ClipboardEvent): void {
      if (isTextEntry(document.activeElement)) return
      if (event.target instanceof Element && isTextEntry(event.target)) return
      const image = imageFromClipboard(event.clipboardData)
      if (!image) return
      event.preventDefault()
      callback.current(namePastedImage(image))
    }
    document.addEventListener('paste', onPaste)
    return () => document.removeEventListener('paste', onPaste)
  }, [enabled])
}
