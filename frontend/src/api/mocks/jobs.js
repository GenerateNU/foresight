import { ApiError } from '../client.js'

/** Jobs made by mock uploads, by id, so polling them moves through queued, running, succeeded. */
const jobs = new Map()
let nextId = 1

/**
 * One queued job per file, in the shape of JobResponse (backend/foresight/routes/job.py),
 * like POST /hotels/{id}/ingest/files. A file named like "cancel..." is turned away with
 * the API's 422, as Cancellations no longer load; the real API reads the header instead.
 */
export function mockUploadJobs(hotelId, files) {
  const wrong = files.find((file) => /cancel/i.test(file.name))
  if (wrong) throw new ApiError(422, `${wrong.name} is not a known report (expected Daily New Reservations)`)

  return files.map((file, i) => {
    const rows = Math.max(1, Math.round(file.size / 180))
    const job = {
      id: nextId++,
      hotel_id: hotelId,
      kind: 'reservations',
      status: 'queued',
      params: { file: file.name, rows, skipped: 0, first_date: '2026-11-26', last_date: '2026-11-26' },
      progress: {},
      error: null,
      resume_from: null,
      created_at: new Date().toISOString(),
      started_at: null,
      finished_at: null,
    }
    // Files run one at a time, so each starts a little after the one before.
    jobs.set(job.id, { job, startsAt: Date.now() + 1500 * (i + 1) })
    return job
  })
}

/** GET /jobs/{id} for a mock upload's job: queued, then running for 2 seconds, then succeeded. */
export function mockJob(id) {
  const entry = jobs.get(id)
  if (!entry) throw new ApiError(404, `job ${id} not found`)
  const { job, startsAt } = entry
  const elapsed = Date.now() - startsAt
  const rows = job.params.rows
  if (elapsed < 0) return job
  if (elapsed < 2000) {
    const done = Math.round((rows * elapsed) / 2000)
    return { ...job, status: 'running', started_at: new Date(startsAt).toISOString(), progress: { rows_done: done, rows_total: rows } }
  }
  return {
    ...job,
    status: 'succeeded',
    started_at: new Date(startsAt).toISOString(),
    finished_at: new Date(startsAt + 2000).toISOString(),
    progress: { rows_done: rows, rows_total: rows, outcomes: { new: rows, updated: 0, unchanged: 0 } },
  }
}
