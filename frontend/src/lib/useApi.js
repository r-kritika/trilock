import { useCallback, useEffect, useState } from 'react'

// Tiny data-loading hook: { data, error, loading, reload }.
export function useApi(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true }))
    try {
      setState({ data: await fn(), error: null, loading: false })
    } catch (e) {
      setState({ data: null, error: e, loading: false })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { load() }, [load])
  return { ...state, reload: load }
}
