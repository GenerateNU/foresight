import { apiGet, apiUpload } from './client.js'

/**
 * POST /hotels/{id}/ingest/files: the day's Guestline exports, one job per file in upload
 * order. A file that isn't a known report, or doesn't parse, is a 422 naming it and
 * nothing is queued.
 */
export async function uploadReports(hotelId, files) {
  const jobs = await apiUpload(`/hotels/${hotelId}/ingest/files`, files)
  return jobs.map(toJob)
}

/** GET /jobs/{id}: where one job is now. */
export async function getJob(jobId) {
  return toJob(await apiGet(`/jobs/${jobId}`))
}

/** One API job in the shape the upload page uses. */
function toJob(job) {
  return {
    id: job.id,
    kind: job.kind,
    status: job.status,
    file: job.params.file,
    rows: job.params.rows,
    firstDate: job.params.first_date,
    lastDate: job.params.last_date,
    rowsDone: job.progress.rows_done ?? 0,
    rowsTotal: job.progress.rows_total ?? job.params.rows,
    // Rows saved by outcome: new, updated (changed since the last upload) or unchanged.
    outcomes: job.progress.outcomes ?? {},
    error: job.error,
  }
}
