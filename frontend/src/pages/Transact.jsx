import { useEffect, useState } from 'react'
import { Fingerprint, Mic, ScanFace } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../lib/auth'
import { Alert, PageHead, RiskBadge, StatusBadge } from '../components/ui'
import { AudioCapture, ImageCapture } from '../components/Capture'
import ResultView from '../components/ResultView'

const EMPTY = { amount: '', recipient_name: '', recipient_account: '', transaction_type: 'domestic_transfer',
  recipient_is_new: false, is_international: false, new_device: false, note: '' }

export default function Transact() {
  const { user, refresh } = useAuth()
  const [f, setF] = useState(EMPTY)
  const [preview, setPreview] = useState(null)
  const [txn, setTxn] = useState(null)
  const [samples, setSamples] = useState({})
  const [round, setRound] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  // live risk preview while the form is being filled in
  useEffect(() => {
    const amount = parseFloat(f.amount)
    if (!(amount > 0) || txn) { setPreview(null); return }
    const t = setTimeout(() => {
      api.riskPreview({ amount, transaction_type: f.transaction_type, recipient_is_new: f.recipient_is_new, is_international: f.is_international, new_device: f.new_device })
        .then(setPreview).catch(() => setPreview(null))
    }, 250)
    return () => clearTimeout(t)
  }, [f.amount, f.transaction_type, f.recipient_is_new, f.is_international, f.new_device, txn])

  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  const start = async (e) => {
    e.preventDefault(); setErr(null); setBusy(true)
    try {
      setTxn(await api.createTransaction({ ...f, amount: parseFloat(f.amount), note: f.note || null }))
    } catch (x) { setErr(x.fields?.map((q) => `${q.field}: ${q.message}`).join('; ') || x.message) } finally { setBusy(false) }
  }

  const submit = async () => {
    setErr(null); setBusy(true)
    try {
      setTxn(await api.authenticate(txn.id, samples))
      setSamples({}); setRound((r) => r + 1)
    } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }

  const reset = () => { setTxn(null); setF(EMPTY); setSamples({}); setErr(null); setRound((r) => r + 1) }
  const enrolled = Object.fromEntries(user.enrollments.map((e) => [e.modality, e]))
  const closed = txn && (txn.decision === 'approved' || txn.decision === 'rejected')
  const step = !txn ? 1 : closed ? 3 : 2
  const setS = (k) => (b) => setSamples((s) => ({ ...s, [k]: b || undefined }))

  return (
    <div className="stack">
      <PageHead title="Simulated transaction">No money moves. The transaction is scored for risk, then you verify with whichever biometrics you have.</PageHead>
      <div className="steps">{['1 Transaction', '2 Biometrics', '3 Decision'].map((s, i) => <span key={s} className={`step ${step === i + 1 ? 'on' : ''}`}>{s}</span>)}</div>
      {err && <Alert kind="error">{err}</Alert>}

      {!txn && (
        <form className="grid split" onSubmit={start}>
          <div className="card">
            <h2>Payment details</h2>
            <div className="field"><label>Account</label>
              <div>{user.full_name} <span className="faint mono small">{user.account_number}</span></div></div>
            <div className="grid g2">
              <div className="field"><label htmlFor="a">Amount (USD)</label><input id="a" type="number" min="0.01" step="0.01" required value={f.amount} onChange={set('amount')} /></div>
              <div className="field"><label htmlFor="t">Type</label>
                <select id="t" value={f.transaction_type} onChange={set('transaction_type')}>
                  <option value="domestic_transfer">Domestic transfer</option><option value="bill_payment">Bill payment</option>
                  <option value="cash_withdrawal">Cash withdrawal</option><option value="wire_transfer">Wire transfer</option>
                </select></div>
            </div>
            <div className="grid g2">
              <div className="field"><label htmlFor="r">Recipient name</label><input id="r" type="text" required value={f.recipient_name} onChange={set('recipient_name')} /></div>
              <div className="field"><label htmlFor="ra">Recipient account</label><input id="ra" type="text" required minLength={3} value={f.recipient_account} onChange={set('recipient_account')} /></div>
            </div>
            <div className="field stack">
              <label className="check"><input type="checkbox" checked={f.recipient_is_new} onChange={set('recipient_is_new')} />Recipient is new (never paid before)</label>
              <label className="check"><input type="checkbox" checked={f.is_international} onChange={set('is_international')} />International recipient</label>
              <label className="check"><input type="checkbox" checked={f.new_device} onChange={set('new_device')} />Request comes from a new, unrecognised device</label>
            </div>
            <div className="field"><label htmlFor="no">Note (optional)</label><input id="no" type="text" maxLength={200} value={f.note} onChange={set('note')} /></div>
            <div style={{ marginTop: 14 }}><button className="btn primary" disabled={busy}>{busy ? 'Working…' : 'Continue to authentication'}</button></div>
          </div>
          <div className="card">
            <h2>Risk preview</h2>
            {!preview ? <p className="muted small">Enter an amount to see how the rule-based risk engine scores it.</p> : (
              <>
                <p><RiskBadge category={preview.category} score={preview.score} /></p>
                {preview.factors.map((x) => <div className="factor" key={x.name}><span className="small">{x.description}</span><strong>+{Math.round(x.points)}</strong></div>)}
                <p className="faint small" style={{ marginTop: 8 }}>The final score also considers the customer's approved history, so it can be higher after you submit.</p>
              </>
            )}
            <h3 style={{ marginTop: 18 }}>Enrolled biometrics for {user.full_name}</h3>
            <div className="stack">{user.enrollments.map((e) => <div className="row between" key={e.modality}><span style={{ textTransform: 'capitalize' }}>{e.modality}</span><StatusBadge status={e.state} /></div>)}</div>
          </div>
        </form>
      )}

      {txn && !closed && (
        <div className="card">
          <h2>Verify identity for transaction #{txn.id} <RiskBadge category={txn.risk_category} score={txn.risk_score} /></h2>
          {txn.attempts.length > 0 && <Alert kind="warn">Attempt {txn.attempts.length} was not enough. Add or retake samples below. Remaining attempts: {3 - txn.attempts.length}.</Alert>}
          <p className="muted small">Provide any combination. Anything left blank counts as not provided, never as a match. Higher-risk transactions require more evidence.</p>
          <div className="grid g3">
            {[['face', ScanFace, 'Face'], ['fingerprint', Fingerprint, 'Fingerprint (experimental)'], ['voice', Mic, 'Voice']].map(([m, Icon, title]) => (
              <div className="mod-card stack" key={m}>
                <h3><span className="row" style={{ gap: 8 }}><Icon size={17} />{title}</span><StatusBadge status={enrolled[m].state} /></h3>
                {enrolled[m].state !== 'enrolled' && <Alert kind="warn">Not enrolled. A sample here cannot be verified.</Alert>}
                {!enrolled[m].module_available && <Alert kind="warn">{enrolled[m].module_detail}</Alert>}
                {m === 'voice' ? <AudioCapture key={`v${round}`} value={samples[m]} onChange={setS(m)} />
                  : <ImageCapture key={`${m}${round}`} value={samples[m]} onChange={setS(m)} allowCamera={m === 'face'}
                      uploadLabel={m === 'face' ? 'Upload photo' : 'Upload fingerprint image'} />}
                {samples[m] && <p className="small" style={{ margin: 0 }}>Sample ready.</p>}
              </div>
            ))}
          </div>
          <div className="row" style={{ marginTop: 16 }}>
            <button className="btn primary" disabled={busy} onClick={submit}>{busy ? 'Verifying…' : 'Verify and decide'}</button>
            <span className="small muted">Submitting nothing is allowed; it will simply ask for more verification.</span>
          </div>
        </div>
      )}

      {txn && (
        <>
          <ResultView txn={txn} />
          {closed && <button className="btn primary" onClick={reset}>New transaction</button>}
        </>
      )}
    </div>
  )
}
