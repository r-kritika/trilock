import { useState } from 'react'
import { FlaskConical, Inbox } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { useApi } from '../lib/useApi'
import { Alert, DecisionBadge, Empty, Loading, PageHead, pct, when } from '../components/ui'

const FIXED = 'var(--r-low)', MIN2 = 'var(--text-3)', AWARE = 'var(--r-crit)'
const POLS = [['fixed', 'Fixed'], ['fixed_min2', 'Fixed + min 2 modalities'], ['risk_aware', 'Risk-aware']]
const tip = { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6 }
const ci = (c) => (c && c[0] != null ? ` [${pct(c[0])} to ${pct(c[1])}]` : '')
const ms = (o) => (o?.mean == null ? '–' : `${pct(o.mean)} ± ${pct(o.sd)}`)

function Source({ run }) {
  return (
    <span className="faint small">
      {run.is_synthetic ? <span className="badge b-warn">synthetic data</span> : <span className="badge b-approved">real dataset</span>}
      {' '}{run.data_source} · {when(run.created_at)}
    </span>
  )
}

function latestByModality(runs) {
  const seen = new Set()
  return runs.filter((r) => {
    const k = r.kind === 'modality' && r.metrics.modality + r.is_synthetic
    if (!k || seen.has(k)) return false
    seen.add(k)
    return true
  })
}

function ModalityTable({ runs }) {
  const rows = latestByModality(runs)
  if (!rows.length) return <Empty icon={Inbox} title="No biometric evaluation has been run">Run <code>python -m app.evaluation.run_modality</code> (see docs/EVALUATION.md).</Empty>
  return (
    <div className="table-wrap"><table>
      <thead><tr><th>Module</th><th>Data</th><th className="num">Genuine / impostor trials</th><th className="num">EER</th>
        <th className="num">FAR (95% CI)</th><th className="num">FRR (95% CI)</th><th className="num">FAR over {rows[0].metrics.splits?.count ?? '–'} splits</th><th className="num">FRR over splits</th>
        <th className="num">Not evaluable</th><th className="num">Latency mean / p95</th></tr></thead>
      <tbody>{rows.map((r) => {
        const m = r.metrics
        return (
          <tr key={r.id}>
            <td style={{ textTransform: 'capitalize' }}><strong>{m.modality}</strong></td>
            <td><Source run={r} /></td>
            <td className="num">{m.genuine_trials} / {m.impostor_trials}</td>
            <td className="num">{pct(m.eer)}</td>
            <td className="num">{pct(m.far)}<div className="faint small">{ci(m.far_ci)}</div></td>
            <td className="num">{pct(m.frr)}<div className="faint small">{ci(m.frr_ci)}</div></td>
            <td className="num">{ms(m.splits?.far)}</td><td className="num">{ms(m.splits?.frr)}</td>
            <td className="num">{pct(m.not_evaluable_rate)}</td><td className="num">{m.latency_ms_mean} / {m.latency_ms_p95} ms</td>
          </tr>)
      })}</tbody></table>
      <p className="faint small">Primary split shown; thresholds were fitted on a disjoint half of the subjects. Intervals assume independent trials, which repeated use of the same speakers or faces violates, so treat them as optimistic. Inputs a module could not evaluate are counted separately, never as errors or matches.</p>
    </div>
  )
}

function DegradedTable({ runs }) {
  const rows = latestByModality(runs).filter((r) => r.metrics.degraded?.length)
  if (!rows.length) return <p className="muted small">No degraded-input measurements stored.</p>
  return (
    <div className="table-wrap"><table>
      <thead><tr><th>Module</th><th>Condition</th><th className="num">Trials</th><th className="num">FAR</th><th className="num">FRR</th><th className="num">Not evaluable</th></tr></thead>
      <tbody>{rows.flatMap((r) => r.metrics.degraded.map((d) => (
        <tr key={r.id + d.condition}><td style={{ textTransform: 'capitalize' }}>{r.metrics.modality}{r.is_synthetic ? ' (synthetic)' : ''}</td><td>{d.condition}</td>
          <td className="num">{d.trials}</td><td className="num">{pct(d.far)}</td><td className="num">{pct(d.frr)}</td><td className="num">{pct(d.not_evaluable_rate)}</td></tr>)))}
      </tbody></table></div>
  )
}

const METRICS = [
  ['far', 'Impostor approved (zero effort)'],
  ['worst_bypass_asr', 'Worst single-modality bypass'],
  ['worst_omission_asr', 'Worst omission attack'],
  ['frr', 'Genuine user rejected'],
  ['genuine_additional_rate', 'Genuine user asked for more'],
]

