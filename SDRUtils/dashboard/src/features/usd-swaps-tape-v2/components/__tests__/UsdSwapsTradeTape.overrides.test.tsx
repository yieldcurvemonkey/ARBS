// ABOUTME: Source-string contract test for the Task-19 override-orchestration
// wiring in UsdSwapsTradeTape. The orchestrator carries heavy Next/PrimeReact +
// CSS-import wiring (theme.css, next/navigation, VolumeGridCard fetch) that
// makes a full jsdom render impractical — matching the existing orchestrator
// test suite, which is entirely source-string based. Render-level behaviour of
// the pieces is covered by applyOverrides.test.ts (SPLIT explosion),
// LegsSubTable.selection.test.tsx (leg checkbox + note), columns.override.test
// (override badges) and the RegroupActionBar / OverrideCommitPopover /
// NotePopover component tests. Here we pin the integration: that those pieces
// are actually mounted and wired to selection / refetch / undo.
import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx',
  ),
  'utf8',
)

describe('UsdSwapsTradeTape — override building-block imports', () => {
  it('imports applyOverrides, useTradeSelection and useSelectionContext', () => {
    expect(source).toMatch(/import\s+\{\s*applyOverrides\s*\}\s+from\s+['"]\.\.\/utils\/applyOverrides['"]/)
    expect(source).toMatch(/useTradeSelection/)
    expect(source).toMatch(/useSelectionContext/)
  })

  it('imports the action bar, commit popover, note popover and overrides panel', () => {
    expect(source).toMatch(/import\s+\{\s*RegroupActionBar\s*\}\s+from\s+['"]\.\/RegroupActionBar\/RegroupActionBar['"]/)
    expect(source).toMatch(/import\s+\{\s*OverrideCommitPopover\s*\}\s+from\s+['"]\.\/OverrideCommitPopover\/OverrideCommitPopover['"]/)
    expect(source).toMatch(/import\s+\{\s*NotePopover\s*\}\s+from\s+['"]\.\/NotePopover\/NotePopover['"]/)
    expect(source).toMatch(/import\s+\{\s*OverridesPanel\s*\}\s+from\s+['"]\.\/OverridesPanel\/OverridesPanel['"]/)
  })

  it('imports createOverride + deactivateOverride for the undo affordance', () => {
    expect(source).toMatch(/import\s+\{[^}]*createOverride[^}]*deactivateOverride[^}]*\}\s+from\s+['"]\.\.\/api\/overrideApi['"]/)
  })
})

describe('UsdSwapsTradeTape — retired legacy selection / link-create paths', () => {
  it('no longer imports groupLinkedRows directly', () => {
    expect(source).not.toMatch(/import\s+\{[^}]*groupLinkedRows[^}]*\}/)
  })

  it('no longer imports or mounts ManualLinksDialog (create flow retired)', () => {
    expect(source).not.toMatch(/ManualLinksDialog/)
  })

  it('no longer uses the package-row useRowSelection hook', () => {
    expect(source).not.toMatch(/useRowSelection/)
  })

  it('still keeps the legacy ManualLinkDetailModal for auto manual_link rows', () => {
    expect(source).toMatch(/<ManualLinkDetailModal\b/)
  })
})

describe('UsdSwapsTradeTape — override display + selection wiring', () => {
  it('memoizes applyOverrides on tape.rows identity into displayRows', () => {
    expect(source).toMatch(/const\s+displayRows\s*=\s*useMemo\(\(\)\s*=>\s*applyOverrides\(tape\.rows\),\s*\[tape\.rows\]\)/)
  })

  it('feeds displayRows (not tape.rows) into the table', () => {
    expect(source).toMatch(/<TradeTapeTable\b[\s\S]{0,120}rows=\{displayRows\}/)
  })

  it('derives the selection context from the original rows + selected trade ids', () => {
    expect(source).toMatch(/useSelectionContext\(tape\.rows,\s*tradeSelection\.selectedTradeIds\)/)
  })

  it('wires the leg-level selection callbacks into the table', () => {
    expect(source).toMatch(/selectedTradeIds=\{tradeSelection\.selectedTradeIds\}/)
    expect(source).toMatch(/onTogglePackage=\{tradeSelection\.togglePackage\}/)
    expect(source).toMatch(/onToggleTrade=\{tradeSelection\.toggleTrade\}/)
    expect(source).toMatch(/onOpenNote=\{setNoteTarget\}/)
  })
})

describe('UsdSwapsTradeTape — action bar + popovers mounted', () => {
  it('mounts RegroupActionBar gated on a non-empty selection', () => {
    expect(source).toMatch(/tradeSelection\.count\s*>\s*0[\s\S]{0,120}<RegroupActionBar/)
  })

  it('mounts the OverrideCommitPopover and clears selection + refetches on success', () => {
    expect(source).toMatch(/<OverrideCommitPopover\b/)
    expect(source).toMatch(/onSuccess=\{\(result\)\s*=>\s*\{[\s\S]{0,200}tradeSelection\.clear\(\)[\s\S]{0,80}tape\.refetch\(\)/)
  })

  it('mounts the NotePopover and refetches the tape on save (so has_notes updates)', () => {
    expect(source).toMatch(/<NotePopover\b[\s\S]{0,200}onSaved=\{\(\)\s*=>\s*tape\.refetch\(\)\}/)
  })

  it('mounts the OverridesPanel behind overridesPanelOpen and refetches on revert', () => {
    expect(source).toMatch(/overridesPanelOpen\s*\?\s*\([\s\S]{0,120}<OverridesPanel/)
    expect(source).toMatch(/onReverted=\{\(overrideId,\s*recreate\)\s*=>\s*\{[\s\S]{0,160}tape\.refetch\(\)/)
  })

  it('exposes an Overrides toolbar button that opens the panel', () => {
    expect(source).toMatch(/onClick=\{\(\)\s*=>\s*setOverridesPanelOpen\(true\)\}/)
    expect(source).toMatch(/>\s*Overrides\s*</)
  })

  it('offers an Undo affordance after the last override action', () => {
    expect(source).toMatch(/lastAction\s*\?/)
    expect(source).toMatch(/onClick=\{handleUndo\}/)
  })
})
