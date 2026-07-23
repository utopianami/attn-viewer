# AGENTS.md

## Project Direction

This project should be developed Swagger/OpenAPI contract first. Do not rely on
ad hoc natural-language descriptions of backend behavior when adding frontend
features. The backend API contract is the source of truth for frontend work,
tests, and agent context.

The operating idea comes from the Swagger/OpenAPI workflow described in:

https://news.hada.io/topic?id=28597

Key takeaway: a machine-readable API spec is better context than prose. When it
is converted into typed client code or checked by a test harness, it becomes a
guardrail that catches hallucinated field names, wrong response shapes, and
missing constraints early.

## Required Workflow

When adding or changing an API endpoint:

1. Update or add the Swagger/OpenAPI contract in the same change.
2. Keep request fields, response fields, error shapes, auth requirements, and
   constraints explicit.
3. Make the frontend follow that contract instead of duplicating undocumented
   assumptions.
4. Verify the endpoint with an executable check, such as `curl`, a schema check,
   or a typed client compile step when one exists.
5. Update README only for operational instructions. Keep API behavior in the API
   contract.

## Mobile First UI

All UI work must be mobile first. Start layout decisions from the narrow mobile
viewport, then enhance for tablet and desktop.

Rules:

- Primary flows must work comfortably on a phone.
- Do not add desktop-only navigation or controls without a mobile equivalent.
- Keep controls reachable, text wrapping cleanly, and cards/buttons stable at
  small widths.
- Use responsive grids only after the single-column mobile layout is correct.
- Before finishing meaningful UI changes, inspect the page at mobile and desktop
  widths.

## Current API Surface

The current server is `server.mjs`; the current frontend is
`public/index.html`.

Note: the list below is a snapshot of the document-viewer feature only, not the
full route surface. Blog, memory-sector, and KG routes live in `server.mjs` and
the `lib/` route modules. Some implemented routes are not yet in `openapi.yaml`
(non-exhaustive examples: `/kg`, `/api/kg/*`, `/v1/case-memory/*`) — this is a
known gap to close when touching those routes.

Auth endpoints:

- `GET /api/session`
- `POST /api/login`
- `POST /api/logout`

Document endpoints, all requiring login:

- `GET /api/documents`
- `GET /api/documents/latest`
- `GET /api/documents/:id`
- `GET /api/documents/:id/pdf`
- `POST /api/documents/:id/analyze`
- `POST /api/documents/:id/shares`
- `POST /api/uploads/pdf`

Public share endpoints, not requiring login:

- `GET /api/shares/:token`
- `GET /api/shares/:token/pdf`
- `GET /api/shares/:token/assets/:file`

Asset endpoints, requiring login:

- `GET /assets/:id/:file`

## User Storage Rule

All document data must stay user-scoped. Do not write new document, asset,
analysis, upload, or conversion files into shared top-level storage folders.

Use this layout:

```text
storage/users/<username>/
  uploads/
  converted/
  documents/
  assets/
  analysis/
```

If a new feature creates user data, put it under the matching user directory or
add a clearly named user-scoped subdirectory.

Exception: singleton system reports (`storage/rag/memory_sector/reports/`) are
market data generated from public sources, not user analysis — global storage
and the public read-only routes are intentional.

## Auth Rule

Features that read or write documents must require login. Do not expose PDF
files, extracted images, markdown, metadata, or analysis output through a public
route.

Exception: token-based share routes explicitly created by an authenticated user
are intentionally public — `GET /api/shares/:token`, `GET /api/shares/:token/pdf`,
`GET /api/shares/:token/assets/:file`, `GET /api/analysis-html-shares/:token`,
`GET /api/chat-shares/:token`.

Sessions are persisted in `storage/sessions.json` (see `server.mjs`), so a
normal process restart does not log users out until the cookie expires. User
files remain on disk.

## Implementation Style

Keep changes small and aligned with the current app shape:

- Express routes in `server.mjs` and route modules in `lib/` (e.g.
  `blogs-router.mjs`, `memory-router.mjs`).
- Browser UI in `public/index.html`.
- Runtime files under `storage/`.
- Python PDF tooling in `.venv/`, installed from `requirements.txt`.

Before finishing backend changes, run:

```bash
node --check server.mjs
```

For running service checks, prefer:

```bash
curl -i http://127.0.0.1:3000/api/session
pm2 list
```

## Next Contract Step

`openapi.yaml` exists at the repo root. When changing routes, request fields,
response shapes, error shapes, or auth requirements, update `openapi.yaml` in
the same change. Known gap: some implemented routes (non-exhaustive: KG and
case-memory routes) are not yet registered — close the gap when touching them.
