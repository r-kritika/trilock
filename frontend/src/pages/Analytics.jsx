import { useState } from 'react'
import { FlaskConical, Inbox } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api/client'
import { useApi } from '../lib/useApi'
import {
  Alert, Card, DataBadge, DecisionBadge, Disclosure, Empty, ErrorState, MODALITY, Meter, PageHead, PageSkeleton, Tabs, num, pct, when,
} from '../components/ui'

const tip = { background: 'var(--surface-3)', border: '1px solid var(--border-strong)', borderRadius: 8, color: 'var(--text)', fontSize: 12 }
const axis = { fill: 'var(--text-3)', fontSize: 11 }
const POLS = [['fixed', 'Fixed threshold', '#6fa8ff'], ['fixed_min2', 'Fixed + min 2 modalities', '#8ea0b6'], ['risk_aware', 'Risk-aware', '#e5a23c']]
const sourceKind = (run) => (run.is_synthetic ? 'synthetic' : 'real')

// first (= newest) run per modality and data kind
function modalityRuns(runs) {
  const seen = new Set()
  return runs.filter((r) => {
    const k = r.kind === 'modality' && `${r.metrics.modality}-${r.is_synthetic}`
    if (!k || seen.has(k)) return false
    seen.add(k)
    return true
  }).sort((a, b) => ['face', 'voice', 'fingerprint'].indexOf(a.metrics.modality) - ['face', 'voice', 'fingerprint'].indexOf(b.metrics.modality))
}
const ci = (c) => (c && c[0] != null ? `${pct(c[0])} to ${pct(c[1])}` : '–')
const ms = (o) => (o?.mean == null ? '–' : `${pct(o.mean, 2)} ± ${pct(o.sd, 2)}`)

// A rate with its 95% confidence interval drawn on a 0..max scale
function RangeBar({ value, interval, max }) {
  if (value == null) return <span className="faint">–</span>
  const m = max || Math.max(interval?.[1] ?? 0, value, 0.02) * 1.15
  const left = interval?.[0] != null ? (interval[0] / m) * 100 : null
  const width = interval?.[0] != null ? ((interval[1] - interval[0]) / m) * 100 : 0
  return (
    <div style={{ minWidth: 120 }}>
      <div style={{ position: 'relative', height: 8, background: 'var(--surface-3)', borderRadius: 999 }} role="img" aria-label={`${pct(value)} with interval ${ci(interval)}`}>
        {left != null && <span style={{ position: 'absolute', left: `${left}%`, width: `${Math.max(width, 1)}%`, top: 2, bottom: 2, background: 'rgba(91,157,255,.35)', borderRadius: 999 }} />}
        <span style={{ position: 'absolute', left: `calc(${(value / m) * 100}% - 3px)`, top: -2, width: 6, height: 12, background: 'var(--accent)', borderRadius: 2 }} />
      </div>
    </div>
  )
}

function Legend3() {
  return (
    <div className="card">
      <div className="grid g3" style={{ gap: 18 }}>
        {[['real', 'Real dataset', 'Photos and recordings of real people from public datasets (LFW faces, LibriSpeech voices). Still easier than a phone camera in a dim room.'],
          ['synthetic', 'Synthetic data', 'Generated data. The fingerprint results use generated prints, not real fingerprints, so they say nothing about real-world fingerprint accuracy.'],
          ['simulated', 'Simulated', 'Attempts and attacks built from the measured scores (and, for liveness, from still photos). They compare policies; they are not real-world accuracy.']]
          .map(([k, t, d]) => <div key={k}><div className="row" style={{ gap: 8, marginBottom: 6 }}><DataBadge kind={k} /></div><div className="small muted">{d}</div></div>)}
      </div>
    </div>
  )
}

function Reproducibility({ m }) {
  const r = m.reproducibility
  if (!r) return null
  return (
    <Disclosure title="Reproducibility">
      <dl className="kv small">
        <dt>Seed</dt><dd>{r.seed}</dd>
        {r.manifest_sha256_16 && <><dt>Trial list hash</dt><dd className="mono">{r.manifest_sha256_16}</dd></>}
        {r.data_source && <><dt>Data</dt><dd className="mono">{r.data_source}</dd></>}
        <dt>Command</dt><dd className="mono" style={{ fontSize: '.78rem' }}>{r.command}</dd>
        {r.versions && <><dt>Libraries</dt><dd className="mono" style={{ fontSize: '.78rem' }}>{Object.entries(r.versions).map(([k, v]) => `${k} ${v}`).join(' · ')}</dd></>}
      </dl>
    </Disclosure>
  )
}

