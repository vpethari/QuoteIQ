# QuoteIQ local development (Windows)

Run the API and the web UI in two terminals. Azure OpenAI is optional and is not required for deterministic matching.

## Terminal 1 — backend

```powershell
cd C:\Projects\QuoteIQ
py -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Do not set `PYTHONPATH`. Start this command from the repository root.

- API: http://127.0.0.1:8000
- Health: http://127.0.0.1:8000/health

## Terminal 2 — frontend

```powershell
cd C:\Projects\QuoteIQ\frontend
npm install
npm run dev
```

- UI: http://localhost:5173

Vite proxies `/api/*` to http://127.0.0.1:8000. Leave `VITE_API_BASE_URL` empty in development so the browser calls `/api/...` on the Vite origin.

## Environment

Copy `.env.example` to `.env` in the repository root if you need to override defaults. See comments in `.env.example`. Azure OpenAI variables may stay blank.

For local pytest, `CATALOG_SOURCE=excel` is set automatically so unit tests do not require PostgreSQL. Runtime matching in the API uses PostgreSQL (`CATALOG_SOURCE=postgresql`, table `productmaster`) and `Productcode` as the matched part number. The Excel catalog is not loaded during normal matching.

## Process a quote

1. Open http://localhost:5173
2. Upload `data/inputfile.xlsx`
3. Leave **Use AI matching** off
4. Click **Process Quote**
5. Expand a Review Required row to inspect catalog candidates
6. Click **Download CSV** for `QuoteIQ_results.csv`

The current sample quote is expected to show 3 lines, all Review Required, because several Atkore products share the same description. Those counts come from the API.
