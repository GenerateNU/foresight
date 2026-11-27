import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getJob, uploadReports } from '../../api/uploads.js'
import PageHeader from '../../components/layout/PageHeader.jsx'
import Button from '../../components/ui/Button.jsx'
import Card from '../../components/ui/Card.jsx'
import ErrorState from '../../components/ui/ErrorState.jsx'
import { useAuth } from '../auth/useAuth.js'
import DropZone from './DropZone.jsx'
import JobStatus from './JobStatus.jsx'
import { FINISHED, addFiles, formatSize } from './uploadUtils.js'

/** How often to ask about unfinished jobs. */
const POLL_MS = 1500

/**
 * The Guestline upload, daily or a backfill of past bookings: pick the exports, check them in the browser, send them, then
 * poll each file's job until it finishes. It never starts training; new rates come from
 * the next scheduled retrain.
 */
export default function UploadPage() {
  const { hotel } = useAuth()
  const [files, setFiles] = useState([])
  const [problems, setProblems] = useState([])
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState(null)
  const [jobs, setJobs] = useState(null)
  const [pollError, setPollError] = useState(null)

  const unfinished = jobs?.filter((job) => !FINISHED.includes(job.status)) ?? []
  const pollKey = unfinished.map((job) => `${job.id}:${job.status}:${job.rowsDone}`).join(',')

  useEffect(() => {
    if (!pollKey) return
    const ids = pollKey.split(',').map((entry) => Number(entry.split(':')[0]))
    const timer = setTimeout(async () => {
      try {
        const fresh = await Promise.all(ids.map(getJob))
        setPollError(null)
        setJobs((current) => current.map((job) => fresh.find((f) => f.id === job.id) ?? job))
      } catch (err) {
        // Shown under the list; changing pollError doesn't change pollKey, so retry by hand.
        setPollError(err)
      }
    }, POLL_MS)
    return () => clearTimeout(timer)
  }, [pollKey])

  function pick(picked) {
    const result = addFiles(files, picked)
    setFiles(result.files)
    setProblems(result.problems)
    setSendError(null)
  }

  async function send() {
    setSending(true)
    setSendError(null)
    try {
      setJobs(await uploadReports(hotel.id, files))
      setFiles([])
      setProblems([])
    } catch (err) {
      setSendError(err)
    } finally {
      setSending(false)
    }
  }

  function startOver() {
    setJobs(null)
    setPollError(null)
  }

  const allDone = jobs && unfinished.length === 0
  const allLoaded = allDone && jobs.every((job) => job.status === 'succeeded')

  return (
    <div className="flex max-w-3xl flex-col gap-6 px-8 py-8">
      <PageHeader title="Upload data" />

      {jobs ? (
        <Card className="flex flex-col gap-4 shadow-sm">
          <h2 className="text-lg font-medium">{allDone ? 'Upload finished' : 'Loading your files…'}</h2>
          <ul className="divide-y divide-stone-100">
            {jobs.map((job) => (
              <JobStatus key={job.id} job={job} />
            ))}
          </ul>
          {pollError && (
            <ErrorState
              title="Couldn't check on the upload"
              error={pollError}
              onRetry={() => setJobs((current) => [...current])}
            />
          )}
          {allLoaded && (
            <p className="rounded-control bg-success-50 px-4 py-3 text-sm text-success-700">
              Rates will update after the next retrain.{' '}
              <Link to="/calendar" className="font-medium underline">
                Go to the calendar
              </Link>
            </p>
          )}
          {allDone && (
            <Button size="sm" className="self-start" onClick={startOver}>
              Upload more files
            </Button>
          )}
        </Card>
      ) : (
        <>
          <DropZone onFiles={pick} disabled={sending} />

          {problems.length > 0 && (
            <div role="alert" className="rounded-card border border-error-200 bg-error-50 p-4 text-sm text-error-700">
              <p className="font-medium">Some files weren't added</p>
              <ul className="mt-1 list-disc pl-5">
                {problems.map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            </div>
          )}

          {files.length > 0 && (
            <Card className="flex flex-col gap-4 shadow-sm">
              <h2 className="text-lg font-medium">
                {files.length} {files.length === 1 ? 'file' : 'files'} ready
              </h2>
              <ul className="divide-y divide-stone-100">
                {files.map((file) => (
                  <li key={`${file.name}:${file.size}`} className="flex items-center justify-between gap-4 py-2 first:pt-0 last:pb-0">
                    <span className="min-w-0 truncate text-sm font-medium">{file.name}</span>
                    <span className="flex shrink-0 items-center gap-3 text-xs text-stone-500">
                      {formatSize(file.size)}
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={sending}
                        onClick={() => {
                          setFiles(files.filter((f) => f !== file))
                          setSendError(null)
                        }}
                        aria-label={`Remove ${file.name}`}
                      >
                        Remove
                      </Button>
                    </span>
                  </li>
                ))}
              </ul>
              {sendError && <ErrorState title="Nothing was uploaded" error={sendError} />}
              <Button variant="primary" className="self-start" onClick={send} disabled={sending}>
                {sending ? 'Uploading…' : `Upload ${files.length === 1 ? 'file' : `${files.length} files`}`}
              </Button>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
