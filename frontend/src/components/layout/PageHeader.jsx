// The title block at the top of every page: an optional line above, the title, and
// optional controls (buttons, pickers) on the right.
export default function PageHeader({ eyebrow, title, actions }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && <p className="text-sm text-stone-600">{eyebrow}</p>}
        <h1 className="font-display text-4xl font-medium tracking-tight">{title}</h1>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}
