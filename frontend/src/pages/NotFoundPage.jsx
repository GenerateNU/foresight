import { useNavigate } from 'react-router-dom'
import Button from '../components/ui/Button.jsx'
import EmptyState from '../components/ui/EmptyState.jsx'

export default function NotFoundPage() {
  const navigate = useNavigate()
  return (
    <div className="px-8 py-8">
      <EmptyState
        title="Page not found"
        message="That address doesn't match any page."
        action={<Button onClick={() => navigate('/')}>Go to the calendar</Button>}
      />
    </div>
  )
}
