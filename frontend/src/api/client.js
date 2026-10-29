// All HTTP calls live here so components never build URLs or parse errors themselves.
export class ApiError extends Error {
  constructor(status, code, message, fields) {
    super(message)
    this.status = status
    this.code = code
    this.fields = fields
  }
}

// The session token lives in sessionStorage (cleared when the tab closes). It is never put in a URL.
const TOKEN_KEY = 'trilock_token'
export const getToken = () => { try { return sessionStorage.getItem(TOKEN_KEY) } catch { return null } }
export const setToken = (t) => {
  try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY) } catch { /* storage blocked */ }
}

// A random id this browser keeps (localStorage). The server stores only its hash and uses it to tell the
// owner's known browser apart from strangers, so an attacker's failed attempts cannot lock the owner out.
function deviceId() {
  try {
    let id = localStorage.getItem('trilock_device')
    if (!id) {
      id = (crypto.randomUUID?.() || `${Date.now()}${Math.random()}`).replace(/[^A-Za-z0-9_-]/g, '') + Math.random().toString(36).slice(2, 10)
      localStorage.setItem('trilock_device', id)
    }
    return id
  } catch { return null }
}

async function request(path, options = {}) {
  let res
  try {
    const token = options.token || getToken()
    const dev = deviceId()
    const headers = { ...(options.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(dev ? { 'X-Device-Id': dev } : {}) }
    const { token: _t, ...fetchOptions } = options
    res = await fetch(`/api${path}`, { ...fetchOptions, headers })
  } catch {
    throw new ApiError(0, 'network', 'Cannot reach the TriLock backend. Is it running on port 8000?')
  }
  let body = null
  try { body = res.status === 204 ? null : await res.json() } catch { /* non-JSON error page */ }
  if (!res.ok) {
    if (res.status === 401 && path !== '/auth/login') window.dispatchEvent(new Event('trilock:unauthorized'))
    const e = body?.error
    throw new ApiError(res.status, e?.code || 'http_error', e?.message || `Request failed (${res.status})`, e?.fields)
  }
  return body
}

const json = (method, data) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
})

function form(entries) {
  const fd = new FormData()
  for (const [k, v] of entries) {
    if (v == null) continue
    if (v instanceof Blob) fd.append(k, v, v.name || `${k}.bin`)
    else fd.append(k, v)
  }
  return { method: 'POST', body: fd }
}

const proofEntries = (proofs) => Object.entries(proofs).filter(([, v]) => v).map(([k, v]) => [`proof_${k}`, v])

export const api = {
  health: () => request('/health'),
  dashboard: () => request('/dashboard/stats'),
  policy: () => request('/policy'),
  register: (data) => request('/auth/register', json('POST', data)),
  login: (data) => request('/auth/login', json('POST', data)),
  // second sign-in step; `token` is the short-lived pre-auth token from the password step
  loginChallenge: (token) => request('/auth/login/challenge', { method: 'POST', token }),
  loginBiometric: (token, challengeId, frames, voice) => request('/auth/login/biometric', {
    method: 'POST', token,
    body: form([['challenge_id', challengeId], ...frames.map((f) => ['face_frames', f]), ['voice', voice]]).body,
  }),
  requestRecoveryWith: (token, reason, password) => request('/recovery', { method: 'POST', token, body: form([['reason', reason], ['password', password]]).body }),
  logout: () => request('/auth/logout', { method: 'POST' }),
  me: () => request('/auth/me'),
  users: () => request('/users'),
  // Changing biometrics needs the password and, if some are already enrolled, matching proof samples
  // ({ face: Blob, voice: Blob, fingerprint: Blob }) from those enrolled modalities.
  enroll: (userId, modality, files, password, proofs = {}) =>
    request(`/users/${userId}/enrollments/${modality}`, form([...files.map((f) => ['files', f]), ['password', password], ...proofEntries(proofs)])),
  removeEnrollment: (userId, modality, password, proofs = {}) =>
    request(`/users/${userId}/enrollments/${modality}`, { method: 'DELETE', body: form([['password', password], ...proofEntries(proofs)]).body }),
  deleteAccount: (userId, password, proofs = {}) =>
    request(`/users/${userId}`, { method: 'DELETE', body: form([['password', password], ...proofEntries(proofs)]).body }),
  riskPreview: (data) => request('/risk/assess', json('POST', data)),
  createTransaction: (data) => request('/transactions', json('POST', data)),
  // live = { challengeId, faceFrames: Blob[] } when a liveness challenge is being answered
  authenticate: (id, samples, live = null) => request(`/transactions/${id}/authenticate`, form([
    ...Object.entries(samples),
    ...(live?.challengeId ? [['challenge_id', live.challengeId]] : []),
    ...((live?.faceFrames || []).map((f) => ['face_frames', f])),
  ])),
  livenessChallenge: () => request('/liveness/challenge', { method: 'POST' }),
  requestRecovery: (reason, password) => request('/recovery', { method: 'POST', body: form([['reason', reason], ['password', password]]).body }),
  myRecovery: () => request('/recovery/mine'),
  cancelRecovery: (id, password) => request(`/recovery/${id}/cancel`, { method: 'POST', body: form([['password', password]]).body }),
  recoveryQueue: (status = 'pending') => request(`/recovery?status=${status}`),
  approveRecovery: (id, note) => request(`/recovery/${id}/approve`, { method: 'POST', body: form([['note', note || '']]).body }),
  denyRecovery: (id, note) => request(`/recovery/${id}/deny`, { method: 'POST', body: form([['note', note || '']]).body }),
  transaction: (id) => request(`/transactions/${id}`),
  transactions: (params) => request(`/transactions?${new URLSearchParams(params)}`),
  evaluationRuns: () => request('/evaluation/runs'),
  policyDemo: () => request('/evaluation/policy-demo'),
  riskDemo: () => request('/evaluation/risk-demo'),
}
