# Manual Links Integration Guide

This guide explains how to integrate manual trade linking functionality into the SwaptionTradeTape component.

## Overview

The manual linking feature is frontend-driven and consists of:
- **Hook**: `useManualLinks` - Manages link state and API calls
- **Modal**: `ManualLinkModal` - Create new links
- **Badge**: `ManualLinkBadge` - Display link indicator on trades
- **Panel**: `ManualLinkPanel` - View/edit link details

## Integration Steps

### 1. Add the hook to SwaptionTradeTape

```tsx
import { useManualLinks } from '@/hooks/useManualLinks'

export default function SwaptionTradeTape() {
  // Existing state...
  const [rows, setRows] = useState<TapeRow[]>([])

  // Add manual links hook
  const {
    links,
    isLoading: linksLoading,
    error: linksError,
    loadLinks,
    createLink,
    updateLink,
    deleteLink,
    getLinksForTrades,
    isTradeLinked,
    linkedTradeIds
  } = useManualLinks()

  // Add selection state
  const [selectedTrades, setSelectedTrades] = useState<Set<string>>(new Set())
  const [showLinkModal, setShowLinkModal] = useState(false)
  const [selectedLink, setSelectedLink] = useState<ManualLink | null>(null)
  const [showLinkPanel, setShowLinkPanel] = useState(false)

  // Load links when data loads
  useEffect(() => {
    if (rows.length > 0) {
      const start = rows[rows.length - 1].execution_start
      const end = rows[0].execution_start
      loadLinks(start, end)
    }
  }, [rows, loadLinks])
}
```

### 2. Add selection column to DataTable

```tsx
<DataTable
  value={rows}
  selection={Array.from(selectedTrades).map(id =>
    rows.find(r => r.package_id === id)
  )}
  onSelectionChange={(e) => {
    const ids = new Set(e.value.map(r => r.package_id))
    setSelectedTrades(ids)
  }}
  dataKey="package_id"
>
  {/* Add selection column first */}
  <Column
    selectionMode="multiple"
    headerStyle={{ width: '3rem' }}
    frozen
  />

  {/* Existing columns... */}
</DataTable>
```

### 3. Add link badge to package_id column

```tsx
const packageIdBodyTemplate = (rowData: TapeRow) => {
  const tradeLinks = getLinksForTrades([rowData.package_id])

  return (
    <div className="flex items-center gap-2">
      <span className="font-mono text-xs">{rowData.package_id}</span>
      {tradeLinks.length > 0 && (
        <ManualLinkBadge
          tradeId={rowData.package_id}
          links={links}
          onClick={(link) => {
            setSelectedLink(link)
            setShowLinkPanel(true)
          }}
        />
      )}
    </div>
  )
}

// Use it in the Column
<Column
  field="package_id"
  header="Package ID"
  body={packageIdBodyTemplate}
/>
```

### 4. Add toolbar with link button

```tsx
<div className="flex items-center justify-between mb-4">
  {/* Existing toolbar items */}

  {/* Add link button */}
  {selectedTrades.size >= 2 && (
    <Button
      label={`Link ${selectedTrades.size} Trades`}
      icon="pi pi-link"
      onClick={() => setShowLinkModal(true)}
      className="p-button-sm"
    />
  )}
</div>
```

### 5. Add modal and panel components

```tsx
// At the end of the component return
return (
  <div>
    {/* Existing DataTable */}
    <DataTable>...</DataTable>

    {/* Add Modal */}
    <ManualLinkModal
      visible={showLinkModal}
      onHide={() => {
        setShowLinkModal(false)
        setSelectedTrades(new Set())
      }}
      selectedTrades={Array.from(selectedTrades)
        .map(id => rows.find(r => r.package_id === id))
        .filter(Boolean)}
      onCreateLink={async (tradeIds, comment, tags) => {
        const link = await createLink({
          trade_ids: tradeIds,
          comment,
          tags,
          user: 'current_user@example.com' // Replace with actual user
        })
        return link !== null
      }}
    />

    {/* Add Panel */}
    <ManualLinkPanel
      visible={showLinkPanel}
      onHide={() => {
        setShowLinkPanel(false)
        setSelectedLink(null)
      }}
      link={selectedLink}
      trades={rows}
      onUpdate={async (linkId, comment, tags) => {
        return await updateLink({ link_id: linkId, comment, tags })
      }}
      onDelete={async (linkId) => {
        return await deleteLink(linkId)
      }}
    />
  </div>
)
```

## Display Modes (Optional)

### Flat View (Default)
All trades shown individually with link badges.

### Grouped View
Group linked trades under a single header row. Add this logic:

```tsx
const processedRows = useMemo(() => {
  if (displayMode === 'flat') {
    return rows
  }

  // Grouped mode: create parent rows for links
  const linkedIds = linkedTradeIds()
  const grouped: TapeRow[] = []
  const processed = new Set<string>()

  rows.forEach(row => {
    if (processed.has(row.package_id)) return

    const rowLinks = getLinksForTrades([row.package_id])
    if (rowLinks.length === 0) {
      // Not linked - show normally
      grouped.push(row)
    } else {
      // Linked - create group row
      const link = rowLinks[0]
      const linkedRows = rows.filter(r =>
        link.linked_trade_ids.includes(r.package_id)
      )

      // Mark all as processed
      linkedRows.forEach(r => processed.add(r.package_id))

      // Add group parent
      grouped.push({
        ...row,
        _isLinkGroup: true,
        _linkId: link.link_id,
        _linkedRows: linkedRows
      })
    }
  })

  return grouped
}, [rows, displayMode, links])
```

## User Context

Replace the hardcoded user email with actual authentication:

```tsx
// Option 1: From session
import { useSession } from 'next-auth/react'
const { data: session } = useSession()
const currentUser = session?.user?.email || 'anonymous'

// Option 2: From environment
const currentUser = process.env.NEXT_PUBLIC_USER_EMAIL || 'unknown'

// Option 3: From a context
import { useAuth } from '@/contexts/AuthContext'
const { user } = useAuth()
const currentUser = user?.email || 'unknown'
```

## Styling

The components use PrimeReact theming (lara-dark-indigo). Customize via:

```tsx
// In _app.tsx or layout.tsx
import 'primereact/resources/themes/lara-dark-indigo/theme.css'

// Or use custom CSS variables
:root {
  --primary-color: #6366f1;
  --surface-a: #1e293b;
  --surface-b: #334155;
  --surface-c: #475569;
}
```

## API Configuration

If your API endpoints are at a different path, update the hook:

```tsx
// In useManualLinks.ts
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '/api'

const response = await fetch(`${API_BASE}/manual-links?${params}`)
```

## Testing

1. **Create Link**: Select 2+ trades, click "Link", add comment, submit
2. **View Link**: Click badge on linked trade, panel opens
3. **Edit Link**: In panel, click "Edit", modify comment/tags, save
4. **Delete Link**: In panel, click "Unlink Trades", confirm

## Troubleshooting

### Links not loading
- Check API endpoint is running
- Check database migration was applied
- Check browser console for errors

### Selection not working
- Ensure DataTable has `dataKey="package_id"`
- Ensure `selection` and `onSelectionChange` props are set

### Badge not showing
- Check `links` array is populated
- Check `getLinksForTrades` returns links
- Check trade ID matches what's in database

## Performance

- Links are loaded once per date range
- All computation (metrics, validation) happens in frontend
- Use `useMemo` for expensive calculations
- Debounce link creation to prevent duplicate submits
