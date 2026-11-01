import { Route, Routes } from 'react-router-dom'
import AppShell from './components/layout/AppShell.jsx'
import CalendarPage from './features/calendar/CalendarPage.jsx'
import ReturnAfterSignIn from './features/auth/ReturnAfterSignIn.jsx'
import SignInPage from './features/auth/SignInPage.jsx'
import ComponentsPage from './pages/ComponentsPage.jsx'
import NotFoundPage from './pages/NotFoundPage.jsx'
import PlaceholderPage from './pages/PlaceholderPage.jsx'

/** The route table: which URL shows which page. Add a page by adding a line here. */
export default function App() {
  return (
    <Routes>
      {/* Before signing in, or before the hotel exists: no sidebar or top bar. */}
      <Route path="sign-in" element={<SignInPage />} />
      <Route path="setup" element={<PlaceholderPage title="Set up your hotel" />} />

      <Route element={<AppShell />}>
        <Route index element={<ReturnAfterSignIn />} />
        <Route path="calendar" element={<CalendarPage />} />
        <Route path="calendar/:date" element={<PlaceholderPage title="Night detail" />} />
        <Route path="today" element={<PlaceholderPage title="Today" />} />
        <Route path="inbox" element={<PlaceholderPage title="Inbox" />} />
        <Route path="signals" element={<PlaceholderPage title="Signals" />} />
        <Route path="reports" element={<PlaceholderPage title="Reports" />} />
        <Route path="upload" element={<PlaceholderPage title="Upload data" />} />
        <Route path="upload/export-guide" element={<PlaceholderPage title="Export guide" />} />
        <Route path="pricing-rules" element={<PlaceholderPage title="Pricing rules" />} />
        <Route path="settings" element={<PlaceholderPage title="Settings" />} />
        {import.meta.env.DEV && <Route path="components" element={<ComponentsPage />} />}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
