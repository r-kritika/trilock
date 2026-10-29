import { useState } from 'react'
import { Lock, LifeBuoy, ShieldCheck } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../lib/auth'
import { Alert, Spinner, Stepper } from '../components/ui'
import { AudioCapture, ImageCapture } from '../components/Capture'
import { LiveFace, PhraseBanner } from '../components/LiveCapture'

const Brand = () => <div className="auth-brand"><span className="brand-mark"><Lock size={16} /></span>TriLock</div>

function BiometricStep() {
  const { pending, completeBiometric, newChallenge, cancelPending } = useAuth()
  const [frames, setFrames] = useState([])
  const [photo, setPhoto] = useState(null)       // used only when the server has liveness switched off
  const [voice, setVoice] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [round, setRound] = useState(0)
  const [recovery, setRecovery] = useState(false)
  const [rec, setRec] = useState({ reason: '', password: '' })
  const [recMsg, setRecMsg] = useState(null)
  const live = pending.livenessRequired
  const faceReady = live ? frames.length >= 6 : !!photo

  const submit = async () => {
    setErr(null); setBusy(true)
    try {
      await completeBiometric(live ? frames : [photo], voice)
    } catch (e) {
      setErr(e)
      // every attempt uses its challenge up, so get a fresh one and clear the inputs
      setFrames([]); setPhoto(null); setVoice(null); setRound((r) => r + 1)
      if (e.code !== 'start_over' && e.status !== 429) { try { await newChallenge() } catch { /* ignore */ } }
    } finally { setBusy(false) }
  }
  const requestRecovery = async () => {
    setRecMsg(null)
    try { await api.requestRecoveryWith(pending.token, rec.reason, rec.password); setRecMsg({ kind: 'ok', text: 'Recovery requested. An administrator can approve it after the waiting period.' }) }
    catch (e) { setRecMsg({ kind: 'error', text: e.message }) }
  }
  const details = err?.details?.modalities

  return (
    <div className="auth">
      <div className="card stack auth-card wide">
        <Brand />
        <Stepper steps={['Password', 'Face and voice']} current={1} />
        <div>
          <h2 style={{ fontSize: '1.2rem' }}>Verify it is you, {pending.name}</h2>
          <p className="muted small" style={{ margin: '6px 0 0', maxWidth: '64ch' }}>Password accepted. Signing in also needs your <strong>face</strong> and your <strong>voice</strong>{live ? ', live: a head turn and three spoken words, so a photo or a recording does not work.' : '.'}</p>
        </div>
        {live && <PhraseBanner challenge={pending.challenge} />}
        <div className="grid g2">
          <div className="mod">
            <div className="mod-head"><h3>1. Face</h3></div>
            {live
              ? <LiveFace key={`f${round}`} challenge={pending.challenge} frames={frames} onChange={setFrames} />
              : <ImageCapture key={`p${round}`} value={photo} onChange={setPhoto} allowCamera uploadLabel="Upload photo" guide />}
          </div>
          <div className="mod">
            <div className="mod-head"><h3>2. Voice</h3></div>
            <p className="small muted" style={{ margin: 0 }}>{live ? 'Record yourself saying the three words above.' : 'Record a few seconds of normal speech.'}</p>
            <AudioCapture key={`v${round}`} value={voice} onChange={setVoice} />
          </div>
        </div>
        {err && (
          <Alert kind="error">
            <div><strong>{err.message}</strong></div>
            {details && <ul className="small" style={{ margin: '6px 0 0', paddingLeft: 18 }}>
              {details.map((m) => <li key={m.modality} className="cap">{m.modality}: {m.status === 'match' ? 'confirmed' : (m.reason || m.status)}</li>)}
            </ul>}
            {err.details?.attempts_left != null && <div className="small" style={{ marginTop: 6 }}>{err.details.attempts_left} tries left for this password entry.</div>}
          </Alert>
        )}
        <div className="row">
          <button className="btn primary lg" disabled={busy || !faceReady || !voice} onClick={submit}>{busy ? <><Spinner />Checking…</> : <><ShieldCheck size={16} />Verify and sign in</>}</button>
          <button className="btn" onClick={cancelPending}>Back</button>
          <button className="btn ghost sm" onClick={() => setRecovery(!recovery)}><LifeBuoy size={14} />Cannot verify? Recovery</button>
        </div>
        {recovery && (
          <div className="subcard stack-sm">
            <p className="small muted" style={{ margin: 0 }}>If your face or voice changed or a device broke, you can ask for a recovery. It deletes your enrolled biometrics after a waiting period and an administrator's approval, and high-value payments stay disabled for a few days afterwards.</p>
            <div className="grid g2">
              <div className="field"><label htmlFor="rr">Reason</label><input id="rr" type="text" maxLength={300} value={rec.reason} onChange={(e) => setRec({ ...rec, reason: e.target.value })} /></div>
              <div className="field"><label htmlFor="rp">Password again</label><input id="rp" type="password" value={rec.password} onChange={(e) => setRec({ ...rec, password: e.target.value })} /></div>
            </div>
            {recMsg && <Alert kind={recMsg.kind}>{recMsg.text}</Alert>}
            <div><button className="btn" disabled={rec.reason.trim().length < 3 || !rec.password} onClick={requestRecovery}>Request recovery</button></div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function Login() {
  const { login, register, pending } = useAuth()
  const [mode, setMode] = useState('login')
  const [f, setF] = useState({ full_name: '', email: '', password: '' })
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  if (pending) return <BiometricStep />

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
    <div className="auth">
      <form className="card stack auth-card" onSubmit={submit}>
        <Brand />
        <div>
          <h2 style={{ fontSize: '1.2rem' }}>{mode === 'login' ? 'Sign in' : 'Create your account'}</h2>
          <p className="muted small" style={{ margin: '6px 0 0' }}>Password first, then your live face and voice once you have enrolled them.</p>
        </div>
        {mode === 'register' && (
          <div className="field"><label htmlFor="fn">Full name</label><input id="fn" type="text" required minLength={2} value={f.full_name} onChange={set('full_name')} /></div>
        )}
        <div className="field"><label htmlFor="em">Email</label><input id="em" type="email" required autoComplete="username" value={f.email} onChange={set('email')} /></div>
        <div className="field"><label htmlFor="pw">Password</label>
          <input id="pw" type="password" required minLength={mode === 'register' ? 10 : 1} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={f.password} onChange={set('password')} />
          {mode === 'register' && <div className="hint">At least 10 characters.</div>}
        </div>
        {err && <Alert kind="error">{err}</Alert>}
        <button className="btn primary lg block" disabled={busy}>{busy && <Spinner />}{mode === 'login' ? 'Continue' : 'Create account'}</button>
        <button type="button" className="btn ghost sm block" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setErr(null) }}>
          {mode === 'login' ? 'Need an account? Register' : 'Have an account? Sign in'}
        </button>
        <p className="xs faint center" style={{ margin: 0 }}>Academic prototype. Simulated transactions only.</p>
      </form>
    </div>
  )
}
