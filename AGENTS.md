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

## Auth Rule

Features that read or write documents must require login. Do not expose PDF
files, extracted images, markdown, metadata, or analysis output through a public
route.

Current sessions are in server memory. A Node process restart logs users out,
but user files remain on disk.

## Implementation Style

Keep changes small and aligned with the current app shape:

- Express routes in `server.mjs`.
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

The next structural improvement should be adding an OpenAPI document for the
current API, then keeping it updated with each endpoint change. Once the spec
exists, frontend changes should use the OpenAPI contract as the primary context
for request and response shapes.
