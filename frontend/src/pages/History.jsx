import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Inbox, Search } from 'lucide-react'
import { api } from '../api/client'
import { useApi } from '../lib/useApi'
import { Alert, DecisionBadge, Empty, Loading, PageHead, RiskBadge, StatusBadge, money, when } from '../components/ui'
import ResultView from '../components/ResultView'

function Detail({ id }) {
  const { data, error, loading } = useApi(() => api.transaction(id), [id])
  return (
    <div className="stack">
      <Link to="/history" className="row" style={{ textDecoration: 'none' }}><ArrowLeft size={15} />Back to history</Link>
      {loading ? <Loading /> : error ? <Alert kind="error">{error.message}</Alert> : <ResultView txn={data} />}
    </div>
  )
}

function Summary({ items }) {
  if (!items.length) return <span className="faint small">no attempt</span>
  return (
    <div className="row" style={{ gap: 4 }}>
      {items.map((m) => (
        <span key={m.modality} title={m.reason || `${m.modality}: ${m.status}`}>
          <StatusBadge status={m.status} />
        </span>
      ))}
    </div>
  )
}

export default function HistoryPage() {
  const { id } = useParams()
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [decision, setDecision] = useState('')
  const [risk, setRisk] = useState('')
  const [debounced, setDebounced] = useState('')
  useEffect(() => { const t = setTimeout(() => setDebounced(q), 250); return () => clearTimeout(t) }, [q])
  const params = {}
  if (debounced) params.q = debounced
  if (decision) params.decision = decision
  if (risk) params.risk_category = risk
  const { data, error, loading } = useApi(() => (id ? Promise.resolve(null) : api.transactions(params)), [id, debounced, decision, risk])

  if (id) return <Detail id={id} />
  const filtered = q || decision || risk

  return (
    <div className="stack">
      <PageHead title="Transaction history">Every simulated transaction with its stored risk score, biometric evidence and decision.</PageHead>
      <div className="card row">
        <div style={{ flex: '1 1 240px', position: 'relative' }}>
          <Search size={15} style={{ position: 'absolute', left: 10, top: 11, color: 'var(--text-3)' }} />
          <input type="text" aria-label="Search" placeholder="Search recipient, account, customer or #id" value={q} onChange={(e) => setQ(e.target.value)} style={{ paddingLeft: 32 }} />
        </div>
        <select aria-label="Decision" value={decision} onChange={(e) => setDecision(e.target.value)} style={{ width: 'auto' }}>
          <option value="">All decisions</option><option value="approved">Approved</option><option value="rejected">Rejected</option>
          <option value="additional_verification_required">Additional verification</option><option value="pending">Pending</option>
        </select>
        <select aria-label="Risk" value={risk} onChange={(e) => setRisk(e.target.value)} style={{ width: 'auto' }}>
          <option value="">All risk levels</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option>
        </select>
      </div>
      <div className="card">
        {loading && !data ? <Loading /> : error ? <Alert kind="error">{error.message}</Alert> : data.items.length === 0 ? (
          <Empty icon={Inbox} title={filtered ? 'No matching transactions' : 'No transactions yet'}>{filtered ? 'Try clearing the filters.' : 'Start one from New transaction.'}</Empty>
        ) : (
          <div className="table-wrap"><table>
            <thead><tr><th>#</th><th>When</th><th>Customer</th><th>Recipient</th><th className="num">Amount</th><th>Risk</th><th>Biometrics</th><th>Decision</th></tr></thead>
            <tbody>{data.items.map((t) => (
              <tr key={t.id} className="click" onClick={() => nav(`/history/${t.id}`)}>
                <td>{t.id}</td><td className="small muted">{when(t.created_at)}</td><td>{t.user_name}</td>
                <td>{t.recipient_name}{t.recipient_is_new && <span className="badge b-neutral" style={{ marginLeft: 6 }}>new</span>}</td>
                <td className="num">{money(t.amount, t.currency)}</td><td><RiskBadge category={t.risk_category} score={t.risk_score} /></td>
                <td><Summary items={t.modality_summary} /></td><td><DecisionBadge decision={t.decision} /></td>
              </tr>))}
            </tbody></table>
            <p className="faint small">Showing {data.items.length} of {data.total}. Open a row for the full explanation.</p>
          </div>
        )}
      </div>
    </div>
  )
}
