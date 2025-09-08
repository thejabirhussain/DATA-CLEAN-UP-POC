# Complyia • Data Clean, Diagnostics & Prep (React + .NET)

This repo converts the original static HTML tools in `data-clean-up/data-clean-up/` into a modern, extensible React + .NET application.

- Frontend: React 18 + Vite + Tailwind (via CDN) + `xlsx` for file parsing/exports
- Backend: .NET 8 minimal API with CORS and placeholder endpoints

## Project Structure

```
app/
  frontend/
    index.html              # Vite entry with Tailwind CDN
    vite.config.js          # Dev server + API proxy to backend
    package.json
    src/
      main.jsx              # React entry + router
      App.jsx               # Top-level layout + routes
      pages/
        Home.jsx            # Clean & Prep (basic) — from index.html
        Diagnostics.jsx     # Anomaly scan + GL↔TB reconciliation — from diagnostics.html
        Prep.jsx            # Clean & Prep (advanced) — from complyia_prep.html
  backend/
    Complyia.Api.csproj
    Program.cs              # .NET 8 minimal API, CORS, /api/health and /api/nl
```

## Routes (Frontend)

- `/` → Clean & Prep (basic) — mirrors `data-clean-up/index.html`
- `/diagnostics` → Anomaly Scan and GL↔TB reconciliation — mirrors `data-clean-up/diagnostics.html`
- `/prep` → Clean & Prep (advanced) with NL commands + undo/redo — mirrors `data-clean-up/complyia_prep.html`

## Getting Started

Open two terminals (one for backend, one for frontend).

### 1) Backend (.NET 8)

Requirements: .NET 8 SDK

```
# From: app/backend/
dotnet restore
Dotnet run
# The API serves on http://localhost:5199 (configured in Program.cs)
# Test: curl http://localhost:5199/api/health
```

### 2) Frontend (React + Vite)

Requirements: Node 18+ and npm

```
# From: app/frontend/
npm install
npm run dev
# Open the printed Vite URL (default http://localhost:5173)
```

Vite dev server proxies `/api/*` to `http://localhost:5199` (see `vite.config.js`).

## Production Build

```
# Frontend
cd app/frontend
npm run build            # outputs to dist/

# Backend
cd ../backend
# publish self-contained server (example):
dotnet publish -c Release -o out
```

You can host the backend and serve the frontend's `dist/` via a static file server or through the backend with a simple static files middleware (future enhancement).

## Notes and Next Steps

- The UI and behavior closely mirror the original HTML implementations, including file parsing, transforms, anomaly scanning, and reconciliation logic.
- The `/api/nl` endpoint currently returns an empty plan as a placeholder. Hook your AI or rules engine here. The React pages already send requests to `/api/nl` when "AI" mode is selected.
- Tailwind is loaded via CDN for simplicity. If you prefer a full PostCSS/Tailwind pipeline, we can wire it up.
- Add tests and logging as needed.

## Troubleshooting

- If the frontend cannot reach the backend, ensure the backend is running on `http://localhost:5199` and the frontend proxy is active (`vite.config.js`).
- For large files, parsing is done in-browser using SheetJS (`xlsx`).
