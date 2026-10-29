import { useState } from 'react'
import { ArrowRight, CheckCircle2, Info, ShieldAlert, XCircle } from 'lucide-react'
import { Card, DecisionBadge, FactorList, MODALITY, Meter, RiskBadge, RiskGauge, StatusBadge, money, num, pct, when } from './ui'

const VERDICT = {
  approved: { icon: CheckCircle2, title: 'Approved', lead: 'The evidence was strong enough for this level of risk.' },
  rejected: { icon: XCircle, title: 'Rejected', lead: 'This payment was not authorised.' },
  additional_verification_required: { icon: ShieldAlert, title: 'Additional verification required', lead: 'Not enough evidence yet to approve or reject.' },
  pending: { icon: Info, title: 'Waiting for verification', lead: 'Verify with your biometrics to get a decision.' },
}

// Two reference marks on one bar: where "reject" and "approve" start for this risk level.
function ThresholdMeter({ value, reject, approve }) {
  const v = Math.max(0, Math.min(1, value ?? 0))
  const tone = value == null ? '' : approve != null && value >= approve ? 'ok' : reject != null && value < reject ? 'bad' : 'warn'
  return (
    <div>
      <div className={`meter thick ${tone}`} role="img" aria-label={`fused score ${Math.round(v * 100)} percent`}>
        <span style={{ width: `${v * 100}%` }} />
        {reject != null && <i className="tick" style={{ left: `${reject * 100}%` }} title={`reject below ${reject}`} />}
        {approve != null && <i className="tick" style={{ left: `${approve * 100}%` }} title={`approve from ${approve}`} />}
      </div>
      <div className="row between xs faint" style={{ marginTop: 6 }}>
        <span>0</span>{reject != null && <span>reject below {num(reject)}</span>}<span>approve from {num(approve)}</span><span>1</span>
      </div>
    </div>
  )
}

function Evidence({ r }) {
  const m = MODALITY[r.modality]
  const Icon = m.icon
  const notEvaluated = r.status === 'not_evaluated'
  const hidden = !notEvaluated && r.calibrated == null
  const live = r.details?.liveness
  const tone = r.status === 'match' ? 'ok' : r.status === 'no_match' ? 'bad' : ''
  return (
    <div className="mod" style={{ gap: 10 }}>
      <div className="mod-head">
        <div className="mod-title"><span className="mod-icon"><Icon size={17} /></span><div><h3>{m.label}</h3><div className="xs faint">{r.modality === 'fingerprint' ? 'Optional' : 'Required'}</div></div></div>
        <StatusBadge status={r.status} />
      </div>
      {notEvaluated && (
        <div className="small muted">
          {r.reason_code === 'not_provided' ? 'No sample was submitted for this modality, so it counts as no evidence. It is never treated as a match.' : (r.reason || 'This input could not be evaluated.')}
        </div>
      )}
      {!notEvaluated && !hidden && (
        <>
          <div>
            <div className="evid-score"><span className="small muted">Match confidence</span><b>{pct(r.calibrated, 0)}</b></div>
            <Meter value={r.calibrated} tick={0.5} tone={tone} thick />
          </div>
          <dl className="kv small">
            <dt>Raw score</dt><dd>{num(r.raw_score, 3)} <span className="faint">(threshold {num(r.threshold, 3)})</span></dd>
            <dt>Input quality</dt><dd><div className="row" style={{ gap: 8, flexWrap: 'nowrap' }}><div style={{ flex: 1, minWidth: 40 }}><Meter value={r.quality} /></div><span className="num">{pct(r.quality, 0)}</span></div></dd>
            <dt>Processing</dt><dd>{num(r.latency_ms, 0)} ms</dd>
          </dl>
        </>
      )}
      {hidden && <div className="small muted">Score details are hidden for this account. The result is still {r.status === 'match' ? 'a match' : 'a mismatch'}.</div>}
      {live && (
        <div className="small">
          <span className={`badge ${live.passed ? 'b-ok' : 'b-bad'}`}>Live check {live.passed ? 'passed' : 'failed'}</span>{' '}
          <span className="faint">
            {live.kind === 'head_turn' && live.yaw_change != null && `head turn ${live.yaw_change}, parallax ${live.parallax ?? '–'}`}
            {live.kind === 'spoken_phrase' && `heard ${live.words_matched}/${live.words_needed} words`}
          </span>
        </div>
      )}
      <div className="xs faint">{r.method}{r.calibration_source === 'default' ? ' · default thresholds' : ''}</div>
    </div>
  )
}

function Next({ txn, attempt }) {
  if (txn.decision !== 'additional_verification_required' || !attempt) return null
  const o = attempt.risk_aware_outcome
  const missing = attempt.modality_results.filter((r) => r.status === 'not_evaluated' && r.modality !== 'fingerprint')
  const left = 3 - txn.attempt_count
  return (
    <Card title="What to do next" icon={ArrowRight}>
      <ul className="next-steps">
        {o.unmet.map((u) => <li key={u}>{u[0].toUpperCase() + u.slice(1)}.</li>)}
        {missing.map((r) => <li key={r.modality}>{MODALITY[r.modality].label}: {r.reason_code === 'not_provided' ? 'submit a sample' : r.reason}</li>)}
        {!o.unmet.length && !missing.length && <li>Retake your samples in better conditions and verify again.</li>}
      </ul>
      <p className="small muted" style={{ margin: '10px 0 0' }}>{left} attempt{left === 1 ? '' : 's'} left. After that the payment is rejected.</p>
    </Card>
  )
}

