import { Link } from 'react-router-dom'
import { Activity, CheckCircle2, Inbox, ShieldAlert, XCircle } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { useApi } from '../lib/useApi'
import { Alert, DecisionBadge, Empty, Loading, PageHead, RiskBadge, money, when } from '../components/ui'

const RISK_COLORS = { low: 'var(--r-low)', medium: 'var(--r-med)', high: 'var(--r-high)', critical: 'var(--r-crit)' }

function Stat({ label, value, icon: Icon, hint }) {
  return (
    <div className="card stat">
      <div className="label"><Icon size={15} />{label}</div>
      <div className="value">{value}</div>
      {hint && <div className="faint small">{hint}</div>}
    </div>
  )
}

function TxnTable({ rows, empty }) {
  if (!rows.length) return <p className="muted small">{empty}</p>
  return (
    <div className="table-wrap"><table>
      <thead><tr><th>#</th><th>Customer</th><th>Recipient</th><th className="num">Amount</th><th>Risk</th><th>Decision</th><th>When</th></tr></thead>
      <tbody>
        {rows.map((t) => (
          <tr key={t.id}>
            <td><Link to={`/history/${t.id}`}>{t.id}</Link></td><td>{t.user_name}</td><td>{t.recipient_name}</td>
            <td className="num">{money(t.amount, t.currency)}</td>
            <td><RiskBadge category={t.risk_category} score={t.risk_score} /></td>
            <td><DecisionBadge decision={t.decision} /></td><td className="small muted">{when(t.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table></div>
  )
}

export default function Dashboard() {
  const { data: s, error, loading } = useApi(api.dashboard)
  if (loading) return <Loading />
  if (error) return <Alert kind="error">{error.message}</Alert>
  const risk = Object.entries(s.risk_distribution).map(([name, count]) => ({ name, count }))
  const decided = s.attempts.total
  const modOutcome = Object.entries(s.modality_outcomes)

  return (
    <div className="stack">
      <PageHead title="Dashboard">Live figures from the stored transactions and authentication attempts.</PageHead>
      {s.total_transactions === 0 && (
        <Alert kind="info">No transactions yet. <Link to="/enroll">Enroll a test user</Link>, then <Link to="/transact">start a transaction</Link>.</Alert>
      )}
      <div className="grid g4">
        <Stat label="Transactions" value={s.total_transactions} icon={Activity} hint={`${s.pending} pending authentication`} />
        <Stat label="Approved" value={s.approved} icon={CheckCircle2} />
        <Stat label="Rejected" value={s.rejected} icon={XCircle} />
        <Stat label="Additional verification" value={s.additional_verification} icon={ShieldAlert} hint="waiting for more evidence" />
      </div>

      <div className="grid g2">
        <div className="card">
          <h2>Transaction risk distribution</h2>
          {s.total_transactions === 0 ? <Empty icon={Inbox} title="No data">Risk categories appear after the first transaction.</Empty> : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={risk} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" />
                <XAxis dataKey="name" stroke="var(--text-3)" tickLine={false} />
                <YAxis allowDecimals={false} stroke="var(--text-3)" tickLine={false} axisLine={false} />
                <Tooltip cursor={{ fill: 'var(--surface-2)' }} contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6 }} />
                <Bar dataKey="count" name="Transactions" radius={[4, 4, 0, 0]} maxBarSize={56}>
                  {risk.map((r) => <Cell key={r.name} fill={RISK_COLORS[r.name]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="card">
          <h2>Authentication attempts</h2>
          {decided === 0 ? <Empty icon={Inbox} title="No attempts yet">Attempt outcomes appear after a transaction is authenticated.</Empty> : (
            <>
              <div className="grid g3" style={{ marginBottom: 12 }}>
                <div><div className="faint small">Approved</div><strong style={{ fontSize: '1.4rem' }}>{s.attempts.approved}</strong></div>
                <div><div className="faint small">Rejected</div><strong style={{ fontSize: '1.4rem' }}>{s.attempts.rejected}</strong></div>
                <div><div className="faint small">Needs more</div><strong style={{ fontSize: '1.4rem' }}>{s.attempts.additional}</strong></div>
              </div>
              <p className="small muted">Success rate {Math.round((s.attempts.approved / decided) * 100)}% of {decided} attempts · mean processing {s.mean_attempt_latency_ms} ms.</p>
              <table><thead><tr><th>Module</th><th className="num">Match</th><th className="num">No match</th><th className="num">Not evaluated</th></tr></thead>
                <tbody>{modOutcome.map(([m, o]) => (
                  <tr key={m}><td style={{ textTransform: 'capitalize' }}>{m}</td><td className="num">{o.match}</td><td className="num">{o.no_match}</td><td className="num">{o.not_evaluated}</td></tr>
                ))}</tbody></table>
            </>
          )}
        </div>
      </div>

      <div className="card">
        <h2>Biometric module status</h2>
        <div className="grid g3">
          {Object.entries(s.modules).map(([m, v]) => (
            <div className="mod-card" key={m}>
              <h3 style={{ textTransform: 'capitalize' }}>{m}<span className={`badge ${v.available ? 'b-approved' : 'b-rejected'}`}>{v.available ? 'Ready' : 'Unavailable'}</span></h3>
              <p className="small muted" style={{ margin: 0 }}>{v.detail}</p>
              <p className="small faint" style={{ margin: '6px 0 0' }}>Calibration: {v.calibration === 'default' ? 'default starting values' : v.calibration}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="card"><h2>Recent transactions</h2><TxnTable rows={s.recent_transactions} empty="Nothing here yet." /></div>
      <div className="card"><h2>Recent rejected transactions</h2><TxnTable rows={s.suspicious} empty="No rejected transactions." /></div>
    </div>
  )
}
