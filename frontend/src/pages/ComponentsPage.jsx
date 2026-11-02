import { useState } from 'react'
import PageHeader from '../components/layout/PageHeader.jsx'
import Badge from '../components/ui/Badge.jsx'
import Button from '../components/ui/Button.jsx'
import Card from '../components/ui/Card.jsx'
import Chip from '../components/ui/Chip.jsx'
import EmptyState from '../components/ui/EmptyState.jsx'
import ErrorState from '../components/ui/ErrorState.jsx'
import Input from '../components/ui/Input.jsx'
import LoadingState from '../components/ui/LoadingState.jsx'
import Skeleton from '../components/ui/Skeleton.jsx'
import Spinner from '../components/ui/Spinner.jsx'

function Section({ title, children }) {
  return (
    <Card className="space-y-4">
      <h2 className="text-sm font-medium text-stone-600">{title}</h2>
      {children}
    </Card>
  )
}

/**
 * Every shared component on one page, to check how they look and to copy usage from.
 * Only routed in development (see App.jsx). Add a section when you add a component.
 */
export default function ComponentsPage() {
  const [chip, setChip] = useState('demand')

  return (
    <div className="space-y-6 px-8 py-8">
      <PageHeader eyebrow="Development only" title="Components" actions={<Button variant="primary">Action</Button>} />

      <Section title="Button">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary">Primary</Button>
          <Button>Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">Danger</Button>
          <Button size="sm">Small</Button>
          <Button size="icon" aria-label="Next">
            ›
          </Button>
          <Button disabled>Disabled</Button>
        </div>
      </Section>

      <Section title="Input">
        <div className="grid max-w-md gap-4">
          <Input label="Hotel name" placeholder="The Linden House" hint="As guests see it." />
          <Input label="Rooms" defaultValue="0" error="Must be at least 1." />
        </div>
      </Section>

      <Section title="Badge and Chip">
        <div className="flex flex-wrap gap-2">
          {['neutral', 'info', 'success', 'warning', 'error'].map((tone) => (
            <Badge key={tone} tone={tone}>
              {tone}
            </Badge>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          {['demand', 'events', 'weather'].map((id) => (
            <Chip key={id} selected={chip === id} onClick={() => setChip(id)}>
              {id}
            </Chip>
          ))}
          <Chip disabled>disabled</Chip>
        </div>
      </Section>

      <Section title="Loading, empty and error states">
        <div role="status" aria-label="Loading" className="flex items-center gap-4">
          <Skeleton className="size-12 rounded-card" />
          <div className="space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-24" />
          </div>
        </div>
        <Spinner />
        <LoadingState label="Loading prices…" />
        <EmptyState
          title="No prices yet"
          message="Upload a booking export to get recommendations."
          action={<Button variant="primary">Upload data</Button>}
        />
        <ErrorState error={new Error('The server took too long to answer.')} onRetry={() => {}} />
      </Section>
    </div>
  )
}
