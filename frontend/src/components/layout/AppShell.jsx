import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar.jsx'
import TopBar from './TopBar.jsx'

/**
 * The frame every signed-in page sits in: sidebar on the left, top bar on top, page in the
 * middle. `<Outlet />` is where react-router drops the current page. The frame is one
 * screen tall; a page taller than that scrolls inside `main`, and a page can fill it exactly
 * with `h-full`.
 */
export default function AppShell() {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
