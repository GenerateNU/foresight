import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar.jsx'
import TopBar from './TopBar.jsx'

/**
 * The frame every signed-in page sits in: sidebar on the left, top bar on top, page in the
 * middle. `<Outlet />` is where react-router drops the current page.
 */
export default function AppShell() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
