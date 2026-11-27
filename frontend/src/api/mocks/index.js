import { ApiError } from '../client.js'
import { mockMe } from './hotels.js'
import { mockJob, mockUploadJobs } from './jobs.js'
import { mockRecommendations } from './recommendations.js'

/**
 * One entry per endpoint: `[path pattern, (path params, query params) => response body]`.
 * Each returns exactly what the real endpoint returns: keep the shapes in step with the
 * backend's *Response schemas (see http://localhost:8000/docs).
 */
const ROUTES = [
  [/^\/auth\/me$/, () => mockMe()],
  [/^\/hotels\/(\d+)\/recommendations$/, ([id], query) => mockRecommendations(Number(id), query)],
  [/^\/jobs\/(\d+)$/, ([id]) => mockJob(Number(id))],
]

/** The same, for uploads: `[path pattern, (path params, files) => response body]`. */
const UPLOADS = [[/^\/hotels\/(\d+)\/ingest\/files$/, ([id], files) => mockUploadJobs(Number(id), files)]]

/** The fake `apiGet` behind VITE_USE_MOCKS=true, so screens work before the backend does. */
export async function mockGet(path, params) {
  for (const [pattern, respond] of ROUTES) {
    const match = path.match(pattern)
    if (match) {
      await delay(300) // long enough that loading states are visible
      return respond(match.slice(1), params)
    }
  }
  throw new ApiError(404, `No mock for GET ${path}. Add one in src/api/mocks/index.js.`)
}

/** The fake `apiUpload` behind VITE_USE_MOCKS=true. */
export async function mockUpload(path, files) {
  for (const [pattern, respond] of UPLOADS) {
    const match = path.match(pattern)
    if (match) {
      await delay(600)
      return respond(match.slice(1), files)
    }
  }
  throw new ApiError(404, `No mock for upload to ${path}. Add one in src/api/mocks/index.js.`)
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
