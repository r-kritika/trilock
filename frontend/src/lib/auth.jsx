import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api, getToken, setToken } from '../api/client'

const Ctx = createContext(null)
export const useAuth = () => useContext(Ctx)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(!!getToken())
  // set after the password step when the face and voice step is still needed: { token, challenge, name, livenessRequired }
  const [pending, setPending] = useState(null)

  const refresh = useCallback(async () => {
    try { setUser(await api.me()) } catch { setToken(null); setUser(null) }
  }, [])

  useEffect(() => {
    if (getToken()) refresh().finally(() => setLoading(false))
    const onUnauthorized = () => { setToken(null); setUser(null) }
    window.addEventListener('trilock:unauthorized', onUnauthorized)
    return () => window.removeEventListener('trilock:unauthorized', onUnauthorized)
  }, [refresh])

  const adopt = async (r) => { setToken(r.token); setPending(null); await refresh() }

  // password step. Resolves to 'ok', 'enrollment_required' or 'biometric_required'
  const login = async (email, password) => {
    const r = await api.login({ email, password })
    if (r.status === 'biometric_required') {
      setPending({ token: r.preauth_token, challenge: r.challenge, name: r.name, livenessRequired: r.liveness_required })
      return r.status
    }
    await adopt(r)
    return r.status
  }
  // face and voice step; throws ApiError (with .details) if they could not both be confirmed
  const completeBiometric = async (frames, voice) => {
    const r = await api.loginBiometric(pending.token, pending.challenge.challenge_id, frames, voice)
    await adopt(r)
  }
  const newChallenge = async () => {
    const challenge = await api.loginChallenge(pending.token)
    setPending((p) => ({ ...p, challenge }))
    return challenge
  }
  const cancelPending = () => setPending(null)
  const register = async (full_name, email, password) => {
    await api.register({ full_name, email, password })
    return login(email, password)
  }
  const logout = async () => {
    try { await api.logout() } catch { /* already expired */ }
    setToken(null)
    setUser(null)
  }

  return <Ctx.Provider value={{ user, loading, pending, login, register, logout, refresh, completeBiometric, newChallenge, cancelPending }}>{children}</Ctx.Provider>
}
