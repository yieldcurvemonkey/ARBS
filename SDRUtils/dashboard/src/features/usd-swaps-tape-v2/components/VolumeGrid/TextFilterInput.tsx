'use client'
import { useCallback, useEffect, useRef, useState, type JSX } from 'react'

export interface TextFilterInputProps {
  value: string
  onChange: (value: string) => void
  debounceMs?: number
}

export function TextFilterInput({ value, onChange, debounceMs = 300 }: TextFilterInputProps): JSX.Element {
  const [local, setLocal] = useState(value)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => { setLocal(value) }, [value])

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const next = e.target.value
    setLocal(next)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => onChange(next), debounceMs)
  }, [onChange, debounceMs])

  const handleClear = useCallback(() => {
    setLocal('')
    onChange('')
    if (timerRef.current) clearTimeout(timerRef.current)
  }, [onChange])

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  return (
    <div className="relative flex items-center">
      <input
        type="text"
        value={local}
        onChange={handleChange}
        placeholder="filter trades..."
        className="w-28 rounded border border-slate-700 bg-slate-900 px-2 py-[2px] pr-6 font-mono text-[10.5px] text-slate-200 placeholder:text-slate-600 hover:bg-slate-800 focus:border-indigo-500/50 focus:outline-none"
      />
      {value && (
        <button
          type="button"
          aria-label="Clear filter"
          onClick={handleClear}
          className="absolute right-1 font-mono text-[10px] text-slate-500 hover:text-slate-300"
        >
          ×
        </button>
      )}
    </div>
  )
}
