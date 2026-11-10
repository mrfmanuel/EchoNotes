import { Link, Outlet } from 'react-router'
import { AppFooter } from './AppFooter'

export function Layout() {
  return (
    <div className="app">
      <header className="app-header">
        <Link to="/" className="brand">
          <span className="brand-mark" aria-hidden="true">
            ◉
          </span>
          EchoNotes
        </Link>
        <span className="brand-tagline">Turn audio into organized text notes.</span>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
      <AppFooter />
    </div>
  )
}
