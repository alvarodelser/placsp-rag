import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import {
  authMe, authLogin, authRegister, authLogout, authRefresh,
  getSavedIds, saveItem as apiSave, unsaveItem as apiUnsave,
} from './api.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  // undefined = still checking cookie; null = not logged in; object = logged in
  const [user, setUser] = useState(undefined)
  const [savedIds, setSavedIds] = useState(new Set())

  // On mount: check if already logged in via cookie.
  useEffect(() => {
    authMe()
      .then((u) => {
        setUser(u)
        return getSavedIds()
      })
      .then((data) => setSavedIds(new Set(data.ids || [])))
      .catch(() => {
        // Try refreshing the access token
        authRefresh()
          .then((ok) => {
            if (!ok) { setUser(null); return }
            return authMe()
              .then((u) => { setUser(u); return getSavedIds() })
              .then((data) => setSavedIds(new Set(data.ids || [])))
          })
          .catch(() => setUser(null))
      })
  }, [])

  const login = useCallback(async (email, password) => {
    const u = await authLogin(email, password)
    setUser(u)
    try {
      const data = await getSavedIds()
      setSavedIds(new Set(data.ids || []))
    } catch { /* fresh user, no saves */ }
    return u
  }, [])

  const register = useCallback(async ({ email, password, display_name }) => {
    const u = await authRegister({ email, password, display_name })
    setUser(u)
    setSavedIds(new Set())
    return u
  }, [])

  const logout = useCallback(async () => {
    try { await authLogout() } catch { /* best-effort */ }
    setUser(null)
    setSavedIds(new Set())
  }, [])

  const toggleSave = useCallback(async (item) => {
    const id = item._id || item.syndication_id
    if (!id) return
    const wasSaved = savedIds.has(id)

    // Optimistic UI update
    setSavedIds((prev) => {
      const next = new Set(prev)
      wasSaved ? next.delete(id) : next.add(id)
      return next
    })

    try {
      if (wasSaved) {
        await apiUnsave(id)
      } else {
        await apiSave({
          item_id: id,
          syndication_id: item.syndication_id || null,
          title: item.title || null,
        })
      }
    } catch {
      // Revert on error
      setSavedIds((prev) => {
        const next = new Set(prev)
        wasSaved ? next.add(id) : next.delete(id)
        return next
      })
    }
  }, [savedIds])

  return (
    <AuthContext.Provider value={{ user, savedIds, login, register, logout, toggleSave }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (ctx === null) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
