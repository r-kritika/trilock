import { Link, useNavigate } from 'react-router-dom'
import { Activity, CheckCircle2, Clock, Inbox, Send, ShieldAlert, ShieldCheck, XCircle } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { useApi } from '../lib/useApi'
import { useAuth } from '../lib/auth'
import {
  Card, DecisionBadge, Empty, ErrorState, MODALITY, ModalityChip, PageHead, PageSkeleton, RISK_COLOR, RiskBadge, Stat, calibrationLabel, money, pct, whenShort,
} from '../components/ui'

const tip = { background: 'var(--surface-3)', border: '1px solid var(--border-strong)', borderRadius: 8, color: 'var(--text)', fontSize: 12 }
const axis = { fill: 'var(--text-3)', fontSize: 11 }
const OUTCOME = { approved: ['Approved', 'var(--ok)'], additional: ['Needs verification', 'var(--warn)'], rejected: ['Rejected', 'var(--bad)'] }

function TxnTable({ rows, empty }) {
  const nav = useNavigate()
  if (!rows.length) return <p className="muted small" style={{ margin: 0 }}>{empty}</p>
  return (
    <div className="table-wrap"><table>
      <thead><tr><th>#</th><th>Recipient</th><th className="num">Amount</th><th>Risk</th><th>Decision</th><th>When</th></tr></thead>
      <tbody>
        {rows.map((t) => (
          <tr key={t.id} className="click" tabIndex={0} onClick={() => nav(`/history/${t.id}`)} onKeyDown={(e) => e.key === 'Enter' && nav(`/history/${t.id}`)}>
            <td className="mono small">{t.id}</td><td>{t.recipient_name}</td>
            <td className="num">{money(t.amount, t.currency)}</td>
            <td><RiskBadge category={t.risk_category} score={t.risk_score} /></td>
            <td><DecisionBadge decision={t.decision} /></td><td className="small muted nowrap">{whenShort(t.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table></div>
  )
}

function Posture({ s, policy }) {
  const mods = Object.entries(s.modules)
  const ready = mods.filter(([, v]) => v.available).length
  const live = s.liveness
  const liveReady = live && live.face.available && live.voice.available
  return (
    <div className="card">
      <div className="grid g3" style={{ gap: 24 }}>
        <div>
          <div className="stat-label"><span className={`stat-icon ${ready === mods.length ? 'ok' : 'warn'}`}><ShieldCheck size={15} /></span>Biometric modules</div>
          <div className="stat-value" style={{ fontSize: '1.5rem', margin: '6px 0' }}>{ready} of {mods.length} ready</div>
          <div className="row" style={{ gap: 6 }}>{mods.map(([m, v]) => <ModalityChip key={m} modality={m} status={v.available ? 'match' : 'not_evaluated'} />)}</div>
        </div>
        <div>
          <div className="stat-label"><span className={`stat-icon ${liveReady ? 'ok' : 'warn'}`}><Activity size={15} /></span>Liveness challenges</div>
          <div className="stat-value" style={{ fontSize: '1.5rem', margin: '6px 0' }}>{s.liveness_required_from === 'never' ? 'Off' : `From ${s.liveness_required_from} risk`}</div>
          <div className="small muted">{liveReady ? 'Head turn and spoken words are available.' : 'A checker is unavailable. Those inputs count as not evaluated.'}</div>
        </div>
        <div>
          <div className="stat-label"><span className="stat-icon info"><Clock size={15} /></span>Decision policy</div>
          <div className="stat-value" style={{ fontSize: '1.5rem', margin: '6px 0' }}>{policy ? (policy.active_policy === 'risk_aware' ? 'Risk-aware' : 'Fixed threshold') : '–'}</div>
          <div className="small muted"><Link to="/analytics">See thresholds and evaluation</Link></div>
        </div>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { user } = useAuth()
  const { data: s, error, loading, reload } = useApi(api.dashboard)
  const { data: policy } = useApi(() => api.policy().catch(() => null))
  if (loading && !s) return <PageSkeleton />
  if (error) return <ErrorState error={error} onRetry={reload} />
  const admin = user.role === 'admin'
  const total = s.total_transactions
  const share = (n) => (total ? n / total : 0)
  const risk = Object.entries(s.risk_distribution)
  const maxRisk = Math.max(...risk.map(([, n]) => n), 1)
  const a = s.attempts
  const modOutcome = Object.entries(s.modality_outcomes)

  return (
    <div className="stack">
      <PageHead title="Security overview"
        actions={[<span key="scope" className="badge b-neutral">{admin ? 'All accounts' : 'Your activity'}</span>,
          !admin && <Link key="new" to="/transact" className="btn primary"><Send size={15} />New payment</Link>]}>
        Everything here is read from the stored transactions and authentication attempts.
      </PageHead>

      {total === 0 && (
        <Card><Empty icon={Inbox} title="No transactions yet" action={!admin && <Link to="/transact" className="btn primary"><Send size={15} />Make your first payment</Link>}>
          The charts fill in as soon as the first simulated payment is verified.</Empty></Card>
      )}

      <Posture s={s} policy={policy} />

      <div className="grid g4">
        <Stat label="Transactions" value={total} icon={Activity} hint={s.pending ? `${s.pending} waiting for verification` : 'all decided'} />
        <Stat label="Approved" value={s.approved} icon={CheckCircle2} tone="ok" share={share(s.approved)} hint={total ? pct(share(s.approved), 0) + ' of all' : ' '} />
        <Stat label="Rejected" value={s.rejected} icon={XCircle} tone="bad" share={share(s.rejected)} hint={total ? pct(share(s.rejected), 0) + ' of all' : ' '} />
        <Stat label="Needs verification" value={s.additional_verification} icon={ShieldAlert} tone="warn" share={share(s.additional_verification)} hint="waiting for more evidence" />
      </div>

      <div className="grid split-even">
        <Card title="Transaction risk distribution" subtitle="How risky the payments were, by the rule-based score.">
          {total === 0 ? <Empty icon={Inbox} title="No data">Risk levels appear after the first payment.</Empty> : (
            <div className="stack-sm">
              {risk.map(([k, n]) => (
                <div key={k}>
                  <div className="row between small" style={{ marginBottom: 5 }}><span className="cap">{k}</span><span className="muted num">{n} · {pct(share(n), 0)}</span></div>
                  <div className="meter thick"><span style={{ width: `${(n / maxRisk) * 100}%`, background: RISK_COLOR[k] }} /></div>
                </div>
              ))}
              <p className="xs faint" style={{ margin: '8px 0 0' }}>Low below 25, medium 25 to 49, high 50 to 74, critical 75 and above.</p>
            </div>
          )}
        </Card>

        <Card title="Authentication outcomes" subtitle="Verification attempts (a payment can take up to three).">
          {a.total === 0 ? <Empty icon={Inbox} title="No attempts yet">Outcomes appear after a payment is verified.</Empty> : (
            <div className="stack-sm">
              <div className="row between"><div><span className="stat-value" style={{ fontSize: '1.6rem' }}>{pct(a.approved / a.total, 0)}</span> <span className="muted small">approved</span></div>
                <span className="small muted">{a.total} attempts · mean {s.mean_attempt_latency_ms} ms</span></div>
              <div style={{ display: 'flex', height: 10, borderRadius: 999, overflow: 'hidden', background: 'var(--surface-3)', gap: 2 }} role="img" aria-label="Outcome split">
                {Object.entries(OUTCOME).map(([k, [, c]]) => a[k] > 0 && <span key={k} style={{ width: `${(a[k] / a.total) * 100}%`, background: c }} />)}
              </div>
              <div className="legend">{Object.entries(OUTCOME).map(([k, [l, c]]) => <span key={k}><i style={{ background: c }} />{l} {a[k]}</span>)}</div>
              <div className="table-wrap"><table>
                <thead><tr><th>Modality</th><th className="num">Match</th><th className="num">No match</th><th className="num">Not evaluated</th></tr></thead>
                <tbody>{modOutcome.map(([m, o]) => <tr key={m}><td><ModalityChip modality={m} status="off" /></td><td className="num">{o.match}</td><td className="num">{o.no_match}</td><td className="num">{o.not_evaluated}</td></tr>)}</tbody>
              </table></div>
            </div>
          )}
        </Card>
      </div>

      <div className="grid split-even">
        <Card title="Activity, last 14 days">
          {total === 0 ? <Empty icon={Inbox} title="No data">Daily outcomes appear after the first payment.</Empty> : (
            <ResponsiveContainer width="100%" height={230}>
              <BarChart data={s.timeline.map((d) => ({ ...d, day: d.date.slice(5) }))} margin={{ top: 6, right: 4, left: -22, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" />
                <XAxis dataKey="day" tick={axis} tickLine={false} axisLine={false} interval={1} />
                <YAxis allowDecimals={false} tick={axis} tickLine={false} axisLine={false} />
                <Tooltip cursor={{ fill: 'var(--surface-2)' }} contentStyle={tip} />
                <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, color: 'var(--text-2)' }} />
                <Bar dataKey="approved" name="Approved" stackId="a" fill="var(--ok)" maxBarSize={22} />
                <Bar dataKey="additional" name="Needs verification" stackId="a" fill="var(--warn)" maxBarSize={22} />
                <Bar dataKey="rejected" name="Rejected" stackId="a" fill="var(--bad)" maxBarSize={22} />
                <Bar dataKey="pending" name="Pending" stackId="a" fill="var(--neutral)" maxBarSize={22} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
        <Card title="When payments happen" subtitle="Hour of day. Your usual hours are learned from approved payments.">
          {total === 0 ? <Empty icon={Inbox} title="No data">The hourly profile appears after the first payment.</Empty> : (
            <ResponsiveContainer width="100%" height={230}>
              <BarChart data={s.by_hour} margin={{ top: 6, right: 4, left: -22, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" />
                <XAxis dataKey="hour" tick={axis} tickLine={false} axisLine={false} interval={2} />
                <YAxis allowDecimals={false} tick={axis} tickLine={false} axisLine={false} />
                <Tooltip cursor={{ fill: 'var(--surface-2)' }} labelFormatter={(h) => `${String(h).padStart(2, '0')}:00`} contentStyle={tip} />
                <Bar dataKey="count" name="Payments" fill="var(--accent)" radius={[3, 3, 0, 0]} maxBarSize={14} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      <Card title="Biometric modules" subtitle="What is installed and which thresholds each module uses.">
        <div className="grid g3">
          {Object.entries(s.modules).map(([m, v]) => {
            const M = MODALITY[m]
            return (
              <div className={`mod ${v.available ? '' : 'is-unavailable'}`} key={m}>
                <div className="mod-head">
                  <div className="mod-title"><span className="mod-icon"><M.icon size={17} /></span><div><h3>{M.label}</h3><div className="xs faint">{m === 'fingerprint' ? 'Optional · experimental' : 'Required'}</div></div></div>
                  <span className={`badge ${v.available ? 'b-ok' : 'b-bad'}`}>{v.available ? 'Ready' : 'Unavailable'}</span>
                </div>
                <div className="small muted">{v.detail}</div>
                <div className="xs faint">{calibrationLabel(v.calibration)}</div>
              </div>
            )
          })}
        </div>
      </Card>

      <div className="grid split-even">
        <Card title="Recent transactions" actions={<Link to="/history" className="small">View all</Link>}><TxnTable rows={s.recent_transactions} empty="Nothing here yet." /></Card>
        <Card title="Recent rejections" subtitle="Payments that were refused."><TxnTable rows={s.suspicious} empty="No rejected payments." /></Card>
      </div>
    </div>
  )
}
