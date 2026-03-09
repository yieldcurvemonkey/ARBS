'use client'

import { useEffect, useMemo, useState } from 'react'
import { BookOpenText, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import {
  VOL_GRID_METHODOLOGY_SECTIONS,
  VOL_GRID_METHODOLOGY_TITLE
} from './volGridMethodologyContent'

export function VolGridMethodologyModal({
  isOpen,
  onClose
}: {
  isOpen: boolean
  onClose: () => void
}) {
  const [activeSectionId, setActiveSectionId] = useState(
    VOL_GRID_METHODOLOGY_SECTIONS[0].id
  )

  useEffect(() => {
    if (!isOpen) return
    setActiveSectionId(VOL_GRID_METHODOLOGY_SECTIONS[0].id)
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  const activeSection = useMemo(
    () =>
      VOL_GRID_METHODOLOGY_SECTIONS.find(
        (section) => section.id === activeSectionId
      ) ?? VOL_GRID_METHODOLOGY_SECTIONS[0],
    [activeSectionId]
  )

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-[70] bg-slate-950/85 p-4 md:p-6"
      onClick={onClose}
    >
      <div
        className="mx-auto flex h-[calc(100vh-2rem)] w-full max-w-[1460px] overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-2xl md:h-[calc(100vh-3rem)]"
        onClick={(event) => event.stopPropagation()}
      >
        <aside className="hidden w-64 shrink-0 border-r border-slate-800 bg-slate-950/60 md:flex md:flex-col">
          <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-300">
            <BookOpenText className="h-4 w-4 text-sky-300" />
            Methodology
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {VOL_GRID_METHODOLOGY_SECTIONS.map((section) => {
              const active = section.id === activeSectionId
              return (
                <button
                  key={section.id}
                  type="button"
                  onClick={() => setActiveSectionId(section.id)}
                  className={`mb-1 w-full rounded border px-3 py-2 text-left text-xs transition ${
                    active
                      ? 'border-sky-400/70 bg-sky-500/15 text-sky-100'
                      : 'border-slate-800 text-slate-300 hover:border-slate-600 hover:bg-slate-800/70'
                  }`}
                >
                  {section.label}
                </button>
              )
            })}
          </div>
        </aside>

        <section className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
            <div className="flex min-w-0 items-center gap-2">
              <BookOpenText className="h-4 w-4 shrink-0 text-sky-300" />
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-slate-100">
                  {VOL_GRID_METHODOLOGY_TITLE}
                </div>
                <div className="truncate text-[11px] text-slate-400">
                  {activeSection.label}
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-slate-700 p-1 text-slate-300 transition hover:border-slate-500 hover:text-slate-100"
              aria-label="Close methodology modal"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 md:px-6 md:py-5">
            <div className="mb-3 flex flex-wrap gap-2 md:hidden">
              {VOL_GRID_METHODOLOGY_SECTIONS.map((section) => {
                const active = section.id === activeSectionId
                return (
                  <button
                    key={section.id}
                    type="button"
                    onClick={() => setActiveSectionId(section.id)}
                    className={`rounded border px-2 py-1 text-[11px] transition ${
                      active
                        ? 'border-sky-400/70 bg-sky-500/15 text-sky-100'
                        : 'border-slate-700 text-slate-300 hover:border-slate-500'
                    }`}
                  >
                    {section.label}
                  </button>
                )
              })}
            </div>

            <div className="vol-grid-methodology-markdown text-slate-200">
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeKatex]}
              >
                {activeSection.markdown}
              </ReactMarkdown>
            </div>
          </div>
        </section>
      </div>

      <style jsx global>{`
        .vol-grid-methodology-markdown h1,
        .vol-grid-methodology-markdown h2,
        .vol-grid-methodology-markdown h3 {
          margin-top: 1.1rem;
          margin-bottom: 0.55rem;
          font-weight: 700;
          color: #f8fafc;
        }
        .vol-grid-methodology-markdown h1 {
          font-size: 1.1rem;
        }
        .vol-grid-methodology-markdown h2 {
          font-size: 0.95rem;
          text-transform: uppercase;
          letter-spacing: 0.03em;
          color: #cbd5e1;
        }
        .vol-grid-methodology-markdown h3 {
          font-size: 0.86rem;
          color: #e2e8f0;
        }
        .vol-grid-methodology-markdown p,
        .vol-grid-methodology-markdown li {
          font-size: 0.8rem;
          line-height: 1.45;
          color: #d1d5db;
        }
        .vol-grid-methodology-markdown ul,
        .vol-grid-methodology-markdown ol {
          margin-top: 0.3rem;
          margin-bottom: 0.5rem;
          padding-left: 1.2rem;
        }
        .vol-grid-methodology-markdown code {
          border: 1px solid rgba(71, 85, 105, 0.8);
          background: rgba(2, 6, 23, 0.55);
          border-radius: 0.25rem;
          padding: 0.1rem 0.3rem;
          font-size: 0.72rem;
          color: #e2e8f0;
        }
        .vol-grid-methodology-markdown pre {
          border: 1px solid rgba(51, 65, 85, 0.9);
          background: rgba(2, 6, 23, 0.9);
          border-radius: 0.5rem;
          padding: 0.75rem;
          overflow-x: auto;
          margin: 0.7rem 0;
        }
        .vol-grid-methodology-markdown pre code {
          border: 0;
          background: transparent;
          padding: 0;
          color: #dbeafe;
          font-size: 0.72rem;
        }
        .vol-grid-methodology-markdown table {
          width: 100%;
          border-collapse: collapse;
          margin: 0.7rem 0;
          font-size: 0.74rem;
        }
        .vol-grid-methodology-markdown th,
        .vol-grid-methodology-markdown td {
          border: 1px solid rgba(51, 65, 85, 0.95);
          padding: 0.4rem 0.45rem;
          text-align: left;
          vertical-align: top;
        }
        .vol-grid-methodology-markdown th {
          background: rgba(15, 23, 42, 0.85);
          color: #e2e8f0;
          font-weight: 700;
        }
        .vol-grid-methodology-markdown tr:nth-child(even) td {
          background: rgba(2, 6, 23, 0.3);
        }
        .vol-grid-methodology-markdown .katex-display {
          margin: 0.65rem 0;
          overflow-x: auto;
          overflow-y: hidden;
        }
      `}</style>
    </div>
  )
}