function FusionSection({ run }) {
  const [cond, setCond] = useState(0)
  const [yMetric, setYMetric] = useState('worst_omission_asr')
  const m = run.metrics
  const c = m.conditions[cond]
  const o = c.overall
  const chart = METRICS.map(([k, label]) => ({ metric: label, ...Object.fromEntries(POLS.map(([p, n]) => [n, +((o[p][k] ?? 0) * 100).toFixed(2)])) }))
  const sweep = (c.fixed_sweep || []).map((p) => ({ x: +(p.genuine_not_approved * 100).toFixed(2), y: +((yMetric === 'far' ? p.far : yMetric === 'worst_omission_asr' ? p.worst_omission_asr : p.worst_bypass_asr) * 100).toFixed(2), t: p.threshold }))
  const point = (p) => [{ x: +(((o[p].frr ?? 0) + (o[p].genuine_additional_rate ?? 0)) * 100).toFixed(2), y: +((o[p][yMetric] ?? 0) * 100).toFixed(2) }]
  return (
    <div className="stack">
      <div className="row between"><Source run={run} />
        <span className="small muted">{m.attempts_per_cell} attempts per scenario and risk level, {m.repeats} repeats, smallest score pool {c.pool_size_min} trials</span></div>
      {run.is_synthetic && <Alert kind="warn">At least one modality here uses synthetic scores, and the risk mix is assumed. This compares policy behaviour; it is not evidence of real-world accuracy.</Alert>}
      <div className="row"><label htmlFor="cond" style={{ margin: 0 }}>Input condition</label>
        <select id="cond" style={{ width: 'auto' }} value={cond} onChange={(e) => setCond(+e.target.value)}>
          {m.conditions.map((x, i) => <option key={x.name} value={i}>{x.name}</option>)}</select></div>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={chart} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis dataKey="metric" stroke="var(--text-3)" tickLine={false} fontSize={11} interval={0} />
          <YAxis unit="%" stroke="var(--text-3)" tickLine={false} axisLine={false} />
          <Tooltip contentStyle={tip} cursor={{ fill: 'var(--surface-2)' }} formatter={(v) => `${v}%`} />
          <Legend />
          <Bar dataKey="Fixed" fill={FIXED} radius={[4, 4, 0, 0]} maxBarSize={32} />
          <Bar dataKey="Fixed + min 2 modalities" fill={MIN2} radius={[4, 4, 0, 0]} maxBarSize={32} />
          <Bar dataKey="Risk-aware" fill={AWARE} radius={[4, 4, 0, 0]} maxBarSize={32} />
        </BarChart>
      </ResponsiveContainer>
      <div className="table-wrap"><table>
        <thead><tr><th>By risk level</th><th>Policy</th><th className="num">FAR</th><th className="num">FRR</th><th className="num">Genuine asked for more</th><th className="num">Worst bypass</th><th className="num">Worst omission attack</th></tr></thead>
        <tbody>{Object.entries(c.by_risk).flatMap(([cat, p]) => POLS.map(([k, name], i) => (
          <tr key={cat + k}><td style={{ textTransform: 'capitalize' }}>{i === 0 ? cat : ''}</td><td>{name}</td>
            <td className="num">{pct(p[k].far)}</td><td className="num">{pct(p[k].frr)}</td><td className="num">{pct(p[k].genuine_additional_rate)}</td><td className="num">{pct(p[k].worst_bypass_asr)}</td><td className="num">{pct(p[k].worst_omission_asr)}</td></tr>)))}</tbody></table></div>
      {c.fixed_sweep && (
        <>
          <h3>Security versus friction</h3>
          <p className="small muted">Each dot on the line is the fixed policy at a different threshold. The diamonds are the fixed policy with a static two-modality rule and the risk-aware policy (genuine users sent to extra verification count as friction). A better policy sits lower and further left. Neither alternative dominates the other.</p>
          <div className="row"><label htmlFor="ym" style={{ margin: 0 }}>Vertical axis</label>
            <select id="ym" style={{ width: 'auto' }} value={yMetric} onChange={(e) => setYMetric(e.target.value)}>
              <option value="worst_omission_asr">Worst omission attack success</option><option value="worst_bypass_asr">Worst single-modality bypass success</option><option value="far">Zero-effort impostor approved</option></select></div>
          <ResponsiveContainer width="100%" height={280}>
            <ScatterChart margin={{ top: 8, right: 16, left: -4, bottom: 18 }}>
              <CartesianGrid stroke="var(--border)" />
              <XAxis type="number" dataKey="x" name="Genuine not approved" unit="%" stroke="var(--text-3)" label={{ value: 'Genuine users not approved (%)', position: 'insideBottom', offset: -10, fill: 'var(--text-3)', fontSize: 12 }} />
              <YAxis type="number" dataKey="y" name="Attack approved" unit="%" stroke="var(--text-3)" />
              <Tooltip contentStyle={tip} cursor={{ strokeDasharray: '3 3' }} />
              <Legend verticalAlign="top" />
              <Scatter name="Fixed policy, threshold sweep" data={sweep} fill={FIXED} line={{ stroke: FIXED }} shape="circle" />
              <Scatter name="Fixed + min 2 modalities" data={point('fixed_min2')} fill={MIN2} shape="diamond" />
              <Scatter name="Risk-aware policy" data={point('risk_aware')} fill={AWARE} shape="diamond" />
            </ScatterChart>
          </ResponsiveContainer>
        </>
      )}
      <p className="faint small">Zero-effort impostor: all modalities are impostor samples. Bypass: the attacker defeats one modality (genuine-like score) and is an impostor on the others. Omission: the attacker defeats one modality and submits only that one. For attacks, "asked for more" stops the attack here, but a real attacker could still try to pass it. Intervals for the headline rows are in the stored run; they use the smallest score pool, not the number of attempts.</p>
    </div>
  )
}

