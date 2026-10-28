import { useState } from 'react'
import { Lock } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { Alert } from '../components/ui'

export default function Login() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState('login')
  const [f, setF] = useState({ full_name: '', email: '', password: '' })
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault(); setErr(null); setBusy(true)
    try {
      if (mode === 'login') await login(f.email, f.password)
      else await register(f.full_name, f.email, f.password)
    } catch (x) {
      setErr(x.fields?.map((q) => `${q.field}: ${q.message}`).join('; ') || x.message)
    } finally { setBusy(false) }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 16 }}>
      <form className="card stack" style={{ width: 'min(400px, 100%)' }} onSubmit={submit}>
        <div className="brand" style={{ padding: 0 }}><Lock size={22} />TriLock</div>
        <p className="muted small" style={{ margin: 0 }}>Academic prototype with simulated transactions. Sign in or create a test account.</p>
        {mode === 'register' && (
          <div className="field"><label htmlFor="fn">Full name</label><input id="fn" type="text" required minLength={2} value={f.full_name} onChange={set('full_name')} /></div>
        )}
        <div className="field"><label htmlFor="em">Email</label><input id="em" type="email" required autoComplete="username" value={f.email} onChange={set('email')} /></div>
        <div className="field"><label htmlFor="pw">Password</label>
          <input id="pw" type="password" required minLength={mode === 'register' ? 10 : 1} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={f.password} onChange={set('password')} />
          {mode === 'register' && <span className="faint small">At least 10 characters.</span>}
        </div>
        {err && <Alert kind="error">{err}</Alert>}
        <button className="btn primary" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}</button>
        <button type="button" className="btn sm" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setErr(null) }}>
          {mode === 'login' ? 'Need an account? Register' : 'Have an account? Sign in'}
        </button>
      </form>
    </div>
  )
}
