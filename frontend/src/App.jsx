import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { BarChart3, History, LayoutDashboard, Lock, LogOut, Menu, Send, UserPlus, Users, X } from 'lucide-react'
import Dashboard from './pages/Dashboard'
import Enroll from './pages/Enroll'
import Transact from './pages/Transact'
import HistoryPage from './pages/History'
import Analytics from './pages/Analytics'
import Login from './pages/Login'
import { useAuth } from './lib/auth'
import { Alert, PageSkeleton, when } from './components/ui'

const Brand = () => <div className="brand"><span className="brand-mark"><Lock size={16} /></span>TriLock</div>

export default function App() {
  const { user, loading, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  useEffect(() => setOpen(false), [loc.pathname])
  if (loading) return <div className="main"><PageSkeleton /></div>
  if (!user) return <Login />

  const admin = user.role === 'admin'
  const limited = user.session_scope === 'limited'
  const groups = limited
    ? [['Setup', [['/enroll', 'Enrollment', UserPlus]]]]
    : [
        ['Overview', [['/', 'Dashboard', LayoutDashboard]]],
        ['Payments', [...(admin ? [] : [['/transact', 'New payment', Send]]), ['/history', 'History', History]]],
        ['Security', [[ '/enroll', admin ? 'Accounts' : 'Enrollment', admin ? Users : UserPlus], ['/analytics', 'Analytics', BarChart3]]],
      ]
  const pending = (user.recovery || []).find((r) => r.status === 'pending')
  const probation = user.probation_until && new Date(user.probation_until) > new Date()

  return (
    <div className="shell">
      <div className="proto-banner"><b>Academic prototype</b> · Simulated transactions only. No real money, no real bank, not a production authentication service.</div>
      {open && <div className="scrim" onClick={() => setOpen(false)} aria-hidden />}
      <aside className={`side ${open ? 'open' : ''}`} aria-label="Main navigation">
        <Brand />
        <nav className="nav">
          {groups.map(([label, links]) => (
            <div key={label}>
              <div className="nav-label">{label}</div>
              {links.map(([to, text, Icon]) => <NavLink key={to} to={to} end={to === '/'}><Icon size={17} />{text}</NavLink>)}
            </div>
          ))}
        </nav>
        <div className="side-foot">
          <div className="me">
            <div className="avatar" aria-hidden>{user.full_name.slice(0, 1).toUpperCase()}</div>
            <div style={{ minWidth: 0 }}><div className="me-name">{user.full_name}</div><div className="me-sub">{admin ? 'Administrator, read-only' : user.account_number}</div></div>
          </div>
          <button className="btn sm block" onClick={logout}><LogOut size={14} />Sign out</button>
        </div>
      </aside>
      <div style={{ minWidth: 0 }}>
        <div className="topbar">
          <button className="btn icon-btn" aria-label={open ? 'Close menu' : 'Open menu'} onClick={() => setOpen(!open)}>{open ? <X size={18} /> : <Menu size={18} />}</button>
          <Brand />
        </div>
        <main className="main" key={loc.pathname}>
          <div className="stack-sm" style={{ marginBottom: limited || pending || probation ? 18 : 0 }}>
            {limited && <Alert kind="warn"><strong>Finish setting up your account.</strong> Signing in needs your face and your voice. Enroll both (fingerprint is optional) and the rest of the app unlocks.</Alert>}
            {!admin && pending && <Alert kind="warn"><strong>A biometric recovery was requested on your account.</strong> If this was not you, open Enrollment and cancel it now. It can be approved after {when(pending.earliest_at)}.</Alert>}
            {!admin && probation && <Alert kind="info"><strong>Probation after a biometric reset.</strong> High and critical payments are disabled until {when(user.probation_until)}.</Alert>}
          </div>
          {limited ? (
            <Routes><Route path="*" element={<Enroll />} /></Routes>
          ) : (
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/enroll" element={<Enroll />} />
              <Route path="/transact" element={admin ? <Navigate to="/" /> : <Transact />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/history/:id" element={<HistoryPage />} />
              <Route path="/analytics" element={<Analytics />} />
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          )}
        </main>
      </div>
    </div>
  )
}