function PolicyDemo() {
  const { data, error, loading } = useApi(api.policyDemo)
  if (loading) return <Loading />
  if (error) return <Alert kind="error">{error.message}</Alert>
  return (
    <>
      <Alert kind="warn"><strong>Illustrative only.</strong> {data.note}</Alert>
      <div className="table-wrap" style={{ marginTop: 12 }}><table>
        <thead><tr><th>Scenario</th><th>Risk</th><th>Calibrated scores</th><th>Fixed</th><th>Risk-aware</th></tr></thead>
        <tbody>{data.scenarios.map((s) => (
          <tr key={s.name}><td>{s.name}</td><td style={{ textTransform: 'capitalize' }}>{s.risk_category}</td>
            <td className="small mono">{Object.entries(s.inputs).map(([k, v]) => `${k[0].toUpperCase()}:${v == null ? '–' : v}`).join(' ')}</td>
            <td><DecisionBadge decision={s.fixed.decision} /></td><td><DecisionBadge decision={s.risk_aware.decision} /></td></tr>))}</tbody></table></div>
    </>
  )
}

function PolicyConfig() {
  const { data, error, loading } = useApi(api.policy)
  if (loading) return <Loading />
  if (error) return <Alert kind="error">{error.message}</Alert>
  const b = data.fusion.bands
  return (
    <div className="stack">
      <p className="small muted">Active policy for real transactions: <strong>{data.active_policy}</strong>. Fixed threshold: {data.fusion.fixed_threshold}. Attempt limit: {data.max_auth_attempts}. These are experimental settings, changeable through the policy file (see docs).</p>
      <div className="table-wrap"><table>
        <thead><tr><th>Risk</th><th className="num">Approve at</th><th className="num">Reject below</th><th className="num">Min modalities</th><th className="num">Min coverage</th><th className="num">Conflict floor</th></tr></thead>
        <tbody>{Object.entries(b).map(([k, v]) => (
          <tr key={k}><td style={{ textTransform: 'capitalize' }}>{k}</td><td className="num">{v.approve}</td><td className="num">{v.reject}</td><td className="num">{v.min_modalities}</td><td className="num">{v.min_coverage}</td><td className="num">{v.conflict_floor}</td></tr>))}</tbody></table></div>
    </div>
  )
}

export default function Analytics() {
  const { data: runs, error, loading } = useApi(api.evaluationRuns)
  if (loading) return <Loading />
  if (error) return <Alert kind="error">{error.message}</Alert>
  const fusion = runs.filter((r) => r.kind === 'fusion')
  return (
    <div className="stack">
      <PageHead title="Biometric analytics">Measured results come from evaluation runs saved by the CLI. Nothing on this page is generated by the browser.</PageHead>
      <div className="card"><h2>Individual biometric performance</h2><ModalityTable runs={runs} /></div>
      <div className="card"><h2>Degraded input conditions (single modality)</h2><DegradedTable runs={runs} /></div>
      <div className="card"><h2>Fixed-threshold vs risk-aware fusion (measured on stored scores)</h2>
        {fusion.length === 0 ? <Empty icon={Inbox} title="No fusion evaluation has been run">Needs stored scores for at least one modality. See docs/EVALUATION.md.</Empty> : <FusionSection run={fusion[0]} />}
      </div>
      <div className="card"><h2>Decision rules in force</h2><PolicyConfig /></div>
      <div className="card"><h2><FlaskConical size={16} style={{ verticalAlign: -2 }} /> Policy behaviour demo</h2><PolicyDemo /></div>
    </div>
  )
}
