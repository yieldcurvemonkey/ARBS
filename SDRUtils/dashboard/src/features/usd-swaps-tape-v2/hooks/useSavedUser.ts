import { useEffect, useState } from 'react'

const KEY = 'swappulse_user'

export function useSavedUser(): [string, (next: string) => void] {
  const [user, setUser] = useState<string>('')
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(KEY)
      if (saved) setUser(saved)
    } catch {
      /* ignore */
    }
  }, [])
  const persist = (next: string) => {
    setUser(next)
    try {
      window.localStorage.setItem(KEY, next)
    } catch {
      /* ignore */
    }
  }
  return [user, persist]
}
