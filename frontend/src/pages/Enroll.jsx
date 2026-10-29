import { useEffect, useState } from 'react'
import { Check, KeyRound, Mic, Music2, RefreshCw, ShieldCheck, Trash2, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useApi } from '../lib/useApi'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import { Alert, Card, ErrorState, MODALITY, Meter, PageHead, PageSkeleton, Spinner, StatusBadge, pct, when } from '../components/ui'
import { AudioCapture, ImageCapture } from '../components/Capture'
import RecoveryPanel from '../components/Recovery'

const GUIDE = {
  face: {
    steps: ['Use a well-lit room and face the camera directly.', 'Keep one face in the picture, without sunglasses or a hat.', 'Add two or three photos for a better reference.'],
    max: 5, kind: 'image',
  },
  voice: {
    steps: ['Find a quiet room and hold the device at a normal distance.', 'Record 3 to 10 seconds of normal speech, for example reading a sentence.', 'Add a second recording for a more reliable reference.'],
    max: 5, kind: 'audio',
  },
  fingerprint: {
    steps: ['A browser cannot read a laptop fingerprint reader.', 'Upload a fingerprint image from a dataset (SOCOFing, FVC) or exported from a scanner.', 'This is a future enhancement. Nothing requires it.'],
    max: 4, kind: 'image',
  },
}

function friendly(e) {
  if (e.code === 'password_required') return 'Type your account password in the box at the top of the page.'
  if (e.code === 'biometric_proof_required') return `${e.message} Use the "Security check" panel above.`
  if (e.code === 'too_many_failures') return e.message
  return e.message
}

function Thumb({ item, onRemove }) {
  return (
    <div className="sample" title={item.name}>
      {item.url && item.kind === 'image' ? <img src={item.url} alt="" /> : <Music2 size={18} />}
      <button aria-label="Remove sample" onClick={onRemove}><X size={11} /></button>
    </div>
  )
}