export default function ResultView({ txn, stage = 'result' }) {
  const [idx, setIdx] = useState(null)
  const attempts = txn.attempts || []
  const a = attempts[idx ?? attempts.length - 1]
  const v = VERDICT[txn.decision] || VERDICT.pending
  const Icon = v.icon
  const active = a ? (a.active_policy === 'fixed' ? a.fixed_outcome : a.risk_aware_outcome) : null
  const other = a ? (a.active_policy === 'fixed' ? a.risk_aware_outcome : a.fixed_outcome) : null

  return (
    <div className="stack">
      <div className={`verdict ${txn.decision}`}>
        <div className="verdict-icon"><Icon size={28} /></div>
        <div>
          <div className="xs faint">Transaction #{txn.id} · {when(txn.created_at)}</div>
          <h2>{v.title}</h2>
          <p className="muted" style={{ margin: '4px 0 0', maxWidth: '68ch' }}>{txn.decision_reason || v.lead}</p>
        </div>
        <div className="verdict-amount"><b>{money(txn.amount, txn.currency)}</b><span className="small muted">to {txn.recipient_name}</span></div>
      </div>

      <Next txn={txn} attempt={attempts[attempts.length - 1]} />

      {a && (
        <Card title="Biometric evidence" subtitle={`Attempt ${attempts.indexOf(a) + 1} of ${attempts.length} · ${num(a.latency_ms, 0)} ms · ${when(a.created_at)}`}
          actions={attempts.length > 1 && (
            <div className="row" style={{ gap: 4 }} role="group" aria-label="Attempt">
              {attempts.map((x, i) => <button key={x.id} className={`btn sm ${(idx ?? attempts.length - 1) === i ? 'primary' : ''}`} onClick={() => setIdx(i)}>{i + 1}</button>)}
            </div>)}>
          <div className="grid g3">{a.modality_results.map((r) => <Evidence key={r.modality} r={r} />)}</div>
        </Card>
      )}

      <div className="grid split-even">
        <Card title="Transaction risk" subtitle="Rule-based score out of 100. It is not a trained fraud model.">
          <RiskGauge score={txn.risk_score} category={txn.risk_category} />
          <hr className="divider" />
          <FactorList factors={txn.risk_factors} />
        </Card>

        <Card title="How the decision was made" subtitle={a ? `${a.active_policy === 'fixed' ? 'Fixed-threshold' : 'Risk-aware'} policy applied` : 'Waiting for biometric evidence'}>
          {!a && <p className="muted small">The decision appears here after you verify.</p>}
          {a && active && (
            <div className="stack-sm">
              <div className="row between"><span className="small muted">Fused score</span><strong className="num">{active.fused_score == null ? 'n/a' : num(active.fused_score)}</strong></div>
              {active.fused_score != null && <ThresholdMeter value={active.fused_score} reject={active.reject_threshold} approve={active.approve_threshold} />}
              <dl className="kv small">
                <dt>Risk level</dt><dd><RiskBadge category={active.risk_category} /></dd>
                <dt>Evidence used</dt><dd>{active.usable.length ? active.usable.map((m) => MODALITY[m].label).join(', ') : 'none'}</dd>
                <dt>Coverage</dt><dd>{num(active.coverage)} <span className="faint">of the face and voice evidence</span></dd>
              </dl>
              <p className="small" style={{ margin: 0 }}>{a.explanation}</p>
              {other && (
                <details className="disclosure">
                  <summary>Compare with the {a.active_policy === 'fixed' ? 'risk-aware' : 'fixed-threshold'} policy</summary>
                  <div className="stack-sm">
                    <div className="row"><DecisionBadge decision={other.decision} /><span className="small muted">fused {other.fused_score == null ? 'n/a' : num(other.fused_score)}</span></div>
                    <p className="small muted" style={{ margin: 0 }}>{other.explanation}</p>
                  </div>
                </details>
              )}
            </div>
          )}
        </Card>
      </div>

      <Card title="Payment details">
        <dl className="kv">
          <dt>Customer</dt><dd>{txn.user_name}</dd>
          <dt>Recipient</dt><dd>{txn.recipient_name} <span className="faint mono">{txn.recipient_account}</span></dd>
          <dt>Type</dt><dd className="cap">{txn.transaction_type.replace(/_/g, ' ')}</dd>
          <dt>Flags</dt><dd className="row">
            {txn.recipient_is_new && <span className="chip">new recipient</span>}
            {txn.is_international && <span className="chip">international</span>}
            {txn.new_device && <span className="chip">new device</span>}
            {!txn.recipient_is_new && !txn.is_international && !txn.new_device && <span className="faint">none</span>}
          </dd>
          {txn.note && (<><dt>Note</dt><dd>{txn.note}</dd></>)}
          {stage === 'result' && <><dt>Attempts</dt><dd>{txn.attempt_count}</dd></>}
        </dl>
      </Card>
    </div>
  )
}
