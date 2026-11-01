import { ApiError } from '../client.js'
import { mockHotel } from './hotels.js'

/**
 * One entry per endpoint: `[path pattern, (path params, query params) => response body]`.
 * Each returns exactly what the real endpoint returns: keep the shapes in step with the
 * backend's *Response schemas (see http://localhost:8000/docs).
 */
const ROUTES = [
  [/^\/hotels\/(\d+)$/, ([id]) => mockHotel(Number(id))],
]

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

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
