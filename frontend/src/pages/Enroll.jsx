import { useState } from 'react'
import { Fingerprint, Mic, ScanFace, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import { useApi } from '../lib/useApi'
import { useAuth } from '../lib/auth'
import { Alert, Loading, PageHead, StatusBadge, when } from '../components/ui'
import { AudioCapture, ImageCapture } from '../components/Capture'

const META = {
  face: { title: 'Face', icon: ScanFace, hint: 'Look at the camera in good light, or upload a clear frontal photo. Up to 5 samples; 2 or 3 is better.' },
  fingerprint: { title: 'Fingerprint (experimental)', icon: Fingerprint, hint: 'Laptop fingerprint readers cannot be read by a browser. Upload fingerprint images from a dataset (e.g. SOCOFing, FVC) or exported from a scanner.' },
  voice: { title: 'Voice', icon: Mic, hint: 'Record 3 to 10 seconds of normal speech in a quiet room, or upload WAV/FLAC/OGG. Up to 5 samples.' },
}

function ModalityCard({ user, status, password, onChange }) {
  const m = status.modality
  const { title, icon: Icon, hint } = META[m]
  const [samples, setSamples] = useState([])
  const [key, setKey] = useState(0)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  const add = (blob) => { if (blob) { setSamples((s) => [...s, blob]); setKey((k) => k + 1) } }
  const submit = async () => {
    setBusy(true); setMsg(null)
    try {
      await api.enroll(user.id, m, samples, password)
      setSamples([]); setMsg({ kind: 'ok', text: 'Enrolled. The reference was built from your samples.' }); onChange()
    } catch (e) { setMsg({ kind: 'error', text: e.message }) } finally { setBusy(false) }
  }
  const remove = async () => {
    setMsg(null)
    try { await api.removeEnrollment(user.id, m, password); onChange() } catch (e) { setMsg({ kind: 'error', text: e.message }) }
  }

  return (
    <div className="mod-card stack">
      <h3><span className="row" style={{ gap: 8 }}><Icon size={18} />{title}</span><StatusBadge status={status.state} /></h3>
      {status.state === 'enrolled' && (
        <p className="small muted">{status.sample_count} sample(s), quality {status.quality?.toFixed(2)}, {when(status.enrolled_at)}. Submitting new samples replaces it.</p>
      )}
      {!status.module_available && <Alert kind="warn"><strong>Module unavailable:</strong> {status.module_detail}</Alert>}
      <p className="small muted">{hint}</p>
      {m === 'voice'
        ? <AudioCapture key={key} value={null} onChange={add} />
        : <ImageCapture key={key} value={null} onChange={add} allowCamera={m === 'face'}
            accept={m === 'fingerprint' ? 'image/png,image/jpeg,image/bmp,image/tiff' : 'image/*'} uploadLabel={m === 'fingerprint' ? 'Upload fingerprint image' : 'Upload photo'} />}
      {samples.length > 0 && <p className="small">{samples.length} sample(s) ready to enroll.</p>}
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
      <div className="row">
        <button className="btn primary" disabled={!samples.length || !password || busy} onClick={submit}>{busy ? 'Processing…' : 'Enroll'}</button>
        {samples.length > 0 && <button className="btn" onClick={() => setSamples([])}>Discard</button>}
        {status.state === 'enrolled' && <button className="btn danger" disabled={!password} onClick={remove}><Trash2 size={14} />Remove</button>}
      </div>
    </div>
  )
}

function AdminAccounts() {
  const { data: users, error, loading } = useApi(api.users)
  if (loading) return <Loading />
  if (error) return <Alert kind="error">{error.message}</Alert>
  return (
    <div className="stack">
      <PageHead title="Accounts">Read-only view for administrators. Only the account owner can enroll biometrics or make transactions.</PageHead>
      <div className="card"><table>
        <thead><tr><th>Name</th><th>Account</th><th>Role</th><th>Face</th><th>Fingerprint</th><th>Voice</th></tr></thead>
        <tbody>{users.map((u) => (
          <tr key={u.id}><td><strong>{u.full_name}</strong><div className="faint small">{u.email}</div></td>
            <td className="mono small">{u.account_number}</td><td>{u.role}</td>
            {u.enrollments.map((e) => <td key={e.modality}><StatusBadge status={e.state} /></td>)}</tr>))}</tbody>
      </table></div>
    </div>
  )
}

export default function Enroll() {
  const { user, refresh, logout } = useAuth()
  const [password, setPassword] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [err, setErr] = useState(null)
  if (user.role === 'admin') return <AdminAccounts />

  const erase = async () => {
    setErr(null)
    try { await api.deleteAccount(user.id, password); await logout() } catch (e) { setErr(e.message) }
  }

  return (
    <div className="stack">
      <PageHead title="Biometric enrollment">Enroll each modality for your account. A modality only counts as enrolled after the backend has built a reference from a valid sample.</PageHead>
      <div className="card" style={{ maxWidth: 520 }}>
        <div className="field">
          <label htmlFor="pw">Confirm your password</label>
          <input id="pw" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <span className="faint small">Required to add, replace or remove a biometric reference, so a stolen session alone cannot swap in someone else's face or voice. Kept in memory only.</span>
        </div>
      </div>
      <div className="grid g3">
        {user.enrollments.map((s) => <ModalityCard key={s.modality} user={user} status={s} password={password} onChange={refresh} />)}
      </div>
      <div className="card">
        <h2>Your data</h2>
        <p className="small muted">Raw photos, recordings and fingerprint images are processed in memory and not saved. Only encrypted templates are kept. You can erase the account, its templates, transactions and logs at any time.</p>
        {err && <Alert kind="error">{err}</Alert>}
        {!confirmDelete
          ? <button className="btn danger" onClick={() => setConfirmDelete(true)}><Trash2 size={14} />Erase my account and data</button>
          : <div className="row"><span className="small">This cannot be undone.</span>
              <button className="btn danger" disabled={!password} onClick={erase}>Yes, erase everything</button>
              <button className="btn" onClick={() => setConfirmDelete(false)}>Cancel</button></div>}
      </div>
    </div>
  )
}
