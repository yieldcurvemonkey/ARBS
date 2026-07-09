/** @jest-environment jsdom */
import { describe, expect, it, jest, beforeEach } from '@jest/globals'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'

// Typed per the precedent in src/app/api/usd-swaps-tape-v2/notes/__tests__/route.test.ts:
// an untyped jest.fn() here infers a `never` parameter type from jest's
// UnknownFunction default, which tsc rejects once mockResolvedValue/mockRejectedValue
// is called with concrete payloads below.
const fetchNotes = jest.fn<(...args: unknown[]) => Promise<unknown>>()
const createNote = jest.fn<(...args: unknown[]) => Promise<unknown>>()
const updateNote = jest.fn<(...args: unknown[]) => Promise<unknown>>()
const deactivateNote = jest.fn<(...args: unknown[]) => Promise<unknown>>()
jest.unstable_mockModule('../../../api/noteApi', () => ({
  fetchNotes,
  createNote,
  updateNote,
  deactivateNote,
}))
const { NotePopover } = await import('../NotePopover')

const SAMPLE_NOTE = {
  note_id: 'n1',
  target_type: 'PACKAGE',
  target_id: 'P1',
  author: 'chris',
  body: 'watch this',
  created_at: '2026-07-08T00:00:00Z',
  updated_at: null,
  is_active: true,
}

beforeEach(() => {
  // Real noteApi.fetchNotes resolves { rows: TapeNote[] } (see api/noteApi.ts) —
  // mock the real contract so unwrapNotes' `res.rows` branch is exercised.
  fetchNotes.mockReset().mockResolvedValue({ rows: [SAMPLE_NOTE] })
  createNote.mockReset().mockResolvedValue({ success: true, note_id: 'n2' })
  updateNote.mockReset().mockResolvedValue({ success: true })
  deactivateNote.mockReset().mockResolvedValue({ success: true })
})

describe('NotePopover', () => {
  it('fetches + lists existing notes on open', async () => {
    render(
      <NotePopover
        target={{ target_type: 'PACKAGE', target_id: 'P1' }}
        author="chris"
        onAuthorChange={jest.fn()}
        onClose={jest.fn()}
      />,
    )
    await waitFor(() => expect(fetchNotes).toHaveBeenCalledWith('PACKAGE', 'P1'))
    ;(expect(screen.getByText('watch this')) as any).toBeInTheDocument()
  })

  it('adds a note and calls onSaved', async () => {
    const onSaved = jest.fn()
    render(
      <NotePopover
        target={{ target_type: 'TRADE', target_id: 'T1' }}
        author="chris"
        onAuthorChange={jest.fn()}
        onClose={jest.fn()}
        onSaved={onSaved}
      />,
    )
    await waitFor(() => expect(fetchNotes).toHaveBeenCalled())
    fireEvent.change(screen.getByLabelText('note body'), { target: { value: 'hedge for FOMC' } })
    fireEvent.click(screen.getByRole('button', { name: /save note/i }))
    await waitFor(() =>
      expect(createNote).toHaveBeenCalledWith({
        target_type: 'TRADE',
        target_id: 'T1',
        author: 'chris',
        body: 'hedge for FOMC',
      }),
    )
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
  })

  it('renders nothing when target is null', () => {
    const { container } = render(
      <NotePopover target={null} author="chris" onAuthorChange={jest.fn()} onClose={jest.fn()} />,
    )
    ;(expect(container) as any).toBeEmptyDOMElement()
  })

  it('blocks save with no author', async () => {
    render(
      <NotePopover
        target={{ target_type: 'TRADE', target_id: 'T1' }}
        author=""
        onAuthorChange={jest.fn()}
        onClose={jest.fn()}
      />,
    )
    await waitFor(() => expect(fetchNotes).toHaveBeenCalled())
    fireEvent.change(screen.getByLabelText('note body'), { target: { value: 'x' } })
    ;(expect(screen.getByRole('button', { name: /save note/i })) as any).toBeDisabled()
  })

  it('blocks edit-save and delete with no author', async () => {
    render(
      <NotePopover
        target={{ target_type: 'PACKAGE', target_id: 'P1' }}
        author=""
        onAuthorChange={jest.fn()}
        onClose={jest.fn()}
      />,
    )
    await waitFor(() => (expect(screen.getByText('watch this')) as any).toBeInTheDocument())

    // Enter edit mode and attempt to save the edit.
    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }))
    const editTextarea = screen.getByLabelText('edit note n1')
    fireEvent.change(editTextarea, { target: { value: 'updated body' } })
    const saveEditButton = screen.getByRole('button', { name: /^save$/i })
    ;(expect(saveEditButton) as any).toBeDisabled()
    fireEvent.click(saveEditButton)
    expect(updateNote).not.toHaveBeenCalled()

    // Cancel out of edit mode and attempt delete.
    fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }))
    const deleteButton = screen.getByRole('button', { name: /^delete$/i })
    ;(expect(deleteButton) as any).toBeDisabled()
    fireEvent.click(deleteButton)
    expect(deactivateNote).not.toHaveBeenCalled()
  })

  it('renders an inline error when the API call fails', async () => {
    fetchNotes.mockReset().mockRejectedValue(new Error('network down'))
    render(
      <NotePopover
        target={{ target_type: 'PACKAGE', target_id: 'P1' }}
        author="chris"
        onAuthorChange={jest.fn()}
        onClose={jest.fn()}
      />,
    )
    await waitFor(() => (expect(screen.getByText('network down')) as any).toBeInTheDocument())
  })
})
