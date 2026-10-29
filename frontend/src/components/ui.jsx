import { useState } from 'react'
import {
  AlertTriangle, CheckCircle2, ChevronRight, CircleHelp, Clock, Fingerprint, Info, Mic, ScanFace, ShieldAlert, ShieldCheck, XCircle,
} from 'lucide-react'

// ---------------------------------------------------------------- formatting
export const money = (n, cur = 'USD') => new Intl.NumberFormat('en-US', { style: 'currency', currency: cur }).format(n)
export const when = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '')
export const whenShort = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '')
export const pct = (x, d = 1) => (x == null ? '–' : `${(x * 100).toFixed(d)}%`)
export const num = (x, d = 2) => (x == null ? '–' : Number(x).toFixed(d))

// ---------------------------------------------------------------- badges
export const DECISION_LABEL = {
  approved: 'Approved',
  rejected: 'Rejected',
  additional_verification_required: 'Additional verification',
  pending: 'Pending',
}
const DECISION_ICON = { approved: CheckCircle2, rejected: XCircle, additional_verification_required: ShieldAlert, pending: Clock }
const STATUS_LABEL = { match: 'Match', no_match: 'No match', not_evaluated: 'Not evaluated', enrolled: 'Enrolled', not_enrolled: 'Not enrolled' }
export const MODALITY = {
  face: { label: 'Face', short: 'Face', icon: ScanFace },
  voice: { label: 'Voice', short: 'Voice', icon: Mic },
  fingerprint: { label: 'Fingerprint', short: 'Finger', icon: Fingerprint },
}

// Colour is never the only signal: every badge carries a text label (decisions also an icon).
export function DecisionBadge({ decision }) {
  const Icon = DECISION_ICON[decision] || CircleHelp
  return <span className={`badge b-${decision}`}><Icon size={12} />{DECISION_LABEL[decision] || decision}</span>
}
export function StatusBadge({ status }) {
  return <span className={`badge b-${status}`}>{STATUS_LABEL[status] || status}</span>
}
export function RiskBadge({ category, score }) {
  return <span className={`badge b-${category}`}><span className="dot" />{category}{score != null ? ` · ${Math.round(score)}` : ''}</span>
}
// Where a number comes from. Real dataset results, synthetic data and simulated scenarios are never mixed up.
const SOURCE = {
  real: ['b-real', 'Real dataset', 'Measured on a public dataset of real recordings or photos.'],
  synthetic: ['b-synthetic', 'Synthetic data', 'Generated data, not real fingerprints, faces or voices.'],
  simulated: ['b-simulated', 'Simulated', 'Simulated attempts or attacks built from measured scores. Not real-world accuracy.'],
  illustrative: ['b-neutral', 'Illustrative', 'Hand-written scenario run through the real code. Not a measurement.'],
}
export function DataBadge({ kind }) {
  const [cls, label, tip] = SOURCE[kind] || SOURCE.illustrative
  return <span className={`badge ${cls}`} title={tip}>{label}</span>
}
export function ModalityChip({ modality, status }) {
  const m = MODALITY[modality]
  const Icon = m?.icon || CircleHelp
  const cls = status === 'match' ? 'ok' : status === 'no_match' ? 'bad' : status === 'not_evaluated' ? 'warn' : 'off'
  const label = status === 'match' ? 'matched' : status === 'no_match' ? 'no match' : status === 'not_evaluated' ? 'not evaluated' : 'not used'
  return <span className={`chip ${cls}`} title={`${m?.label || modality}: ${label}`}><Icon size={12} />{m?.short || modality}</span>
}

// ---------------------------------------------------------------- feedback
export function Alert({ kind = 'info', children, action }) {
  const Icon = { error: XCircle, warn: AlertTriangle, ok: ShieldCheck, info: Info }[kind]
  return (
    <div className={`alert ${kind}`} role={kind === 'error' ? 'alert' : undefined}>
      <Icon size={16} /><div className="grow">{children}</div>{action}
    </div>
  )
}
export function Empty({ icon: Icon = Info, title, children, action }) {
  return <div className="empty"><Icon size={26} /><strong>{title}</strong><div className="small">{children}</div>{action && <div style={{ marginTop: 12 }}>{action}</div>}</div>
}
export function ErrorState({ error, onRetry }) {
  return <Alert kind="error" action={onRetry && <button className="btn sm" onClick={onRetry}>Retry</button>}>{error?.message || 'Something went wrong.'}</Alert>
}
export function Spinner() { return <span className="spinner" role="status" aria-label="Loading" /> }
export function Skeleton({ h = 16, w = '100%', style }) { return <div className="skeleton" style={{ height: h, width: w, ...style }} aria-hidden /> }
export function PageSkeleton({ cards = 4 }) {
  return (
    <div className="stack" aria-busy="true" aria-label="Loading">
      <Skeleton h={32} w="30%" />
      <div className="grid g4">{Array.from({ length: cards }).map((_, i) => <div className="card" key={i}><Skeleton h={12} w="50%" /><Skeleton h={30} w="40%" style={{ marginTop: 12 }} /></div>)}</div>
      <div className="grid g2"><div className="card"><Skeleton h={180} /></div><div className="card"><Skeleton h={180} /></div></div>
    </div>
  )
}
// kept for older call sites
export function Loading({ label = 'Loading…' }) { return <p className="muted" aria-busy="true">{label}</p> }

