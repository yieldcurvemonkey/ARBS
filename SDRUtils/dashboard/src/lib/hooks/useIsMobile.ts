'use client'

import { useEffect, useState } from 'react'

const MOBILE_UA =
  /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i

// Tablets in landscape (≥1024px) get desktop mode. Phones in landscape
// (typically ≤844px) still get mobile. Portrait tablets (<1024px) get mobile.
const MOBILE_VIEWPORT_THRESHOLD = 1024

function detectMobile(): boolean {
  if (typeof window === 'undefined') return false
  return (
    MOBILE_UA.test(navigator.userAgent) &&
    window.innerWidth < MOBILE_VIEWPORT_THRESHOLD
  )
}

/**
 * Returns true on mobile devices with viewport width < 1024px.
 * SSR-safe: returns false on server, hydrates on mount.
 */
export function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(false)

  useEffect(() => {
    setMobile(detectMobile())
    const handler = () => setMobile(detectMobile())
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [])

  return mobile
}
