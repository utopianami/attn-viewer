# attn-viewer

Translation-focused reader for URLs and PDFs.

## Local page

Install Node and Python dependencies first:

```bash
npm ci
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Create local environment settings:

```bash
cp .env.example .env
```

Then fill `.env` locally. Real account values and ngrok tokens must stay out of
git.

`server.mjs` expects these local binaries by default:

```bash
.venv/bin/markitdown
.venv/bin/python
```

Start the app:

```bash
npm start
```

The local server listens on `http://127.0.0.1:3000`.

## Login and user storage

The app requires login before document APIs, PDF files, and extracted assets can
be accessed. Accounts are loaded from `.env`:

```bash
AUTH_USERS_JSON={"alice":"change-me","bob":"change-me-too"}
```

`AUTH_USERS_JSON` is a JSON object whose keys are usernames and values are
passwords. Keep real credentials only in local `.env`; `.env` is ignored by git.

Each user has isolated storage under:

```bash
storage/users/<username>/
```

with these subfolders:

```bash
uploads/
converted/
documents/
assets/
analysis/
```

Sessions are stored in `storage/sessions.json`, so normal PM2 restarts keep
users logged in until the cookie expires. Deleting `storage/` or
`storage/sessions.json` logs everyone out.

## Project structure

```text
server.mjs                         Express API, auth, storage, PDF conversion
public/index.html                  Mobile-first single-page UI
scripts/tunnel.mjs                 ngrok helper
scripts/extract_pdf_assets.py      PDF page/chart image extraction
schemas/translation-analysis.schema.json
                                    Codex translation output schema
storage/users/<username>/          Runtime user data, ignored by git
storage/sessions.json              Runtime login sessions, ignored by git
.env                               Local secrets and deployment settings, ignored by git
```

Runtime user data is not part of the repo. To move an installation, copy the
repo plus the target machine's local `.env`, then copy `storage/users/` only if
you intentionally want to migrate existing uploaded documents.

## API contract

Development is Swagger/OpenAPI first. Keep `openapi.yaml` updated when changing
API routes, request fields, response shapes, or auth requirements.

The UI is mobile-first. Build and verify the narrow/mobile layout before widening
the desktop layout.

## PM2

Run the server with PM2:

```bash
pm2 start server.mjs --name attn-viewer --cwd /home/ryze_yn/attn-viewer --time --update-env
pm2 save
```

## ngrok fixed domain

Add your reserved ngrok domain to `.env`:

```bash
NGROK_DOMAIN=https://your-domain.ngrok.app
```

Then run:

```bash
npm run tunnel
```

For the current reserved domain through PM2:

```bash
NGROK_DOMAIN=https://attn.ngrok.app PORT=3000 pm2 start npm --name attn-ngrok --cwd /home/ryze_yn/attn-viewer --time --update-env -- run tunnel
pm2 save
```

If ngrok is not already authenticated on this machine, also add `NGROK_AUTHTOKEN`
to `.env`. The tunnel script passes the token to ngrok without printing it.
Alternatively, install it in the ngrok config:

```bash
ngrok config add-authtoken <YOUR_NGROK_AUTHTOKEN>
```

## Translation generation

The app calls Codex CLI in a background job to generate Korean summaries,
paragraph notes, sentence translations, and chart interpretations. Uploading a
PDF creates the document first; translation can be started later and the
document remains visible in the 글 목록 while it is queued or running.

```bash
codex login
```

Optional `.env` overrides:

```bash
CODEX_BIN=codex
CODEX_MODEL=
CODEX_TRANSLATION_TIMEOUT_MS=240000
CODEX_ANALYSIS_CHUNK_PAGES=4
CODEX_ANALYSIS_CONCURRENCY=2
```

Translation jobs are persisted in `storage/analysis-jobs.json`, so PM2 restarts
can resume queued/running jobs and the UI can show progress after refresh or a
new login.

Translation quality/speed policy:

- Send the original English text to the model and keep it in `sentencePairs.source`.
- Send chart images only with the page chunk they belong to, so graph reading uses
  nearby English context without resending the whole document.
- Split long PDFs into page chunks and translate chunks in parallel with
  `CODEX_ANALYSIS_CONCURRENCY`, then synthesize the whole-document summary.
- Filter platform boilerplate such as Substack comments, legal disclaimers,
  privacy/terms, copyright, and footer pages before/after model output when it
  does not add research content.
