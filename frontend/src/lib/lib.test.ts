import { describe, expect, it } from 'vitest'
import { ApiError } from '../api/client'
import { transcriptionErrorMessage } from '../api/errors'
import { formatDate, formatDuration, formatLanguage } from './format'
import { recordingFile } from './recording'
import { MAX_AUDIO_BYTES, validateAudioFile, validateProjectName } from './validation'

function fileOfSize(name: string, size: number): File {
  const file = new File(['x'], name)
  Object.defineProperty(file, 'size', { value: size })
  return file
}

describe('validateProjectName (mirrors US-01 AC2)', () => {
  it('rejects blank and whitespace-only names', () => {
    expect(validateProjectName('')).not.toBeNull()
    expect(validateProjectName('   ')).not.toBeNull()
  })

  it('accepts 1 to 100 characters after trimming', () => {
    expect(validateProjectName('  a  ')).toBeNull()
    expect(validateProjectName('a'.repeat(100))).toBeNull()
    expect(validateProjectName('a'.repeat(101))).not.toBeNull()
  })
})

describe('validateAudioFile (US-05 AC2/AC3)', () => {
  it.each(['a.mp3', 'a.wav', 'a.m4a', 'a.ogg', 'a.webm', 'A.MP3'])('accepts %s', (name) => {
    expect(validateAudioFile(fileOfSize(name, 10))).toBeNull()
  })

  it('rejects other extensions', () => {
    expect(validateAudioFile(fileOfSize('notes.txt', 10))).toMatch(/not supported/)
  })

  it('accepts exactly 25 MB and rejects one byte more', () => {
    expect(MAX_AUDIO_BYTES).toBe(26_214_400)
    expect(validateAudioFile(fileOfSize('a.mp3', MAX_AUDIO_BYTES))).toBeNull()
    expect(validateAudioFile(fileOfSize('a.mp3', MAX_AUDIO_BYTES + 1))).toMatch(/25 MB/)
  })
})

describe('format helpers', () => {
  it('formats durations as m:ss and unknown when missing', () => {
    expect(formatDuration(125)).toBe('2:05')
    expect(formatDuration(null)).toBe('unknown')
  })

  it('formats dates as YYYY-MM-DD and languages by name', () => {
    expect(formatDate('2026-11-02T09:30:00Z')).toBe('2026-11-02')
    expect(formatLanguage('pt')).toBe('Portuguese')
    expect(formatLanguage(null)).toBe('unknown')
  })
})

describe('recordingFile (#18 recording filename)', () => {
  const now = new Date('2026-11-10T12:34:56.789Z')

  it('names a webm recording recording-<timestamp>.webm', () => {
    const file = recordingFile([new Blob(['a'])], 'audio/webm;codecs=opus', now)
    expect(file.name).toBe('recording-2026-11-10T12-34-56-789Z.webm')
    expect(file.type).toBe('audio/webm')
  })

  it('uses .ogg when the browser records ogg', () => {
    expect(recordingFile([new Blob(['a'])], 'audio/ogg;codecs=opus', now).name).toMatch(/\.ogg$/)
  })
})

describe('transcriptionErrorMessage (US-05 AC2–AC4)', () => {
  it.each([
    [413, /larger than 25 MB/],
    [415, /not supported/],
    [502, /try again/i],
    [504, /timed out.*try again/i],
    [0, /could not reach the server/i],
  ])('maps HTTP %i to a clear message', (status, expected) => {
    expect(transcriptionErrorMessage(new ApiError(status, 'x'))).toMatch(expected)
  })
})
