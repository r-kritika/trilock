import { AlertTriangle, CheckCircle2, CircleHelp, Clock, Info, ShieldAlert, ShieldCheck, XCircle } from 'lucide-react'

export const DECISION_LABEL = {
  approved: 'Approved',
  rejected: 'Rejected',
  additional_verification_required: 'Additional verification',
  pending: 'Pending',
}
const DECISION_ICON = {
  approved: CheckCircle2, rejected: XCircle, additional_verification_required: ShieldAlert, pending: Clock,
}
const STATUS_LABEL = { match: 'Match', no_match: 'No match', not_evaluated: 'Not evaluated', enrolled: 'Enrolled', not_enrolled: 'Not enrolled' }

// Colour is never the only signal: every badge has a text label (and decisions an icon).
export function DecisionBadge({ decision }) {
  const Icon = DECISION_ICON[decision] || CircleHelp
  return <span className={`badge b-${decision}`}><Icon size={13} />{DECISION_LABEL[decision] || decision}</span>
}
export function StatusBadge({ status }) {
  return <span className={`badge b-${status}`}>{STATUS_LABEL[status] || status}</span>
}
export function RiskBadge({ category, score }) {
  return <span className={`badge b-${category}`}>{category}{score != null ? ` · ${Math.round(score)}` : ''}</span>
}

export function Alert({ kind = 'info', children }) {
  const Icon = { error: XCircle, warn: AlertTriangle, ok: ShieldCheck, info: Info }[kind]
  return <div className={`alert ${kind}`} role={kind === 'error' ? 'alert' : undefined}><Icon size={17} /><div>{children}</div></div>
}

export function Empty({ icon: Icon = Info, title, children }) {
  return <div className="empty"><Icon size={28} /><div><strong>{title}</strong></div><div className="small">{children}</div></div>
}

export function Loading({ label = 'Loading…' }) { return <p className="muted">{label}</p> }

export function PageHead({ title, children }) {
  return <div className="page-head"><h1>{title}</h1><p className="muted">{children}</p></div>
}

export const money = (n, cur = 'USD') =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: cur }).format(n)
export const when = (iso) => (iso ? new Date(iso).toLocaleString() : '')
export const pct = (x) => (x == null ? '–' : `${(x * 100).toFixed(1)}%`)

export function Meter({ value, tick }) {
  return (
    <div className="meter" role="img" aria-label={`${Math.round((value || 0) * 100)} percent`}>
      <span style={{ width: `${Math.max(0, Math.min(1, value || 0)) * 100}%` }} />
      {tick != null && <i className="tick" style={{ left: `${tick * 100}%` }} title={`threshold ${tick}`} />}
    </div>
  )
}
