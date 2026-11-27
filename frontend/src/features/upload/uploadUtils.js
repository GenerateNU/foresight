/** The Guestline reports the backend reads, recognised from each file's header. */
export const REPORTS = ['Daily New Reservations']

/** The backend's limits per upload (UPLOAD_MAX_FILES and UPLOAD_MAX_FILE_MB in config.py). */
export const MAX_FILES = 10
export const MAX_FILE_MB = 50

/** A job that won't change any more, so it needs no more polling. */
export const FINISHED = ['succeeded', 'failed', 'stopped', 'cancelled']

/**
 * Adds `picked` to the files already `chosen`, dropping exact repeats, and says why any
 * were turned away: only CSVs, each up to MAX_FILE_MB, at most MAX_FILES in all.
 * Returns `{ files, problems }`.
 */
export function addFiles(chosen, picked) {
  const files = [...chosen]
  const problems = []
  for (const file of picked) {
    if (!/\.csv$/i.test(file.name)) {
      problems.push(`${file.name} isn't a CSV. Export the report from Guestline as CSV.`)
    } else if (file.size > MAX_FILE_MB * 1024 * 1024) {
      problems.push(`${file.name} is over ${MAX_FILE_MB} MB.`)
    } else if (files.some((f) => sameFile(f, file))) {
      continue
    } else if (files.length >= MAX_FILES) {
      problems.push(`${file.name} wasn't added: at most ${MAX_FILES} files per upload.`)
    } else {
      files.push(file)
    }
  }
  return { files, problems }
}

function sameFile(a, b) {
  return a.name === b.name && a.size === b.size && a.lastModified === b.lastModified
}

/** "640 B", "18.7 KB" or "2.4 MB". */
export function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
