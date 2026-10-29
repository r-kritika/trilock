import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Check, Fingerprint, History as HistoryIcon, Mic, ScanFace, Send, ShieldCheck } from 'lucide-react'
import { api } from '../api/client'
import { useApi } from '../lib/useApi'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import { Alert, Card, FactorList, MODALITY, PageHead, RiskGauge, Spinner, Stepper, StatusBadge, money } from '../components/ui'
import { AudioCapture, ImageCapture } from '../components/Capture'
import { LiveFace, PhraseBanner } from '../components/LiveCapture'
import ResultView from '../components/ResultView'

const RISK_ORDER = { low: 0, medium: 1, high: 2, critical: 3 }
const EMPTY = { amount: '', recipient_name: '', recipient_account: '', transaction_type: 'domestic_transfer', recipient_is_new: false, is_international: false, new_device: false, note: '' }
const STEPS = ['Details', 'Risk', 'Verify', 'Decision']
const STAGE_INDEX = { details: 0, risk: 1, verify: 2, result: 3 }

function Biometrics({ user }) {
  return (
    <div className="stack-sm">
      {user.enrollments.map((e) => {
        const M = MODALITY[e.modality]
        return (
          <div className="row between" key={e.modality}>
            <span className="row" style={{ gap: 8 }}><M.icon size={15} style={{ color: 'var(--text-3)' }} /><span>{M.label}</span>{!e.required && <span className="xs faint">optional</span>}</span>
            <StatusBadge status={e.state} />
          </div>
        )
      })}
    </div>
  )
}

function Requirements({ txn, policy, user }) {
  if (!policy) return null
  const band = policy.fusion.bands[txn.risk_category]
  const live = policy.liveness_required_from !== 'never' && RISK_ORDER[txn.risk_category] >= RISK_ORDER[policy.liveness_required_from]
  const items = [
    `Approved when the combined evidence score reaches ${band.approve} (rejected below ${band.reject}).`,
    band.require_core ? 'Both your face and your voice are required. Fingerprint cannot replace either.' : `At least ${band.min_modalities} biometric${band.min_modalities > 1 ? 's' : ''} must be evaluated.`,
    live ? 'The face must be a live head turn and the voice must say three random words. Photos and free recordings are not accepted.' : 'A live head turn and spoken words are optional at this level.',
    'A sample you leave blank counts as no evidence, never as a match.',
  ]
  const missing = user.enrollments.filter((e) => e.required && e.state !== 'enrolled')
  return (
    <div className="stack-sm">
      <ul className="next-steps" style={{ margin: 0 }}>{items.map((t) => <li key={t} className="small">{t}</li>)}</ul>
      {missing.length > 0 && <Alert kind="warn">You have not enrolled: {missing.map((e) => e.modality).join(', ')}. Enroll them first or this payment cannot be approved.</Alert>}
    </div>
  )
}

