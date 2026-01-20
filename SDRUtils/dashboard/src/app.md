# app/

Next.js App Router pages and layouts for the SwapPulse dashboard application.

## Files

| File | Description |
|------|-------------|
| `layout.tsx` | Root layout component configuring app-wide fonts, metadata, and layout structure. Sets up Geist fonts, page transitions, and MainLayout wrapper for all pages. |
| `page.tsx` | Main dashboard page displaying trade summaries, recent trades, and block trades. Client component with real-time data fetching, CB monitor, and version info. |

## Subdirectories

- `analytics/` - Analytics dashboard pages
- `api/` - API routes for data fetching and server-side logic
- `block-trades/` - Block trades analysis pages
- `butterfly-explorer/` - Butterfly spread exploration interface
- `cb-analytics/` - Central bank analytics dashboard
- `cb-monitor/` - Central bank monitoring interface
- `live/` - Live trading data views
- `package-monitor/` - Package monitoring dashboard
- `packages/` - Package trading analysis pages
- `personas/` - User persona dashboards
- `rv-analytics/` - Relative value analytics pages
- `summary/` - Summary and overview pages
- `swaptions/` - Swaptions trading dashboards
- `swaptions-monitor/` - Swaptions real-time monitoring
- `swaptions-table/` - Swaptions data tables