function ModalityCard({ user, status, password, proofs, onDone }) {
  const m = status.modality
  const g = GUIDE[m]
  const M = MODALITY[m]
  const toast = useToast()
  const { refresh } = useAuth()
  const [queue, setQueue] = useState([])
  const [key, setKey] = useState(0)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [editing, setEditing] = useState(false)
  useEffect(() => () => queue.forEach((q) => q.url && URL.revokeObjectURL(q.url)), []) // eslint-disable-line react-hooks/exhaustive-deps

  const enrolled = status.state === 'enrolled'
  const showCapture = status.module_available && (!enrolled || editing)
  const add = (blob) => {
    if (!blob) return
    if (queue.length >= g.max) { setMsg({ kind: 'warn', text: `At most ${g.max} samples per enrollment.` }); return }
    setMsg(null)
    setQueue((q) => [...q, { blob, kind: g.kind, name: blob.name || `sample ${q.length + 1}`, url: g.kind === 'image' ? URL.createObjectURL(blob) : null }])
    setKey((k) => k + 1)
  }
  const removeAt = (i) => setQueue((q) => { q[i].url && URL.revokeObjectURL(q[i].url); return q.filter((_, j) => j !== i) })
  const clear = () => { queue.forEach((q) => q.url && URL.revokeObjectURL(q.url)); setQueue([]) }

  const submit = async () => {
    setBusy(true); setMsg(null)
    try {
      const wasLimited = user.session_scope === 'limited'
      const after = await api.enroll(user.id, m, queue.map((q) => q.blob), password, proofs)
      clear(); setEditing(false); onDone()
      const complete = after.filter((s) => s.required).every((s) => s.state === 'enrolled')
      await refresh()
      toast(wasLimited && complete ? 'Face and voice are enrolled. Your account is unlocked.' : `${M.label} ${enrolled ? 'updated' : 'enrolled'}.`)
    } catch (e) { setMsg({ kind: 'error', text: friendly(e) }) } finally { setBusy(false) }
  }
  const remove = async () => {
    if (!window.confirm(`Remove your ${M.label.toLowerCase()} reference?`)) return
    setMsg(null)
    try { await api.removeEnrollment(user.id, m, password, proofs); onDone(); await refresh(); toast(`${M.label} reference removed.`, 'info') }
    catch (e) { setMsg({ kind: 'error', text: friendly(e) }) }
  }

  return (
    <div className={`mod ${enrolled ? 'is-enrolled' : ''} ${status.module_available ? '' : 'is-unavailable'}`} data-testid={`enroll-${m}`}>
      <div className="mod-head">
        <div className="mod-title">
          <span className="mod-icon">{enrolled ? <Check size={17} /> : <M.icon size={17} />}</span>
          <div><h3>{M.label}</h3><div className="xs faint">{status.required ? 'Required for sign-in and payments' : 'Optional · future enhancement'}</div></div>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <span className={`badge ${status.required ? 'b-high' : 'b-neutral'}`}>{status.required ? 'Required' : 'Optional'}</span>
          <StatusBadge status={status.state} />
        </div>
      </div>

      {!status.module_available && <Alert kind="warn"><strong>Not available on this server.</strong> {status.module_detail}</Alert>}

      {enrolled && (
        <div className="stack-sm">
          <dl className="kv small">
            <dt>Enrolled</dt><dd>{when(status.enrolled_at)}</dd>
            <dt>Samples</dt><dd>{status.sample_count}</dd>
            <dt>Sample quality</dt><dd><div className="row" style={{ gap: 8, flexWrap: 'nowrap' }}><div style={{ flex: 1, minWidth: 50 }}><Meter value={status.quality} tone="ok" /></div><span className="num">{pct(status.quality, 0)}</span></div></dd>
          </dl>
          {!editing && (
            <div className="row">
              <button className="btn sm" disabled={!status.module_available} onClick={() => setEditing(true)}><RefreshCw size={13} />Replace</button>
              <button className="btn sm danger" disabled={!password} title={password ? '' : 'Type your password at the top first'} onClick={remove}><Trash2 size={13} />Remove</button>
            </div>
          )}
        </div>
      )}

      {showCapture && (
        <>
          {!enrolled && <ol className="howto">{g.steps.map((t) => <li key={t}>{t}</li>)}</ol>}
          {enrolled && <p className="small muted" style={{ margin: 0 }}>New samples replace the current reference.</p>}
          {m === 'voice'
            ? <AudioCapture key={key} value={null} onChange={add} />
            : <ImageCapture key={key} value={null} onChange={add} allowCamera={m === 'face'} guide={m === 'face'}
                accept={m === 'fingerprint' ? 'image/png,image/jpeg,image/bmp,image/tiff' : 'image/*'} uploadLabel={m === 'fingerprint' ? 'Upload fingerprint image' : 'Upload photo'} />}
          {queue.length > 0 && (
            <div className="stack-sm">
              <div className="row between small"><span className="muted">{queue.length} sample(s) ready to enroll <span className="faint">(max {g.max})</span></span><button className="btn ghost sm" onClick={clear}>Discard all</button></div>
              <div className="samples">{queue.map((q, i) => <Thumb key={i} item={q} onRemove={() => removeAt(i)} />)}</div>
            </div>
          )}
          {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
          <div className="row">
            <button className="btn primary" disabled={!queue.length || !password || busy} onClick={submit}>{busy ? <><Spinner />Processing…</> : enrolled ? 'Replace reference' : 'Enroll'}</button>
            {editing && <button className="btn ghost" onClick={() => { setEditing(false); clear() }}>Cancel</button>}
            {queue.length > 0 && !password && <span className="hint">Type your password at the top first.</span>}
          </div>
        </>
      )}
      {!showCapture && msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
    </div>
  )
}

function RecoveryQueue() {
  const { data, error, loading, reload } = useApi(() => api.recoveryQueue('pending'))
  const toast = useToast()
  const [busy, setBusy] = useState(null)
  if (loading && !data) return <Card title="Recovery requests"><div className="skeleton" style={{ height: 60 }} /></Card>
  if (error) return <ErrorState error={error} onRetry={reload} />
  const act = async (fn, r, label) => {
    setBusy(r.id)
    try { await fn(r.id); toast(`${label} for ${r.user_name}. Recorded in the audit log.`); reload() }
    catch (e) { toast(e.message, 'error') } finally { setBusy(null) }
  }
  return (
    <Card title="Recovery requests" subtitle="Approve only after confirming with the user through another channel. Approval deletes their biometric references and starts a probation period. It cannot happen before the waiting period ends.">
      {data.length === 0 ? <p className="muted small" style={{ margin: 0 }}>No pending requests.</p> : (
        <div className="table-wrap"><table>
          <thead><tr><th>User</th><th>Reason</th><th>Filed</th><th>Approvable from</th><th /></tr></thead>
          <tbody>{data.map((r) => (
            <tr key={r.id}><td><strong>{r.user_name}</strong><div className="faint xs">{r.user_email}</div></td><td className="small">{r.reason}</td>
              <td className="small muted nowrap">{when(r.created_at)}</td><td className="small nowrap">{when(r.earliest_at)}</td>
              <td><div className="row" style={{ flexWrap: 'nowrap' }}>
                <button className="btn sm danger" disabled={!r.can_approve || busy === r.id} title={r.can_approve ? '' : 'Still in the waiting period'}
                  onClick={() => window.confirm(`Delete all biometric references of ${r.user_name}?`) && act((id) => api.approveRecovery(id), r, 'Recovery approved')}>Approve</button>
                <button className="btn sm" disabled={busy === r.id} onClick={() => act((id) => api.denyRecovery(id), r, 'Recovery denied')}>Deny</button></div></td></tr>))}</tbody>
        </table></div>
      )}
    </Card>
  )
}

function AdminAccounts() {
  const { data: users, error, loading, reload } = useApi(api.users)
  if (loading && !users) return <PageSkeleton cards={0} />
  if (error) return <ErrorState error={error} onRetry={reload} />
  return (
    <div className="stack">
      <PageHead title="Accounts">Read-only view for administrators. Only the account owner can enroll biometrics or make payments.</PageHead>
      <RecoveryQueue />
      <Card flush>
        <div className="table-wrap"><table>
          <thead><tr><th>Name</th><th>Account</th><th>Role</th><th>Face</th><th>Voice</th><th>Fingerprint</th><th>Notes</th></tr></thead>
          <tbody>{users.map((u) => {
            const st = Object.fromEntries(u.enrollments.map((e) => [e.modality, e.state]))
            return (
              <tr key={u.id}><td><strong>{u.full_name}</strong><div className="faint xs">{u.email}</div></td>
                <td className="mono small">{u.account_number}</td><td className="cap">{u.role}</td>
                <td><StatusBadge status={st.face} /></td><td><StatusBadge status={st.voice} /></td><td><StatusBadge status={st.fingerprint} /></td>
                <td className="small">{u.probation_until && new Date(u.probation_until) > new Date() && <span className="badge b-warn">probation until {when(u.probation_until)}</span>}</td></tr>)
          })}</tbody>
        </table></div>
      </Card>
    </div>
  )
}

export default function Enroll() {
  const { user, refresh, logout } = useAuth()
  const toast = useToast()
  const [password, setPassword] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [err, setErr] = useState(null)
  const [proofs, setProofs] = useState({})
  const [proofRound, setProofRound] = useState(0)
  if (!user) return <PageSkeleton />
  if (user.role === 'admin') return <AdminAccounts />

  const enrolled = user.enrollments.filter((e) => e.state === 'enrolled')
  const required = user.enrollments.filter((e) => e.required)
  const doneRequired = required.filter((e) => e.state === 'enrolled').length
  const complete = doneRequired === required.length
  const needed = Math.min(2, enrolled.length)
  const given = enrolled.filter((e) => proofs[e.modality]).length
  const setProof = (m) => (b) => setProofs((p) => ({ ...p, [m]: b || undefined }))
  const clearProofs = () => { setProofs({}); setProofRound((r) => r + 1) }

  const erase = async () => {
    setErr(null)
    try { await api.deleteAccount(user.id, password, proofs); toast('Account and data erased.', 'info'); await logout() } catch (e) { setErr(e.message) }
  }

  return (
    <div className="stack">
      <PageHead title="Biometric enrollment">Face and voice are required: you use them to sign in and to approve payments. Fingerprint is optional and only adds evidence.</PageHead>

      <Card>
        <div className="row between" style={{ marginBottom: 12 }}>
          <div><h2>Account setup</h2><p className="small muted" style={{ margin: '4px 0 0' }}>{complete ? 'Everything required is enrolled.' : `${doneRequired} of ${required.length} required biometrics enrolled.`}</p></div>
          {complete ? <Link to="/transact" className="btn primary">Make a payment</Link> : <span className="badge b-high">Setup incomplete</span>}
        </div>
        <Meter value={doneRequired / Math.max(required.length, 1)} tone={complete ? 'ok' : 'warn'} thick />
        <div className="row" style={{ marginTop: 14, gap: 8 }}>
          {user.enrollments.map((e) => (
            <span key={e.modality} className={`chip ${e.state === 'enrolled' ? 'ok' : e.required ? 'warn' : 'off'}`}>
              {e.state === 'enrolled' ? <Check size={12} /> : <span style={{ width: 12 }} />}{MODALITY[e.modality].label}{e.required ? '' : ' (optional)'}
            </span>
          ))}
        </div>
      </Card>

      <Card title="Confirm it is you" icon={KeyRound} subtitle="Needed whenever you add, replace or remove a biometric, so a stolen session cannot swap in someone else's face or voice. Kept in memory only.">
        <div style={{ maxWidth: 420 }}>
          <label htmlFor="pw">Account password</label>
          <input id="pw" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Your password" />
        </div>
      </Card>

      {enrolled.length > 0 && (
        <Card title="Security check for changes" icon={ShieldCheck}
          subtitle={`Because you already have biometrics, changing them needs fresh matching samples from ${needed} of your enrolled modalities (${enrolled.map((e) => e.modality).join(', ')}). This stops someone who only knows your password. ${given} of ${needed} provided.`}>
          <div className="grid g3">
            {enrolled.map((e) => (
              <div className="subcard stack-sm" key={e.modality + proofRound} data-testid={`proof-${e.modality}`}>
                <div className="subcard-head"><h3>{MODALITY[e.modality].label}</h3>{proofs[e.modality] && <span className="badge b-ok">Sample ready</span>}</div>
                {e.modality === 'voice' ? <AudioCapture value={proofs.voice} onChange={setProof('voice')} />
                  : <ImageCapture value={proofs[e.modality]} onChange={setProof(e.modality)} allowCamera={e.modality === 'face'}
                      uploadLabel={e.modality === 'face' ? 'Upload photo' : 'Upload fingerprint image'} />}
              </div>
            ))}
          </div>
          <p className="xs faint" style={{ margin: '12px 0 0' }}>Wrong samples count as failed biometric attempts and can pause further tries for 15 minutes.</p>
        </Card>
      )}

      <div className="grid g3">
        {user.enrollments.map((s) => <ModalityCard key={s.modality} user={user} status={s} password={password} proofs={proofs} onDone={clearProofs} />)}
      </div>

      <RecoveryPanel user={user} password={password} refresh={refresh} />

      <Card title="Your data" icon={Trash2} subtitle="Raw photos, recordings and fingerprint images are processed in memory and not saved. Only encrypted templates are kept.">
        {err && <div style={{ marginBottom: 12 }}><Alert kind="error">{err}</Alert></div>}
        {!confirmDelete
          ? <button className="btn danger" onClick={() => setConfirmDelete(true)}><Trash2 size={14} />Erase my account and data</button>
          : <div className="row"><span className="small">This removes your templates, transactions and logs. It cannot be undone.</span>
              <button className="btn danger" disabled={!password || given < needed} onClick={erase}>Yes, erase everything</button>
              <button className="btn" onClick={() => setConfirmDelete(false)}>Cancel</button>
              {(!password || given < needed) && <span className="hint">Needs your password{needed ? ' and the security check above' : ''}.</span>}</div>}
      </Card>
    </div>
  )
}
