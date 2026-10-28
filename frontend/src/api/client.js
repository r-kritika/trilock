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

async function request(path, options = {}) {
  let res
  try {
    const token = getToken()
    const headers = { ...(options.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) }
    res = await fetch(`/api${path}`, { ...options, headers })
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

export const api = {
  health: () => request('/health'),
  dashboard: () => request('/dashboard/stats'),
  policy: () => request('/policy'),
  register: (data) => request('/auth/register', json('POST', data)),
  login: (data) => request('/auth/login', json('POST', data)),
  logout: () => request('/auth/logout', { method: 'POST' }),
  me: () => request('/auth/me'),
  users: () => request('/users'),
  // changing biometric references needs the account password again
  enroll: (userId, modality, files, password) =>
    request(`/users/${userId}/enrollments/${modality}`, form([...files.map((f) => ['files', f]), ['password', password]])),
  removeEnrollment: (userId, modality, password) =>
    request(`/users/${userId}/enrollments/${modality}`, { method: 'DELETE', body: form([['password', password]]).body }),
  deleteAccount: (userId, password) =>
    request(`/users/${userId}`, { method: 'DELETE', body: form([['password', password]]).body }),
  riskPreview: (data) => request('/risk/assess', json('POST', data)),
  createTransaction: (data) => request('/transactions', json('POST', data)),
  authenticate: (id, samples) => request(`/transactions/${id}/authenticate`, form(Object.entries(samples))),
  transaction: (id) => request(`/transactions/${id}`),
  transactions: (params) => request(`/transactions?${new URLSearchParams(params)}`),
  evaluationRuns: () => request('/evaluation/runs'),
  policyDemo: () => request('/evaluation/policy-demo'),
}