// ---------------------------------------------------------------- layout helpers
export function PageHead({ title, children, actions }) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1>{children && <p className="muted">{children}</p>}</div>
      {actions && <div className="row">{actions}</div>}
    </div>
  )
}
export function Card({ title, icon: Icon, subtitle, actions, children, flush, className = '' }) {
  return (
    <section className={`card ${flush ? 'flush' : ''} ${className}`}>
      {(title || actions) && (
        <div className="card-head" style={flush ? { padding: '18px 20px 0' } : undefined}>
          <div><h2>{Icon && <Icon size={16} style={{ color: 'var(--text-3)' }} />}{title}</h2>{subtitle && <p className="muted small">{subtitle}</p>}</div>
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  )
}
export function Stat({ label, value, icon: Icon, tone, hint, share }) {
  return (
    <div className="card stat">
      <div className="stat-label">{Icon && <span className={`stat-icon ${tone || ''}`}><Icon size={15} /></span>}{label}</div>
      <div className="stat-value">{value}</div>
      {share != null && <div className={`meter ${tone || ''}`} aria-hidden><span style={{ width: `${Math.max(0, Math.min(1, share)) * 100}%` }} /></div>}
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  )
}
export function Disclosure({ title, children, open }) {
  return <details className="disclosure" open={open}><summary>{title}</summary><div>{children}</div></details>
}
export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map(([id, label]) => (
        <button key={id} role="tab" aria-selected={value === id} className={`tab ${value === id ? 'on' : ''}`} onClick={() => onChange(id)}>{label}</button>
      ))}
    </div>
  )
}
export function Stepper({ steps, current }) {
  return (
    <div className="stepper" role="list" aria-label="Progress">
      {steps.map((label, i) => {
        const state = i < current ? 'done' : i === current ? 'on' : ''
        return (
          <div key={label} style={{ display: 'flex', alignItems: 'center' }} role="listitem" aria-current={i === current ? 'step' : undefined}>
            <div className={`step ${state}`}>
              <span className="step-dot">{i < current ? '✓' : i + 1}</span><span className="lbl">{label}</span>
            </div>
            {i < steps.length - 1 && <span className={`step-line ${i < current ? 'done' : ''}`} />}
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------- meters and risk
export function Meter({ value, tick, tone, thick }) {
  const v = Math.max(0, Math.min(1, value || 0))
  return (
    <div className={`meter ${tone || ''} ${thick ? 'thick' : ''}`} role="img" aria-label={`${Math.round(v * 100)} percent`}>
      <span style={{ width: `${v * 100}%` }} />
      {tick != null && <i className="tick" style={{ left: `${tick * 100}%` }} title={`threshold ${tick}`} />}
    </div>
  )
}
export const RISK_COLOR = { low: 'var(--r-low)', medium: 'var(--r-med)', high: 'var(--r-high)', critical: 'var(--r-crit)' }
export function RiskGauge({ score, category, compact }) {
  const s = Math.max(0, Math.min(100, score || 0))
  return (
    <div className="gauge">
      <div className="gauge-top">
        <span className="gauge-score" style={{ color: RISK_COLOR[category] }}>{Math.round(s)}</span>
        <span className="gauge-of">/ 100</span>
        <RiskBadge category={category} />
      </div>
      <div className="gauge-wrap">
        <div className="gauge-bar" />
        <div className="gauge-pin" style={{ left: `${s}%` }} />
      </div>
      {!compact && <div className="gauge-scale"><span>Low</span><span>Medium</span><span>High</span><span>Critical</span></div>}
    </div>
  )
}
export function FactorList({ factors }) {
  const max = Math.max(...factors.map((f) => f.points), 1)
  return (
    <div>
      {factors.map((f) => (
        <div className="factor" key={f.name}>
          <span className="small">{f.description}</span><strong className="num">+{Math.round(f.points)}</strong>
          <Meter value={f.points / Math.max(max, 20)} />
        </div>
      ))}
    </div>
  )
}
// "Calibrated on LFW" instead of a file path
export function calibrationLabel(src) {
  if (!src || src === 'default') return 'default thresholds (uncalibrated)'
  const s = String(src).toLowerCase()
  if (s.includes('lfw')) return 'calibrated on LFW photos'
  if (s.includes('librispeech')) return 'calibrated on LibriSpeech'
  return 'calibrated on a labelled dataset'
}
export { ChevronRight }
