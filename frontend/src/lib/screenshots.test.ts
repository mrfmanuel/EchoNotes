import { describe, expect, it } from 'vitest'
import { ApiError } from '../api/client'
import { screenshotErrorMessage } from '../api/errors'
import { formatBytes } from './format'
import { imageFromClipboard, isTextEntry, namePastedImage } from './paste'
import { MAX_IMAGE_BYTES, validateImageFile } from './validation'

function imageOfSize(name: string, type: string, size: number): File {
  const file = new File(['x'], name, { type })
  Object.defineProperty(file, 'size', { value: size })
  return file
}

describe('validateImageFile (US-12 AC1/AC2)', () => {
  it('accepts png, jpeg and webp up to 5 MB (1024² bytes)', () => {
    expect(MAX_IMAGE_BYTES).toBe(5_242_880)
    for (const type of ['image/png', 'image/jpeg', 'image/webp']) {
      expect(validateImageFile(imageOfSize('a', type, MAX_IMAGE_BYTES))).toBeNull()
    }
  })

  it('rejects other types and larger files', () => {
    expect(validateImageFile(imageOfSize('a.gif', 'image/gif', 10))).toMatch(/not supported/)
    expect(validateImageFile(imageOfSize('a.svg', 'image/svg+xml', 10))).toMatch(/not supported/)
    expect(validateImageFile(imageOfSize('a.png', 'image/png', MAX_IMAGE_BYTES + 1))).toMatch(
      /larger than 5 MB/,
    )
  })

  it('falls back to the extension when the browser reports no MIME type', () => {
    expect(validateImageFile(imageOfSize('a.JPG', '', 10))).toBeNull()
    expect(validateImageFile(imageOfSize('a.bmp', '', 10))).toMatch(/not supported/)
  })
})

describe('screenshotErrorMessage (US-12 AC2, US-14 AC2)', () => {
  it('maps 413, 415 and 422 to clear messages', () => {
    expect(screenshotErrorMessage(new ApiError(413, 'x', 'image_too_large'))).toMatch(/5 MB/)
    expect(screenshotErrorMessage(new ApiError(415, 'x'))).toMatch(/PNG, JPEG or WebP/)
    expect(screenshotErrorMessage(new ApiError(422, 'Bad link'))).toBe(
      'The screenshot was rejected: Bad link',
    )
    expect(screenshotErrorMessage(new ApiError(0, 'offline'))).toMatch(/reach the server/)
  })
})

describe('paste helpers (US-13)', () => {
  it('treats text inputs, textareas and contenteditable as text entry', () => {
    const text = document.createElement('input')
    const file = document.createElement('input')
    file.type = 'file'
    const editable = document.createElement('div')
    Object.defineProperty(editable, 'isContentEditable', { value: true })
    expect(isTextEntry(text)).toBe(true)
    expect(isTextEntry(document.createElement('textarea'))).toBe(true)
    expect(isTextEntry(editable)).toBe(true)
    expect(isTextEntry(file)).toBe(false)
    expect(isTextEntry(document.body)).toBe(false)
    expect(isTextEntry(null)).toBe(false)
  })

  it('finds the first image in clipboard items or files, else null', () => {
    const png = new File(['x'], 'a.png', { type: 'image/png' })
    const fromItems = {
      items: [{ kind: 'file', type: 'image/png', getAsFile: () => png }],
      files: [],
    } as unknown as DataTransfer
    const fromFiles = { items: [], files: [png] } as unknown as DataTransfer
    const textOnly = {
      items: [{ kind: 'string', type: 'text/plain', getAsFile: () => null }],
      files: [],
    } as unknown as DataTransfer
    expect(imageFromClipboard(fromItems)).toBe(png)
    expect(imageFromClipboard(fromFiles)).toBe(png)
    expect(imageFromClipboard(textOnly)).toBeNull()
    expect(imageFromClipboard(null)).toBeNull()
  })

  it('renames generic clipboard images and keeps real filenames', () => {
    const generic = new File(['x'], 'image.png', { type: 'image/png' })
    const jpeg = new File(['x'], '', { type: 'image/jpeg' })
    const named = new File(['x'], 'diagram.png', { type: 'image/png' })
    expect(namePastedImage(generic).name).toBe('pasted-screenshot.png')
    expect(namePastedImage(jpeg).name).toBe('pasted-screenshot.jpg')
    expect(namePastedImage(named)).toBe(named)
  })
})

describe('formatBytes', () => {
  it('formats bytes, KB and MB with 1024-based units', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1536)).toBe('1.5 KB')
    expect(formatBytes(MAX_IMAGE_BYTES)).toBe('5.0 MB')
  })
})
