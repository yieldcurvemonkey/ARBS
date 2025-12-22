# Timeseries layout frontend

This Next.js + TypeScript app provides a playground for building custom timeseries dashboards on
 top of the fetching patterns demonstrated in the ARBS notebooks. Charts can be added, rearranged,
 and resized using a responsive grid.

## Getting started

```bash
cd frontend
npm install
npm run dev
```

Then open http://localhost:3000 to start composing layouts. Data is generated locally to mirror the
IRS, fixed-rate bond, and STIR futures series used in the notebooks, so no external curve server is
required.