// ------------------------------------------------------------------ tabs
function Overview({ runs }) {
  const mods = modalityRuns(runs)
  if (!mods.length) return <Empty icon={Inbox} title="No biometric evaluation has been run">Run <code>python -m app.evaluation.run_modality</code> (see docs/EVALUATION.md).</Empty>
  const chart = mods.map((r) => ({ name: `${MODALITY[r.metrics.modality].label}${r.is_synthetic ? ' (synthetic)' : ''}`, eer: +(r.metrics.eer * 100).toFixed(2), synthetic: r.is_synthetic }))
  return (
    <div className="stack">
      <Legend3 />
      <div className="grid g3">
        {mods.map((r) => {
          const m = r.metrics
          const M = MODALITY[m.modality]
          return (
            <div className="card stack-sm" key={r.id}>
              <div className="row between"><span className="row" style={{ gap: 8 }}><M.icon size={17} style={{ color: 'var(--text-3)' }} /><h2>{M.label}</h2></span><DataBadge kind={sourceKind(r)} /></div>
              <div className="row" style={{ alignItems: 'baseline', gap: 8 }}><span className="stat-value">{pct(m.eer, 2)}</span><span className="muted small">equal error rate</span></div>
              <dl className="kv small">
                <dt>FAR</dt><dd>{pct(m.far, 2)} <span className="faint">({ci(m.far_ci)})</span></dd>
                <dt>FRR</dt><dd>{pct(m.frr, 2)} <span className="faint">({ci(m.frr_ci)})</span></dd>
                <dt>Trials</dt><dd>{m.genuine_trials} genuine · {m.impostor_trials} impostor</dd>
                <dt>Latency</dt><dd>{m.latency_ms_mean} ms mean</dd>
              </dl>
            </div>
          )
        })}
      </div>
      <Card title="Equal error rate by module" subtitle="Lower is better. EER is the point where false accepts equal false rejects. Synthetic bars are not real-world results.">
        <ResponsiveContainer width="100%" height={Math.max(150, chart.length * 54)}>
          <BarChart data={chart} layout="vertical" margin={{ top: 4, right: 24, left: 10, bottom: 0 }}>
            <CartesianGrid horizontal={false} stroke="var(--border)" />
            <XAxis type="number" unit="%" tick={axis} tickLine={false} axisLine={false} />
            <YAxis type="category" dataKey="name" tick={{ ...axis, fontSize: 12 }} tickLine={false} axisLine={false} width={150} />
            <Tooltip cursor={{ fill: 'var(--surface-2)' }} contentStyle={tip} formatter={(v) => `${v}%`} />
            <Bar dataKey="eer" name="EER" radius={[0, 4, 4, 0]} maxBarSize={22}>{chart.map((c) => <Cell key={c.name} fill={c.synthetic ? 'var(--warn)' : 'var(--accent)'} fillOpacity={c.synthetic ? 0.55 : 1} />)}</Bar>
          </BarChart>
        </ResponsiveContainer>
      </Card>
    </div>
  )
}