export default function Transact() {
  const { user } = useAuth()
  const toast = useToast()
  const nav = useNavigate()
  const { data: policy } = useApi(() => api.policy().catch(() => null))
  const [f, setF] = useState(EMPTY)
  const [preview, setPreview] = useState(null)
  const [stage, setStage] = useState('details')
  const [txn, setTxn] = useState(null)
  const [samples, setSamples] = useState({})
  const [round, setRound] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [challenge, setChallenge] = useState(null)
  const [frames, setFrames] = useState([])
  const [liveOptional, setLiveOptional] = useState(false)

  const enrolled = Object.fromEntries(user.enrollments.map((e) => [e.modality, e]))
  const closed = txn && (txn.decision === 'approved' || txn.decision === 'rejected')
  const needLive = !!txn && !!policy && policy.liveness_required_from !== 'never' && RISK_ORDER[txn.risk_category] >= RISK_ORDER[policy.liveness_required_from]
  const useLive = needLive || liveOptional

  // live risk estimate while the form is being filled in (uses this user's own history on the server)
  useEffect(() => {
    const amount = parseFloat(f.amount)
    if (!(amount > 0) || stage !== 'details') { setPreview(null); return }
    const t = setTimeout(() => {
      api.riskPreview({ local_hour: new Date().getHours(), amount, transaction_type: f.transaction_type, recipient_is_new: f.recipient_is_new, is_international: f.is_international, new_device: f.new_device })
        .then(setPreview).catch(() => setPreview(null))
    }, 250)
    return () => clearTimeout(t)
  }, [f.amount, f.transaction_type, f.recipient_is_new, f.is_international, f.new_device, stage])

  // each attempt uses its challenge up, so fetch a fresh one whenever verification starts or an attempt finishes
  useEffect(() => {
    if (stage !== 'verify' || !txn) return
    let cancelled = false
    api.livenessChallenge().then((c) => { if (!cancelled) setChallenge(c) }).catch(() => { if (!cancelled) setChallenge(null) })
    return () => { cancelled = true }
  }, [stage, txn?.id, txn?.attempts?.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const fieldErr = (x) => x.fields?.map((q) => `${q.field}: ${q.message}`).join('; ') || x.message

  const create = async (e) => {
    e.preventDefault(); setErr(null); setBusy(true)
    try {
      setTxn(await api.createTransaction({ ...f, amount: parseFloat(f.amount), note: f.note || null, local_hour: new Date().getHours() }))
      setStage('risk')
    } catch (x) { setErr(fieldErr(x)) } finally { setBusy(false) }
  }
  const submit = async () => {
    setErr(null); setBusy(true)
    try {
      const live = useLive && challenge ? { challengeId: challenge.challenge_id, faceFrames: frames } : null
      const out = await api.authenticate(txn.id, samples, live)
      setTxn(out); setSamples({}); setFrames([]); setRound((r) => r + 1); setStage('result')
      if (out.decision === 'approved') toast('Payment approved.')
    } catch (x) {
      setErr(x.message)
      if (x.code === 'too_many_failures') toast(x.message, 'error')
    } finally { setBusy(false) }
  }
  const reset = () => { setStage('details'); setTxn(null); setF(EMPTY); setSamples({}); setFrames([]); setErr(null); setRound((r) => r + 1) }
  const setS = (k) => (b) => setSamples((s) => ({ ...s, [k]: b || undefined }))
  const evidenceCount = Object.values(samples).filter(Boolean).length + (frames.length ? 1 : 0)

  return (
    <div className="stack">
      <PageHead title="New payment">Simulated: no money moves. The payment is scored for risk, then verified with your biometrics.</PageHead>
      <Stepper steps={STEPS} current={closed && stage === 'result' ? 4 : STAGE_INDEX[stage]} />
      {err && <Alert kind="error">{err}</Alert>}

      {stage === 'details' && (
        <form className="grid split" onSubmit={create}>
          <Card title="Payment details">
            <div className="grid g2">
              <div className="field"><label htmlFor="a">Amount (USD)</label><input id="a" type="number" min="0.01" step="0.01" required value={f.amount} onChange={set('amount')} placeholder="0.00" /></div>
              <div className="field" style={{ marginTop: 0 }}><label htmlFor="t">Type</label>
                <select id="t" value={f.transaction_type} onChange={set('transaction_type')}>
                  <option value="domestic_transfer">Domestic transfer</option><option value="bill_payment">Bill payment</option>
                  <option value="cash_withdrawal">Cash withdrawal</option><option value="wire_transfer">Wire transfer</option>
                </select></div>
            </div>
            <div className="grid g2" style={{ marginTop: 14 }}>
              <div className="field" style={{ marginTop: 0 }}><label htmlFor="r">Recipient name</label><input id="r" type="text" required value={f.recipient_name} onChange={set('recipient_name')} /></div>
              <div className="field" style={{ marginTop: 0 }}><label htmlFor="ra">Recipient account</label><input id="ra" type="text" required minLength={3} value={f.recipient_account} onChange={set('recipient_account')} /></div>
            </div>
            <div className="stack-sm" style={{ marginTop: 16 }}>
              <label className="check"><input type="checkbox" checked={f.recipient_is_new} onChange={set('recipient_is_new')} />Recipient is new (never paid before)</label>
              <label className="check"><input type="checkbox" checked={f.is_international} onChange={set('is_international')} />International recipient</label>
              <label className="check"><input type="checkbox" checked={f.new_device} onChange={set('new_device')} />Request comes from a new, unrecognised device</label>
            </div>
            <div className="field"><label htmlFor="no">Note (optional)</label><input id="no" type="text" maxLength={200} value={f.note} onChange={set('note')} /></div>
            <div className="row" style={{ marginTop: 18 }}>
              <button className="btn primary lg" disabled={busy}>{busy ? <><Spinner />Calculating…</> : <>Calculate risk and continue<ArrowRight size={16} /></>}</button>
            </div>
          </Card>
          <div className="stack">
            <Card title="Live risk estimate" subtitle="Updates as you type. The final score is computed by the server.">
              {!preview ? <p className="muted small" style={{ margin: 0 }}>Enter an amount to see how the rule-based risk engine scores it.</p> : (
                <div className="stack-sm"><RiskGauge score={preview.score} category={preview.category} /><hr className="divider" /><FactorList factors={preview.factors} />
                  <p className="xs faint" style={{ margin: 0 }}>It also uses your own history and the time: recent payment speed, your usual hours, account age and recent biometric changes.</p></div>
              )}
            </Card>
            <Card title="Your biometrics"><Biometrics user={user} /></Card>
          </div>
        </form>
      )}

      {stage === 'risk' && txn && (
        <div className="grid split-even">
          <Card title="Risk assessment" subtitle={`${money(txn.amount, txn.currency)} to ${txn.recipient_name}. Computed by the server.`}>
            <RiskGauge score={txn.risk_score} category={txn.risk_category} />
            <hr className="divider" />
            <FactorList factors={txn.risk_factors} />
          </Card>
          <div className="stack">
            <Card title={`What ${txn.risk_category}-risk payments require`} icon={ShieldCheck}><Requirements txn={txn} policy={policy} user={user} /></Card>
            <Card title="Your biometrics"><Biometrics user={user} /></Card>
            <div className="row">
              <button className="btn primary lg" onClick={() => setStage('verify')}>Continue to verification<ArrowRight size={16} /></button>
              <button className="btn" onClick={reset}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {stage === 'verify' && txn && (
        <Card title={`Verify your identity for payment #${txn.id}`} subtitle={`Attempt ${txn.attempts.length + 1} of ${policy?.max_auth_attempts ?? 3}. Provide any combination; the riskier the payment, the more evidence it needs.`}>
          <div className="stack">
            {txn.attempts.length > 0 && <Alert kind="warn">The last attempt was not enough. Add or retake samples below.</Alert>}
            {needLive && <Alert kind="info"><strong>Live check required.</strong> For {txn.risk_category}-risk payments the face must be a live head turn and the voice must say the words below. Still photos and free recordings are not accepted for those two.</Alert>}
            {!needLive && challenge && <label className="check"><input type="checkbox" checked={liveOptional} onChange={(e) => setLiveOptional(e.target.checked)} />Use the live check anyway (head turn and spoken words)</label>}
            {challenge?.services && useLive && !challenge.services.voice.available && <Alert kind="warn">Spoken challenge unavailable on this server: {challenge.services.voice.detail}. Voice cannot be used for the live check.</Alert>}
            {useLive && <PhraseBanner challenge={challenge} />}
            <div className="grid g3">
              {['face', 'voice', 'fingerprint'].map((m) => {
                const M = MODALITY[m]
                const e = enrolled[m]
                return (
                  <div className={`mod ${m === 'fingerprint' ? '' : ''}`} key={m} data-testid={`verify-${m}`}>
                    <div className="mod-head">
                      <div className="mod-title"><span className="mod-icon"><M.icon size={17} /></span><div><h3>{M.label}</h3><div className="xs faint">{e.required ? 'Required' : 'Optional'}</div></div></div>
                      <StatusBadge status={e.state} />
                    </div>
                    {e.state !== 'enrolled' && <Alert kind="warn">Not enrolled, so a sample here cannot be verified.</Alert>}
                    {!e.module_available && <Alert kind="warn">{e.module_detail}</Alert>}
                    {m === 'face' && useLive ? <LiveFace key={`lf${round}`} challenge={challenge} frames={frames} onChange={setFrames} />
                      : m === 'voice' ? <AudioCapture key={`v${round}`} value={samples[m]} onChange={setS(m)} />
                      : <ImageCapture key={`${m}${round}`} value={samples[m]} onChange={setS(m)} allowCamera={m === 'face'} guide={m === 'face'}
                          uploadLabel={m === 'face' ? 'Upload photo' : 'Upload fingerprint image'} />}
                  </div>
                )
              })}
            </div>
            <div className="row">
              <button className="btn primary lg" disabled={busy} onClick={submit}>{busy ? <><Spinner />Verifying…</> : <><ShieldCheck size={16} />Verify and decide</>}</button>
              <span className="small muted">{evidenceCount === 0 ? 'No sample added: you will be asked for more verification.' : `${evidenceCount} modality sample${evidenceCount > 1 ? 's' : ''} ready.`}</span>
            </div>
          </div>
        </Card>
      )}

      {stage === 'result' && txn && (
        <>
          <ResultView txn={txn} />
          <div className="row">
            {txn.decision === 'additional_verification_required' && <button className="btn primary lg" onClick={() => setStage('verify')}><ArrowLeft size={16} />Add more evidence</button>}
            {closed && <button className="btn primary lg" onClick={reset}><Send size={15} />New payment</button>}
            <Link className="btn" to={`/history/${txn.id}`}><HistoryIcon size={15} />View in history</Link>
          </div>
        </>
      )}
    </div>
  )
}
