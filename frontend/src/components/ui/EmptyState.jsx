// What a page or panel shows when it loaded fine but there's nothing to show.
// `action` is optional, e.g. a Button that leads somewhere useful.
export default function EmptyState({ title, message, action }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-card border border-dashed border-stone-200 px-6 py-16 text-center">
      <p className="text-base font-medium">{title}</p>
      {message && <p className="max-w-sm text-sm text-stone-500">{message}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}