function Modules({ runs }) {
  const mods = modalityRuns(runs)
  if (!mods.length) return <Empty icon={Inbox} title="No biometric evaluation has been run">Run <code>python -m app.evaluation.run_modality</code> (see docs/EVALUATION.md).</Empty>
  const maxRate = Math.max(...mods.flatMap((r) => [r.metrics.far_ci?.[1] ?? 0, r.metrics.frr_ci?.[1] ?? 0]), 0.03) * 1.1
  return (
    <div className="stack">
      <Card flush title="Module comparison" subtitle="Primary split. The thresholds were fitted on a separate half of the subjects, so no calibration identity appears in the evaluation set." className="">
        <div className="table-wrap" style={{ padding: '0 20px 8px' }}><table>
          <thead><tr><th>Module</th><th>Data</th><th className="num">Genuine / impostor</th><th className="num">EER</th><th>FAR (95% CI)</th><th>FRR (95% CI)</th><th className="num">Not evaluable</th><th className="num">Latency mean / p95</th></tr></thead>
          <tbody>{mods.map((r) => {
            const m = r.metrics
            return (
              <tr key={r.id}>
                <td><strong>{MODALITY[m.modality].label}</strong></td><td><DataBadge kind={sourceKind(r)} /></td>
                <td className="num">{m.genuine_trials} / {m.impostor_trials}</td><td className="num"><strong>{pct(m.eer, 2)}</strong></td>
                <td><div className="num" style={{ textAlign: 'left' }}>{pct(m.far, 2)}</div><RangeBar value={m.far} interval={m.far_ci} max={maxRate} /></td>
                <td><div className="num" style={{ textAlign: 'left' }}>{pct(m.frr, 2)}</div><RangeBar value={m.frr} interval={m.frr_ci} max={maxRate} /></td>
                <td className="num">{pct(m.not_evaluable_rate)}</td><td className="num">{m.latency_ms_mean} / {m.latency_ms_p95} ms</td>
              </tr>)
          })}</tbody></table></div>
        <p className="xs faint" style={{ margin: 0, padding: '0 20px 16px' }}>Bars show the rate on a shared scale; the shaded band is the 95% Wilson interval, which assumes independent trials and is therefore optimistic. FAR = impostors accepted, FRR = genuine users not accepted. Inputs a module could not evaluate are counted separately, never as errors or matches.</p>
      </Card>

      <div className="grid g3">
        {mods.map((r) => {
          const m = r.metrics
          const s = m.splits
          return (
            <Card key={r.id} title={MODALITY[m.modality].label} actions={<DataBadge kind={sourceKind(r)} />}>
              <dl className="kv small">
                <dt>Subjects</dt><dd>{m.subjects} enrolled · {m.evaluation_subjects} in the evaluation half{m.enrollment_failures ? ` · ${m.enrollment_failures} failed to enroll` : ''}</dd>
                <dt>Threshold</dt><dd>{num(m.threshold, 3)} <span className="faint">fitted on the other half</span></dd>
                {s && <><dt>Over {s.count} splits</dt><dd>FAR {ms(s.far)}<br />FRR {ms(s.frr)}<br />EER {ms(s.eer)}</dd></>}
                {m.cross_group_genuine_share != null && <><dt>Cross-session</dt><dd>{pct(m.cross_group_genuine_share, 0)} of genuine probes</dd></>}
              </dl>
              <div style={{ marginTop: 12 }}><Reproducibility m={m} /></div>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

function Robustness({ runs }) {
  const mods = modalityRuns(runs).filter((r) => r.metrics.degraded?.length)
  if (!mods.length) return <Empty icon={Inbox} title="No degraded-input measurements stored">Run the modality evaluation to produce them.</Empty>
  return (
    <div className="stack">
      <Alert kind="info">Each module re-scores the same evaluation trials after the input is degraded (blur, darkness, low resolution, noise, occlusion, truncation). When quality is too low the module <strong>refuses to guess</strong> and reports "not evaluable". That is the safe behaviour, and it is why some rows show 100% not evaluable and no error rates.</Alert>
      {mods.map((r) => (
        <Card key={r.id} flush title={MODALITY[r.metrics.modality].label} actions={<DataBadge kind={sourceKind(r)} />}>
          <div className="table-wrap" style={{ padding: '0 20px 12px' }}><table>
            <thead><tr><th>Condition</th><th className="num">Trials</th><th className="num">FAR</th><th className="num">FRR</th><th style={{ minWidth: 190 }}>Could not be evaluated</th></tr></thead>
            <tbody>{r.metrics.degraded.map((d) => (
              <tr key={d.condition}><td>{d.condition}</td><td className="num">{d.trials}</td><td className="num">{pct(d.far, 1)}</td><td className="num">{pct(d.frr, 1)}</td>
                <td><div className="row" style={{ gap: 8, flexWrap: 'nowrap' }}><div style={{ flex: 1 }}><Meter value={d.not_evaluable_rate} tone={d.not_evaluable_rate > 0.5 ? 'warn' : ''} /></div><span className="num small" style={{ width: 52, textAlign: 'right' }}>{pct(d.not_evaluable_rate, 0)}</span></div></td></tr>))}</tbody></table></div>
        </Card>
      ))}
    </div>
  )
}

function Fusion({ runs }) {
  const run = runs.find((r) => r.kind === 'fusion')
  const [cond, setCond] = useState(0)
  const [yMetric, setYMetric] = useState('worst_omission_asr')
  if (!run) return <Empty icon={Inbox} title="No fusion evaluation has been run">Needs stored scores for at least one modality. See docs/EVALUATION.md.</Empty>
  const m = run.metrics
  const c = m.conditions[Math.min(cond, m.conditions.length - 1)]
  const o = c.overall
  const METRICS = [['far', 'Impostor approved (zero effort)'], ['worst_bypass_asr', 'Worst single-modality bypass'], ['worst_omission_asr', 'Worst omission attack'], ['genuine_additional_rate', 'Genuine users asked for more']]
  const chart = METRICS.map(([k, label]) => ({ metric: label, ...Object.fromEntries(POLS.map(([p, n]) => [n, +((o[p][k] ?? 0) * 100).toFixed(2)])) }))
  const sweep = (c.fixed_sweep || []).map((p) => ({ x: +(p.genuine_not_approved * 100).toFixed(2), y: +(((yMetric === 'far' ? p.far : yMetric === 'worst_bypass_asr' ? p.worst_bypass_asr : p.worst_omission_asr) ?? 0) * 100).toFixed(2), t: p.threshold }))
  const point = (p) => [{ x: +(((o[p].frr ?? 0) + (o[p].genuine_additional_rate ?? 0)) * 100).toFixed(2), y: +((o[p][yMetric] ?? 0) * 100).toFixed(2) }]
  return (
    <div className="stack">
      <div className="row"><DataBadge kind="simulated" />{run.is_synthetic && <DataBadge kind="synthetic" />}<span className="small muted">{m.attempts_per_cell} attempts per scenario and risk level · {m.repeats} repeats · smallest score pool {c.pool_size_min} trials · {when(run.created_at)}</span></div>
      <Alert kind="warn">These are <strong>simulated attempts built from measured scores</strong>: genuine and impostor trials from different datasets are combined into virtual users, the risk mix is assumed ({Object.entries(m.risk_mix).map(([k, v]) => `${k} ${v * 100}%`).join(', ')}), and {run.is_synthetic ? 'the fingerprint scores come from synthetic prints' : 'attacks are simulated by substituting scores'}. It compares how the policies behave. It is not evidence of real-world accuracy, and an "asked for more" outcome is counted as stopping an attack although a real attacker could still try to pass it.</Alert>
      <div className="row"><label htmlFor="cond" style={{ margin: 0 }}>Input condition</label>
        <select id="cond" style={{ width: 'auto', minWidth: 240 }} value={cond} onChange={(e) => setCond(+e.target.value)}>{m.conditions.map((x, i) => <option key={x.name} value={i}>{x.name}</option>)}</select></div>

      <div className="grid g3">
        {POLS.map(([p, label, color]) => (
          <div className="card stack-sm" key={p} style={{ borderTop: `2px solid ${color}` }}>
            <h2>{label}</h2>
            <dl className="kv small">
              <dt>Impostor approved</dt><dd>{pct(o[p].far, 2)} <span className="faint">({ci(o[p].far_ci)})</span></dd>
              <dt>Genuine rejected</dt><dd>{pct(o[p].frr, 2)}</dd>
              <dt>Asked for more</dt><dd>{pct(o[p].genuine_additional_rate)}</dd>
              <dt>Bypass attack</dt><dd>{pct(o[p].worst_bypass_asr)}</dd>
              <dt>Omission attack</dt><dd>{o[p].worst_omission_asr == null ? 'n/a' : pct(o[p].worst_omission_asr)}</dd>
            </dl>
          </div>
        ))}
      </div>
      <Card title="Security versus friction" subtitle="Lower attack success is safer; lower 'asked for more' is easier for honest users.">
        <ResponsiveContainer width="100%" height={270}>
          <BarChart data={chart} margin={{ top: 6, right: 8, left: -14, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey="metric" tick={axis} tickLine={false} axisLine={false} interval={0} />
            <YAxis unit="%" tick={axis} tickLine={false} axisLine={false} />
            <Tooltip cursor={{ fill: 'var(--surface-2)' }} contentStyle={tip} formatter={(v) => `${v}%`} />
            <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, color: 'var(--text-2)' }} />
            {POLS.map(([p, n, color]) => <Bar key={p} dataKey={n} fill={color} radius={[3, 3, 0, 0]} maxBarSize={30} />)}
          </BarChart>
        </ResponsiveContainer>
        <p className="xs faint" style={{ margin: '8px 0 0' }}>Omission attack: the attacker beats one modality and submits only that one. A policy that averages whatever is present accepts it; the others require more evidence. Risk-aware is a different point on the trade-off, not a free win: it costs more extra verification for honest users than the static two-modality rule when all modalities are present.</p>
      </Card>

      {c.fixed_sweep && (
        <Card title="Fixed threshold sweep" subtitle="Each dot on the line is the fixed policy at another threshold. Diamonds are the other two policies. A better policy sits lower and further left."
          actions={<select aria-label="Vertical axis" style={{ width: 'auto' }} value={yMetric} onChange={(e) => setYMetric(e.target.value)}>
            <option value="worst_omission_asr">Worst omission attack</option><option value="worst_bypass_asr">Worst single-modality bypass</option><option value="far">Zero-effort impostor approved</option></select>}>
          <ResponsiveContainer width="100%" height={280}>
            <ScatterChart margin={{ top: 8, right: 16, left: -4, bottom: 22 }}>
              <CartesianGrid stroke="var(--border)" />
              <XAxis type="number" dataKey="x" name="Genuine not approved" unit="%" tick={axis} tickLine={false} label={{ value: 'Genuine users not approved (%)', position: 'insideBottom', offset: -12, fill: 'var(--text-3)', fontSize: 12 }} />
              <YAxis type="number" dataKey="y" name="Attack approved" unit="%" tick={axis} tickLine={false} />
              <Tooltip contentStyle={tip} cursor={{ strokeDasharray: '3 3' }} />
              <Legend verticalAlign="top" iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, color: 'var(--text-2)' }} />
              <Scatter name="Fixed policy, threshold sweep" data={sweep} fill={POLS[0][2]} line={{ stroke: POLS[0][2] }} shape="circle" />
              <Scatter name="Fixed + min 2 modalities" data={point('fixed_min2')} fill={POLS[1][2]} shape="diamond" />
              <Scatter name="Risk-aware" data={point('risk_aware')} fill={POLS[2][2]} shape="diamond" />
            </ScatterChart>
          </ResponsiveContainer>
        </Card>
      )}

      <Card flush title="By risk level" subtitle={`Condition: ${c.name}`}>
        <div className="table-wrap" style={{ padding: '0 20px 12px' }}><table>
          <thead><tr><th>Risk</th><th>Policy</th><th className="num">FAR</th><th className="num">FRR</th><th className="num">Asked for more</th><th className="num">Bypass</th><th className="num">Omission</th></tr></thead>
          <tbody>{Object.entries(c.by_risk).flatMap(([cat, p]) => POLS.map(([k, name], i) => (
            <tr key={cat + k}><td className="cap">{i === 0 ? cat : ''}</td><td>{name}</td>
              <td className="num">{pct(p[k].far)}</td><td className="num">{pct(p[k].frr)}</td><td className="num">{pct(p[k].genuine_additional_rate)}</td><td className="num">{pct(p[k].worst_bypass_asr)}</td><td className="num">{p[k].worst_omission_asr == null ? '–' : pct(p[k].worst_omission_asr)}</td></tr>)))}</tbody></table></div>
      </Card>
      <Disclosure title="Run details"><dl className="kv small"><dt>Sources</dt><dd>{m.sources.join(' · ')}</dd><dt>Score pools</dt><dd>{Object.entries(m.pool_sizes).map(([k, v]) => `${k}: ${v.genuine} genuine / ${v.impostor} impostor`).join(' · ')}</dd></dl><Reproducibility m={m} /></Disclosure>
    </div>
  )
}

function Rate({ d }) {
  return <span><strong>{pct(d.rate, 1)}</strong> <span className="faint small">{d.k}/{d.n} · {pct(d.ci95[0], 1)} to {pct(d.ci95[1], 1)}</span></span>
}
function Liveness({ runs }) {
  const run = runs.find((r) => r.kind === 'liveness')
  if (!run) return <Empty icon={Inbox} title="No liveness evaluation has been run">Run <code>python -m app.evaluation.run_liveness</code> (see docs/EVALUATION.md).</Empty>
  const { face, voice } = run.metrics
  return (
    <div className="stack">
      <Alert kind="warn"><strong>No spoofing dataset was available</strong>, so none of these numbers is a measurement against real presentation attacks. Face attacks are simulated from still photos; the voice test uses real speech but only checks whether requested words were said. Liveness here stops still photos and pre-recorded audio. It does <strong>not</strong> stop videos of the owner, deepfakes, voice cloning or masks, and the head-turn check has not been run with a real webcam.</Alert>
      {face && (
        <Card title="Face: head-turn challenge" actions={<><DataBadge kind="simulated" /><DataBadge kind="real" /></>} subtitle={`${face.people} real LFW people. Attacks are simulated; thresholds yaw ${face.thresholds.yaw_min}, parallax ${face.thresholds.parallax_min}, tuned on the same kind of data.`}>
          <div className="table-wrap"><table>
            <thead><tr><th>Scenario</th><th>Passed the check</th></tr></thead>
            <tbody>
              <tr><td>Flat photo turned in front of the camera (perspective warp, smooth ramp, 4 angles)</td><td><Rate d={face.flat_photo_tilt_attack_passes} /></td></tr>
              <tr><td>Two real photos of the owner shown one after the other</td><td><Rate d={face.photo_swap_attack_passes} /></td></tr>
              <tr><td>Real-turn proxy: different photos of one person, parallax test only</td><td><Rate d={face.real_turn_proxy_parallax_pass} /></td></tr>
            </tbody></table></div>
          <p className="xs faint" style={{ margin: '10px 0 0' }}>For the first two rows lower is better (the attack should fail); for the last row higher is better. The last row is not a false-reject rate for the whole check, because a smooth real turn cannot be built from stills.</p>
        </Card>
      )}
      {voice && (
        <Card title="Voice: spoken-word challenge" actions={<DataBadge kind="real" />} subtitle={`${voice.utterances} real LibriSpeech utterances from ${voice.speakers} speakers, content check only. Challenge words were taken from each transcript.`}>
          <div className="table-wrap"><table>
            <thead><tr><th>Words required</th><th>Said, clean</th><th>Said, 10 dB noise</th><th>Said, 0 dB noise</th><th>Unrelated recording</th></tr></thead>
            <tbody>{[3, 2].map((n) => (
              <tr key={n}><td><strong>{n} of 3</strong>{n === 2 && <span className="badge b-info" style={{ marginLeft: 8 }}>default</span>}</td>
                {['clean', 'n10', 'n0'].map((k) => <td key={k}><Rate d={voice[`said_words_pass_${n}of3`][k]} /></td>)}
                <td><Rate d={voice[`unrelated_audio_pass_${n}of3`]} /></td></tr>))}</tbody></table></div>
          <p className="xs faint" style={{ margin: '10px 0 0' }}>Requiring all three words rejected about one honest speaker in five on clean audio, so two of three is the default. Chance that unrelated speech contains three random words of the project vocabulary: <Rate d={voice.project_vocabulary_chance_pass_3of3} />.</p>
        </Card>
      )}
      <Reproducibility m={run.metrics} />
    </div>
  )
}

function Rules() {
  const { data: policy, error } = useApi(api.policy)
  const { data: pd } = useApi(api.policyDemo)
  const { data: rd } = useApi(api.riskDemo)
  if (error) return <ErrorState error={error} />
  if (!policy) return <PageSkeleton cards={0} />
  const b = policy.fusion.bands
  const r = policy.risk
  return (
    <div className="stack">
      <Card title="Decision rules in force" subtitle={`Active policy: ${policy.active_policy === 'risk_aware' ? 'risk-aware' : 'fixed threshold'} · fixed threshold ${policy.fusion.fixed_threshold} · ${policy.max_auth_attempts} attempts per payment · liveness from ${policy.liveness_required_from} risk. Experimental starting values, changeable through the policy file.`}>
        <div className="table-wrap"><table>
          <thead><tr><th>Risk</th><th className="num">Approve at</th><th className="num">Reject below</th><th className="num">Min modalities</th><th className="num">Min coverage</th><th className="num">Conflict floor</th><th>Face and voice both</th></tr></thead>
          <tbody>{Object.entries(b).map(([k, v]) => <tr key={k}><td className="cap">{k}</td><td className="num">{v.approve}</td><td className="num">{v.reject}</td><td className="num">{v.min_modalities}</td><td className="num">{v.min_coverage}</td><td className="num">{v.conflict_floor}</td><td>{v.require_core ? <span className="badge b-high">required</span> : <span className="faint">no</span>}</td></tr>)}</tbody></table></div>
      </Card>
      <Card title="Risk score factors" subtitle="Additive and rule-based, out of 100. Not a trained fraud model.">
        <div className="grid g3" style={{ gap: 12 }}>
          {[['New recipient', r.new_recipient_points], ['International', r.international_points], ['New device', r.new_device_points], ['Unusual amount for the user', r.history_points],
            ['Velocity (rapid payments)', Math.max(...r.velocity_points.map((p) => p[1]))], ['24 hour total', r.daily_total_points], ['Unusual or night hour', Math.max(r.usual_hour_points, r.night_points)],
            ['New account', r.new_account_points], ['Dormant account', r.dormant_points], ['Recent biometric change', r.recent_biometric_change_points]]
            .map(([l, p]) => <div className="row between small subcard" key={l} style={{ padding: '8px 12px' }}><span>{l}</span><strong>+{p}</strong></div>)}
        </div>
        <p className="xs faint" style={{ margin: '10px 0 0' }}>The amount contributes 0 to 40 points on a curve. Categories: low below {r.medium_from}, medium from {r.medium_from}, high from {r.high_from}, critical from {r.critical_from}.</p>
      </Card>
      {rd && (
        <Card flush title="Time-aware risk demo" actions={<DataBadge kind="illustrative" />} subtitle="One 1,200 USD payment in different situations, scored by the real engine.">
          <div className="table-wrap" style={{ padding: '0 20px 12px' }}><table>
            <thead><tr><th>Situation</th><th className="num">Score</th><th>Risk</th><th>Why</th></tr></thead>
            <tbody>{rd.scenarios.map((s) => <tr key={s.name}><td>{s.name}</td><td className="num">{Math.round(s.score)}</td><td><span className={`badge b-${s.category}`}>{s.category}</span></td>
              <td className="small muted">{s.factors.filter((f) => f.name !== 'amount').map((f) => `${f.name.replace(/_/g, ' ')} +${f.points}`).join(', ') || 'amount only'}</td></tr>)}</tbody></table></div>
        </Card>
      )}
      {pd && (
        <Card flush title="Policy behaviour demo" actions={<DataBadge kind="illustrative" />} subtitle="Hand-written calibrated scores run through the real fusion code.">
          <div className="table-wrap" style={{ padding: '0 20px 12px' }}><table>
            <thead><tr><th>Scenario</th><th>Risk</th><th>Scores</th><th>Fixed</th><th>Risk-aware</th></tr></thead>
            <tbody>{pd.scenarios.map((s) => <tr key={s.name}><td>{s.name}</td><td className="cap">{s.risk_category}</td>
              <td className="small mono">{Object.entries(s.inputs).map(([k, v]) => `${k[0].toUpperCase()}:${v == null ? '–' : v}`).join(' ')}</td>
              <td><DecisionBadge decision={s.fixed.decision} /></td><td><DecisionBadge decision={s.risk_aware.decision} /></td></tr>)}</tbody></table></div>
        </Card>
      )}
    </div>
  )
}

const TABS = [['overview', 'Overview'], ['modules', 'Biometric modules'], ['robustness', 'Degraded inputs'], ['fusion', 'Fusion policies'], ['liveness', 'Liveness'], ['rules', 'Rules and demos']]

export default function Analytics() {
  const { data: runs, error, loading, reload } = useApi(api.evaluationRuns)
  const [tab, setTab] = useState('overview')
  if (loading && !runs) return <PageSkeleton cards={3} />
  if (error) return <ErrorState error={error} onRetry={reload} />
  return (
    <div className="stack">
      <PageHead title="Biometric analytics" actions={<span className="badge b-neutral"><FlaskConical size={12} />{runs.length} stored evaluation runs</span>}>
        Measured results come from evaluation runs saved by the command line tools. Nothing on this page is generated by the browser, and every figure says what kind of data it comes from.
      </PageHead>
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      {tab === 'overview' && <Overview runs={runs} />}
      {tab === 'modules' && <Modules runs={runs} />}
      {tab === 'robustness' && <Robustness runs={runs} />}
      {tab === 'fusion' && <Fusion runs={runs} />}
      {tab === 'liveness' && <Liveness runs={runs} />}
      {tab === 'rules' && <Rules />}
    </div>
  )
}
