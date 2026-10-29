import { createContext, useCallback, useContext, useState } from 'react'
import { CheckCircle2, Info, X, XCircle } from 'lucide-react'

const Ctx = createContext(() => {})
export const useToast = () => useContext(Ctx)

export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const dismiss = useCallback((id) => setItems((xs) => xs.filter((x) => x.id !== id)), [])
  const push = useCallback((text, kind = 'ok', ms = 5000) => {
    const id = Math.random().toString(36).slice(2)
    setItems((xs) => [...xs.slice(-3), { id, text, kind }])
    if (ms) setTimeout(() => dismiss(id), ms)
  }, [dismiss])
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((t) => {
          const Icon = t.kind === 'error' ? XCircle : t.kind === 'info' ? Info : CheckCircle2
          return <div className={`toast ${t.kind}`} key={t.id} role="status"><Icon size={16} /><span>{t.text}</span><button aria-label="Dismiss" onClick={() => dismiss(t.id)}><X size={14} /></button></div>
        })}
      </div>
    </Ctx.Provider>
  )
}
