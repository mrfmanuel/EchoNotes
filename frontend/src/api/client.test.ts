import { describe, expect, it, vi } from 'vitest'
import { ApiError, createApiClient, filenameFromDisposition } from './client'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function setup(response: Response | Error) {
  const fetchMock = vi.fn((_input: string, _init?: RequestInit) =>
    response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
  )
  return { client: createApiClient('', fetchMock), fetchMock }
}

function formOf(fetchMock: ReturnType<typeof setup>['fetchMock']): FormData {
  const body = fetchMock.mock.calls[0][1]?.body
  expect(body).toBeInstanceOf(FormData)
  return body as FormData
}

describe('API client (follows openapi.yaml)', () => {
  it('listProjects sends GET /api/projects and returns the JSON body', async () => {
    const { client, fetchMock } = setup(jsonResponse(200, [{ id: 'p1' }]))

    await expect(client.listProjects()).resolves.toEqual([{ id: 'p1' }])
    expect(fetchMock).toHaveBeenCalledWith('/api/projects', expect.objectContaining({ method: 'GET' }))
  })

  it('createProject POSTs JSON', async () => {
    const { client, fetchMock } = setup(jsonResponse(201, { id: 'p1', name: 'Notes' }))

    await client.createProject({ name: 'Notes' })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/projects')
    expect(init?.method).toBe('POST')
    expect(init?.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(init?.body).toBe(JSON.stringify({ name: 'Notes' }))
  })

  it('renameProject PATCHes /api/projects/{id}', async () => {
    const { client, fetchMock } = setup(jsonResponse(200, { id: 'p1' }))

    await client.renameProject('p1', { name: 'New' })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/projects/p1')
    expect(fetchMock.mock.calls[0][1]?.method).toBe('PATCH')
  })

  it('deleteProject resolves to undefined on 204', async () => {
    const { client, fetchMock } = setup(new Response(null, { status: 204 }))

    await expect(client.deleteProject('p1')).resolves.toBeUndefined()
    expect(fetchMock.mock.calls[0][1]?.method).toBe('DELETE')
  })

  it('createTranscription sends multipart with file and a non-auto language', async () => {
    const { client, fetchMock } = setup(jsonResponse(201, { id: 't1' }))
    const file = new File(['abc'], 'talk.mp3', { type: 'audio/mpeg' })

    await client.createTranscription('p1', { file, language: 'es', title: 'Talk' })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/projects/p1/transcriptions')
    const form = formOf(fetchMock)
    expect((form.get('file') as File).name).toBe('talk.mp3')
    expect(form.get('language')).toBe('es')
    expect(form.get('title')).toBe('Talk')
  })

  it('createTranscription omits the language field for Auto (US-07 AC2)', async () => {
    const { client, fetchMock } = setup(jsonResponse(201, { id: 't1' }))

    await client.createTranscription('p1', { file: new File(['a'], 'a.wav'), language: 'auto' })

    expect(formOf(fetchMock).has('language')).toBe(false)
  })

  it('updateTranscription PATCHes only the given fields', async () => {
    const { client, fetchMock } = setup(jsonResponse(200, { id: 't1' }))

    await client.updateTranscription('t1', { text: 'new' })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/transcriptions/t1')
    expect(fetchMock.mock.calls[0][1]?.body).toBe('{"text":"new"}')
  })

  it('uploadScreenshot sends file and transcript_id', async () => {
    const { client, fetchMock } = setup(jsonResponse(201, { id: 's1' }))

    await client.uploadScreenshot('p1', { file: new File(['x'], 'a.png'), transcriptId: 't1' })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/projects/p1/screenshots')
    expect(formOf(fetchMock).get('transcript_id')).toBe('t1')
  })

  it('updateScreenshot can unlink with transcript_id null', async () => {
    const { client, fetchMock } = setup(jsonResponse(200, { id: 's1' }))

    await client.updateScreenshot('s1', { transcript_id: null })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/screenshots/s1')
    expect(fetchMock.mock.calls[0][1]?.body).toBe('{"transcript_id":null}')
  })

  it('builds download, image and export URLs', () => {
    const client = createApiClient('')

    expect(client.transcriptDownloadUrl('t1', 'md')).toBe('/api/transcriptions/t1/download?format=md')
    expect(client.transcriptDownloadUrl('t1', 'txt')).toBe('/api/transcriptions/t1/download?format=txt')
    expect(client.screenshotImageUrl('s1')).toBe('/api/screenshots/s1/image')
    expect(client.projectExportUrl('p1')).toBe('/api/projects/p1/export')
  })

  it('exportProject GETs the export and returns the Blob and the Content-Disposition filename', async () => {
    const response = new Response('PK-zip-bytes', {
      status: 200,
      headers: {
        'Content-Type': 'application/zip',
        'Content-Disposition': 'attachment; filename="lecture-notes.zip"',
      },
    })
    const { client, fetchMock } = setup(response)

    const result = await client.exportProject('p1')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/projects/p1/export')
    expect(fetchMock.mock.calls[0][1]?.method).toBe('GET')
    expect(result.filename).toBe('lecture-notes.zip')
    expect(await result.blob.text()).toBe('PK-zip-bytes')
  })

  it('exportProject returns a null filename without Content-Disposition', async () => {
    const { client } = setup(new Response('zip', { status: 200 }))

    await expect(client.exportProject('p1')).resolves.toMatchObject({ filename: null })
  })

  it('exportProject throws ApiError on 404 and on a network failure', async () => {
    const notFound = setup(jsonResponse(404, { detail: 'Project not found', code: 'not_found' }))
    await expect(notFound.client.exportProject('p1')).rejects.toMatchObject({
      status: 404,
      code: 'not_found',
    })

    const offline = setup(new TypeError('Failed to fetch'))
    await expect(offline.client.exportProject('p1')).rejects.toMatchObject({ status: 0 })
  })

  it('filenameFromDisposition reads filename*= and filename=', () => {
    expect(filenameFromDisposition(null)).toBeNull()
    expect(filenameFromDisposition('attachment')).toBeNull()
    expect(filenameFromDisposition('attachment; filename=a.zip')).toBe('a.zip')
    expect(filenameFromDisposition('attachment; filename="b c.zip"')).toBe('b c.zip')
    expect(
      filenameFromDisposition(`attachment; filename="x.zip"; filename*=UTF-8''caf%C3%A9.zip`),
    ).toBe('café.zip')
  })

  it('getHealth returns the body of a 503 (database down)', async () => {
    const body = { status: 'degraded', version: '1.0.0', database: 'error' }
    const { client } = setup(jsonResponse(503, body))

    await expect(client.getHealth()).resolves.toEqual(body)
  })

  it('throws ApiError with status, code and detail on an error response', async () => {
    const { client } = setup(
      jsonResponse(415, { detail: 'Unsupported audio type', code: 'unsupported_media_type' }),
    )

    const error = await client
      .createTranscription('p1', { file: new File(['a'], 'a.txt') })
      .catch((err: unknown) => err)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 415, code: 'unsupported_media_type' })
    expect((error as ApiError).firstMessage).toBe('Unsupported audio type')
  })

  it('exposes the first message of a FastAPI 422 detail list', async () => {
    const { client } = setup(
      jsonResponse(422, { detail: [{ loc: ['body', 'name'], msg: 'String too long' }] }),
    )

    const error = (await client.createProject({ name: 'x' }).catch((err: unknown) => err)) as ApiError

    expect(error.status).toBe(422)
    expect(error.firstMessage).toBe('String too long')
  })

  it('maps a network failure to ApiError with status 0', async () => {
    const { client } = setup(new TypeError('Failed to fetch'))

    await expect(client.listProjects()).rejects.toMatchObject({ status: 0 })
  })

  it('falls back to the status text for a non-JSON error body', async () => {
    const { client } = setup(new Response('<html>', { status: 500, statusText: 'Server Error' }))

    await expect(client.listProjects()).rejects.toMatchObject({ status: 500, detail: 'Server Error' })
  })
})
