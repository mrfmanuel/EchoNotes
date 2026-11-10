/** Saves `blob` as `filename` through a temporary object URL and `<a download>`. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  try {
    anchor.click()
  } finally {
    anchor.remove()
    // Revoke on the next tick so every browser has started the download first.
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
}
