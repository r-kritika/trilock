import { useState } from 'react'
import { LifeBuoy } from 'lucide-react'
import { api } from '../api/client'
import { useToast } from '../lib/toast'
import { Alert, Card, Spinner, when } from './ui'

// Shown on the Enrollment page: request recovery when you can no longer provide your biometrics.
export default function RecoveryPanel({ user, password, refresh }) {
  const [reason, setReason] = useState('')
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const pending = (user.recovery || []).find((r) => r.status === 'pending')
  const hasBio = user.enrollments.some((e) => e.state === 'enrolled')
  if (!hasBio && !pending) return null

  const run = async (fn, done) => {
    setMsg(null); setBusy(true)
    try { await fn(); toast(done); await refresh() } catch (e) { setMsg(e.message) } finally { setBusy(false) }
  }
  return (
    <Card title="Cannot provide your biometrics?" icon={LifeBuoy} subtitle="For a changed face, a broken microphone or a new device.">
      {msg && <div style={{ marginBottom: 12 }}><Alert kind="error">{msg}</Alert></div>}
      {pending ? (
        <div className="stack-sm">
          <Alert kind="warn">A recovery request is waiting. An administrator can approve it after <strong>{when(pending.earliest_at)}</strong>. If this was not you, cancel it now (type your password above).</Alert>
          <div><button className="btn danger" disabled={!password || busy} onClick={() => run(() => api.cancelRecovery(pending.id, password), 'Recovery request cancelled.')}>{busy && <Spinner />}Cancel recovery request</button></div>
        </div>
      ) : (
        <div className="stack-sm">
          <p className="small muted" style={{ margin: 0 }}>A recovery deletes your enrolled biometrics so you can enroll again. It cannot happen instantly: there is a waiting period, an administrator must approve it, and afterwards high-value payments stay disabled for a few days.</p>
          <div className="field"><label htmlFor="rr">Reason</label><input id="rr" type="text" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example: my camera broke and I have a new face enrolled elsewhere" /></div>
          <div><button className="btn" disabled={!password || reason.trim().length < 3 || busy} onClick={() => run(async () => { await api.requestRecovery(reason, password); setReason('') }, 'Recovery requested.')}>{busy && <Spinner />}Request recovery</button>
            {!password && <span className="hint" style={{ marginLeft: 10 }}>Type your password at the top of the page first.</span>}</div>
        </div>
      )}
    </Card>
  )
}
