import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api, getToken, setToken } from '../api/client'

const Ctx = createContext(null)
export const useAuth = () => useContext(Ctx)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(!!getToken())

  const refresh = useCallback(async () => {
    try { setUser(await api.me()) } catch { setToken(null); setUser(null) }
  }, [])

  useEffect(() => {
    if (getToken()) refresh().finally(() => setLoading(false))
    const onUnauthorized = () => { setToken(null); setUser(null) }
    window.addEventListener('trilock:unauthorized', onUnauthorized)
    return () => window.removeEventListener('trilock:unauthorized', onUnauthorized)
  }, [refresh])

  const login = async (email, password) => {
    const r = await api.login({ email, password })
    setToken(r.token)
    setUser(r.user)
  }
  const register = async (full_name, email, password) => {
    await api.register({ full_name, email, password })
    await login(email, password)
  }
  const logout = async () => {
    try { await api.logout() } catch { /* already expired */ }
    setToken(null)
    setUser(null)
  }

  return <Ctx.Provider value={{ user, loading, login, register, logout, refresh }}>{children}</Ctx.Provider>
}
