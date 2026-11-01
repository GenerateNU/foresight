// Fake responses for VITE_USE_MOCKS=true, so screens can be built before the backend is ready.
// Each route returns exactly what the real endpoint returns: keep the shapes in step with
// the backend's *Response schemas (see http://localhost:8000/docs).
import { ApiError } from '../client.js'
import { mockHotel } from './hotels.js'

const ROUTES = [
  // [path pattern, (path params, query params) => response body]
  [/^\/hotels\/(\d+)$/, ([id]) => mockHotel(Number(id))],
]

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
