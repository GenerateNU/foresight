import PageHeader from '../components/layout/PageHeader.jsx'
import EmptyState from '../components/ui/EmptyState.jsx'

// Stand-in for screens that are designed but not built yet.
export default function PlaceholderPage({ title }) {
  return (
    <div className="space-y-6 px-8 py-8">
      <PageHeader title={title} />
      <EmptyState title="Not built yet" message="This screen is designed but not built yet." />
    </div>
  )
}
