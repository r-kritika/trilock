import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, ChevronRight, Inbox, Search, X } from 'lucide-react'
import { api } from '../api/client'
import { useApi } from '../lib/useApi'
import { Card, DecisionBadge, Empty, ErrorState, ModalityChip, PageHead, PageSkeleton, RISK_COLOR, RiskBadge, Skeleton, money, whenShort } from '../components/ui'
import ResultView from '../components/ResultView'

const ORDER = ['face', 'voice', 'fingerprint']

function Detail({ id }) {
  const { data, error, loading, reload } = useApi(() => api.transaction(id), [id])
  return (
    <div className="stack">
      <div><Link to="/history" className="btn ghost sm"><ArrowLeft size={14} />All transactions</Link></div>
      {loading ? <PageSkeleton cards={3} /> : error ? <ErrorState error={error} onRetry={reload} /> : <ResultView txn={data} stage="detail" />}
    </div>
  )
}

// One chip per modality: matched / no match / could not be evaluated / not submitted
function Evidence({ items, pending }) {
  const by = Object.fromEntries((items || []).map((m) => [m.modality, m]))
  return (
    <div className="row" style={{ gap: 5, flexWrap: 'nowrap' }}>
      {ORDER.map((m) => {
        const r = by[m]
        const status = !r || pending ? 'off' : r.reason_code === 'not_provided' ? 'off' : r.status
        return <ModalityChip key={m} modality={m} status={status} />
      })}
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
  const [limit, setLimit] = useState(25)
  useEffect(() => { const t = setTimeout(() => setDebounced(q), 250); return () => clearTimeout(t) }, [q])
  useEffect(() => setLimit(25), [debounced, decision, risk])
  const params = { limit }
  if (debounced) params.q = debounced
  if (decision) params.decision = decision
  if (risk) params.risk_category = risk
  const { data, error, loading, reload } = useApi(() => (id ? Promise.resolve(null) : api.transactions(params)), [id, debounced, decision, risk, limit])

  if (id) return <Detail id={id} />
  const filtered = !!(q || decision || risk)
  const clear = () => { setQ(''); setDecision(''); setRisk('') }

  return (
    <div className="stack">
      <PageHead title="Transaction history">Every simulated payment with its stored risk score, the biometrics that were evaluated, and the decision. Open one for the full explanation.</PageHead>

      <div className="card row" style={{ padding: '12px 16px' }}>
        <div className="input-icon grow" style={{ minWidth: 220 }}>
          <Search size={15} />
          <input type="text" aria-label="Search" placeholder="Search recipient, account, name or #id" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select aria-label="Decision" value={decision} onChange={(e) => setDecision(e.target.value)} style={{ width: 'auto', minWidth: 180 }}>
          <option value="">All decisions</option><option value="approved">Approved</option><option value="rejected">Rejected</option>
          <option value="additional_verification_required">Additional verification</option><option value="pending">Pending</option>
        </select>
        <select aria-label="Risk" value={risk} onChange={(e) => setRisk(e.target.value)} style={{ width: 'auto', minWidth: 150 }}>
          <option value="">All risk levels</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option>
        </select>
        {filtered && <button className="btn ghost sm" onClick={clear}><X size={13} />Clear</button>}
      </div>

      <Card flush>
        {error ? <div style={{ padding: 20 }}><ErrorState error={error} onRetry={reload} /></div>
          : loading && !data ? <div style={{ padding: 20 }} className="stack-sm">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} h={38} />)}</div>
          : data.items.length === 0 ? (
            <Empty icon={Inbox} title={filtered ? 'No matching transactions' : 'No transactions yet'}
              action={filtered ? <button className="btn" onClick={clear}>Clear filters</button> : <Link to="/transact" className="btn primary">Make a payment</Link>}>
              {filtered ? 'Try a different search or clear the filters.' : 'Payments you verify will be listed here.'}</Empty>
          ) : (
            <>
              <div className="table-wrap" style={{ margin: 0, padding: 0 }}><table>
                <thead><tr><th>#</th><th>When</th><th>Recipient</th><th className="num">Amount</th><th>Risk</th><th>Biometrics evaluated</th><th>Decision</th><th /></tr></thead>
                <tbody>{data.items.map((t) => (
                  <tr key={t.id} className="click" tabIndex={0} onClick={() => nav(`/history/${t.id}`)} onKeyDown={(e) => e.key === 'Enter' && nav(`/history/${t.id}`)}>
                    <td className="mono small">{t.id}</td>
                    <td className="small muted nowrap">{whenShort(t.created_at)}</td>
                    <td>{t.recipient_name}{t.recipient_is_new && <span className="chip" style={{ marginLeft: 8 }}>new</span>}{t.user_name && <div className="xs faint">{t.user_name}</div>}</td>
                    <td className="num">{money(t.amount, t.currency)}</td>
                    <td style={{ minWidth: 130 }}><div className="stack-sm" style={{ gap: 5 }}><RiskBadge category={t.risk_category} score={t.risk_score} />
                      <div className="meter" style={{ height: 3 }}><span style={{ width: `${t.risk_score}%`, background: RISK_COLOR[t.risk_category] }} /></div></div></td>
                    <td><Evidence items={t.modality_summary} pending={t.decision === 'pending'} /></td>
                    <td><DecisionBadge decision={t.decision} />{t.attempt_count > 1 && <div className="xs faint" style={{ marginTop: 3 }}>{t.attempt_count} attempts</div>}</td>
                    <td className="faint"><ChevronRight size={16} /></td>
                  </tr>))}
                </tbody></table></div>
              <div className="row between" style={{ padding: '12px 20px', borderTop: '1px solid var(--border)' }}>
                <span className="small muted">Showing {data.items.length} of {data.total}</span>
                {data.items.length < data.total && <button className="btn sm" onClick={() => setLimit(limit + 25)}>Load more</button>}
              </div>
            </>
          )}
      </Card>
    </div>
  )
}
