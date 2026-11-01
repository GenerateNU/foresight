import Button from './Button.jsx'

// What a page or panel shows when loading failed. Pass `onRetry` to offer a retry button.
export default function ErrorState({ title = 'Something went wrong', error, onRetry }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-2 rounded-card border border-error-200 bg-error-50 p-4">
      <p className="text-sm font-medium text-error-700">{title}</p>
      {error && <p className="text-sm text-error-700">{error.message}</p>}
      {onRetry && (
        <Button size="sm" onClick={onRetry} className="mt-1">
          Try again
        </Button>
      )}
    </div>
  )
}
