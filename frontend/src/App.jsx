import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { BarChart3, History, LayoutDashboard, Lock, LogOut, Send, UserPlus, Users } from 'lucide-react'
import Dashboard from './pages/Dashboard'
import Enroll from './pages/Enroll'
import Transact from './pages/Transact'
import HistoryPage from './pages/History'
import Analytics from './pages/Analytics'
import Login from './pages/Login'
import { useAuth } from './lib/auth'
import { Loading } from './components/ui'

export default function App() {
  const { user, loading, logout } = useAuth()
  if (loading) return <div className="main"><Loading /></div>
  if (!user) return <Login />
  const admin = user.role === 'admin'
  const links = [
    ['/', 'Dashboard', LayoutDashboard],
    admin ? ['/enroll', 'Accounts', Users] : ['/enroll', 'Enrollment', UserPlus],
    ...(admin ? [] : [['/transact', 'New transaction', Send]]),
    ['/history', 'History', History],
    ['/analytics', 'Analytics', BarChart3],
  ]
  return (
    <div className="shell">
      <div className="proto-banner">Academic prototype. Simulated transactions only: no real money, no real bank, not a production authentication service.</div>
      <aside className="side">
        <div className="brand"><Lock size={20} />TriLock</div>
        <nav className="nav">
          {links.map(([to, label, Icon]) => (
            <NavLink key={to} to={to} end={to === '/'}><Icon size={17} />{label}</NavLink>
          ))}
        </nav>
        <div className="foot">
          <div style={{ marginBottom: 8 }}><strong>{user.full_name}</strong><br />{admin ? 'Administrator (read-only)' : user.account_number}</div>
          <button className="btn sm" onClick={logout}><LogOut size={13} />Sign out</button>
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/enroll" element={<Enroll />} />
          <Route path="/transact" element={admin ? <Navigate to="/" /> : <Transact />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/history/:id" element={<HistoryPage />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </div>
  )
}
