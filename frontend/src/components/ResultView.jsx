import { useState } from 'react'
import { DecisionBadge, Meter, RiskBadge, StatusBadge, money, when } from './ui'

const MOD_NAME = { face: 'Face', fingerprint: 'Fingerprint (experimental)', voice: 'Voice' }
const fmt = (x, d = 2) => (x == null ? '–' : Number(x).toFixed(d))

function ModuleRow({ r }) {
  return (
    <div className="mod-card">
      <h3>{MOD_NAME[r.modality]}<StatusBadge status={r.status} /></h3>
      {r.status === 'not_evaluated' ? (
        <p className="small muted" style={{ margin: 0 }}>
          {r.reason || 'Could not be evaluated.'}
          {r.reason_code && <span className="faint"> ({r.reason_code})</span>}
        </p>
      ) : (
        <>
          <div className="row between small"><span>Match probability (calibrated)</span><strong>{fmt(r.calibrated)}</strong></div>
          <Meter value={r.calibrated} tick={0.5} />
          <dl className="kv small" style={{ marginTop: 10 }}>
            <dt>Raw score</dt><dd>{fmt(r.raw_score, 3)} <span className="faint">(module threshold {fmt(r.threshold, 3)})</span></dd>
            <dt>Input quality</dt><dd>{fmt(r.quality)}</dd>
            <dt>Latency</dt><dd>{fmt(r.latency_ms, 0)} ms</dd>
          </dl>
        </>
      )}
      <p className="faint small" style={{ margin: '8px 0 0' }}>{r.method}{r.calibration_source === 'default' ? ' · default (uncalibrated) mapping' : ''}</p>
    </div>
  )
}

function PolicyBox({ title, o, active }) {
  return (
    <div className="mod-card">
      <h3>{title}{active && <span className="badge b-neutral">applied</span>}</h3>
      <div className="row between"><DecisionBadge decision={o.decision} /><span className="small muted">fused {fmt(o.fused_score)} · coverage {fmt(o.coverage)}</span></div>
      <p className="small" style={{ margin: '8px 0 0' }}>{o.explanation}</p>
      <p className="faint small" style={{ margin: '6px 0 0' }}>
        approve ≥ {fmt(o.approve_threshold)}{o.reject_threshold != null ? ` · reject < ${fmt(o.reject_threshold)}` : ' (single fixed threshold)'}
      </p>
    </div>
  )
}

export default function ResultView({ txn }) {
  const [idx, setIdx] = useState(null)
  const attempts = txn.attempts || []
  const a = attempts[idx ?? attempts.length - 1]
  return (
    <div className="stack">
      <div className={`card verdict ${txn.decision}`}>
        <div className="row between">
          <div>
            <div className="small muted">Transaction #{txn.id} · {when(txn.created_at)}</div>
            <h2 style={{ margin: '2px 0 0', fontSize: '1.3rem' }}>{money(txn.amount, txn.currency)} to {txn.recipient_name}</h2>
          </div>
          <DecisionBadge decision={txn.decision} />
        </div>
        {txn.decision_reason && <p style={{ margin: '12px 0 0' }}>{txn.decision_reason}</p>}
        {txn.decision === 'additional_verification_required' && (
          <p className="muted small" style={{ margin: '8px 0 0' }}>Submit more or better biometric samples to continue.</p>
        )}
      </div>

      <div className="grid g2">
        <div className="card">
          <h2>Transaction</h2>
          <dl className="kv">
            <dt>Customer</dt><dd>{txn.user_name}</dd>
            <dt>Recipient</dt><dd>{txn.recipient_name} <span className="faint mono">{txn.recipient_account}</span></dd>
            <dt>Type</dt><dd>{txn.transaction_type.replace('_', ' ')}</dd>
            <dt>New recipient</dt><dd>{txn.recipient_is_new ? 'Yes' : 'No'}</dd>
            <dt>International</dt><dd>{txn.is_international ? 'Yes' : 'No'}</dd>
            <dt>New device</dt><dd>{txn.new_device ? 'Yes' : 'No'}</dd>
            {txn.note && (<><dt>Note</dt><dd>{txn.note}</dd></>)}
          </dl>
        </div>
        <div className="card">
          <h2>Transaction risk <RiskBadge category={txn.risk_category} score={txn.risk_score} /></h2>
          {txn.risk_factors.map((f) => (
            <div className="factor" key={f.name}><span>{f.description}</span><strong>+{fmt(f.points, 0)}</strong></div>
          ))}
          <p className="faint small" style={{ margin: '8px 0 0' }}>Rule-based score out of 100, not a trained fraud model.</p>
        </div>
      </div>

      {!a ? (
        <div className="card muted">No biometric attempt has been made for this transaction yet.</div>
      ) : (
        <>
          {attempts.length > 1 && (
            <div className="row">
              <span className="small muted">Attempt</span>
              {attempts.map((x, i) => (
                <button key={x.id} className={`btn sm ${(idx ?? attempts.length - 1) === i ? 'primary' : ''}`} onClick={() => setIdx(i)}>{i + 1}</button>
              ))}
            </div>
          )}
          <div className="card">
            <h2>Biometric evidence <span className="faint small">attempt {attempts.indexOf(a) + 1} · {fmt(a.latency_ms, 0)} ms · {when(a.created_at)}</span></h2>
            <div className="grid g3">{a.modality_results.map((r) => <ModuleRow key={r.modality} r={r} />)}</div>
          </div>
          <div className="card">
            <h2>Decision policies</h2>
            <div className="grid g2">
              <PolicyBox title="Risk-aware fusion" o={a.risk_aware_outcome} active={a.active_policy === 'risk_aware'} />
              <PolicyBox title="Fixed-threshold fusion" o={a.fixed_outcome} active={a.active_policy === 'fixed'} />
            </div>
            {a.risk_aware_outcome.unmet.length > 0 && (
              <ul className="small muted">{a.risk_aware_outcome.unmet.map((u) => <li key={u}>{u}</li>)}</ul>
            )}
          </div>
        </>
      )}
    </div>
  )
}
