# lib/

Utility libraries and shared modules for database, caching, formatting, and performance monitoring.

## Files

| File | Description |
|------|-------------|
| `cache.ts` | Simple in-memory cache implementation for API responses with TTL support. Provides get/set/clear methods with configurable time-to-live (default 5 minutes). |
| `cbDateUtils.ts` | Central bank date utilities handling dates without timezone conversion. Formatters for CB meeting dates as pure dates (no time/timezone adjustments) to prevent date shifting. |
| `csvExport.ts` | CSV export utility for converting data arrays to downloadable CSV files. Handles header extraction, CSV formatting with escaping, and browser download trigger. |
| `dateUtils.ts` | UTC-based date and time formatting utilities for consistent trade date display. Provides formatters for UTC dates, times, relative time, and date parsing to avoid timezone issues. |
| `db.ts` | PostgreSQL connection pool configuration for Supabase with PgBouncer transaction mode. Exports query function with retry logic and automatic connection management (max 20 connections, 10s timeout). |
| `formatters.ts` | Number and date formatting utilities with K/M/B suffixes and locale support. Provides formatters for numbers, dates, times, and basis points with customizable options. |
| `performance-logger.ts` | Performance and user interaction logging singleton for frontend monitoring. Tracks performance, user actions, API calls, errors, and navigation with local storage persistence. |
| `swaptionPackages.ts` | Swaption package definitions and configuration data |
| `utils.ts` | Utility functions for number, currency, and date formatting. Provides formatters for large numbers (K/M/B/T), currency, basis points, dates, and timestamps. |
| `version.ts` | Auto-generated version information file with build metadata. Contains app version, build number, last commit hash, and build timestamp (updated on each commit). |

## Subdirectories

- `constants/` - Application-wide constants and configuration values
