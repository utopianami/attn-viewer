# attn-viewer

Translation-focused reader for URLs and PDFs.

## Local page

Install Node and Python dependencies first:

```bash
npm ci
npx playwright install chromium
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
python3 -m venv engine/.venv
engine/.venv/bin/pip install --upgrade pip
engine/.venv/bin/pip install -r engine/requirements-dev.txt
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

Start the Python QA engine in a second terminal when using research chat or the
memory-sector dashboard:

```bash
engine/.venv/bin/uvicorn engine.app.main:app --host 127.0.0.1 --port 8801
```

## Checks and tests

Run the default offline checks with:

```bash
npm test
```

This checks JavaScript syntax, validates `openapi.yaml`, runs Node unit/API
contract tests and mobile/desktop browser smoke tests against an isolated
temporary server, and runs Python tests that do not require external services.
The isolated tests never use the real
`storage/` directory or the PM2 processes.

Network-dependent Yahoo and Toss smoke tests are opt-in:

```bash
npm run test:engine:live
```

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

The checked-in manifest owns one process for each core role: viewer, API engine,
scheduler worker, and vault bridge. Applications load local settings from
`.env`; the tunnel remains opt-in.

```bash
cd /home/ryze_yn/attn-viewer
pm2 startOrReload ecosystem.config.cjs --update-env
pm2 save
```

Install the single systemd startup owner and log rotation:

```bash
sudo install -m 0644 ops/pm2-ryze_yn.service /etc/systemd/system/pm2-ryze_yn.service
sudo install -m 0644 ops/logrotate-attn-viewer /etc/logrotate.d/attn-viewer
sudo systemctl daemon-reload
sudo systemctl enable pm2-ryze_yn.service
sudo logrotate --debug /etc/logrotate.d/attn-viewer
```

Do not also resurrect PM2 from crontab. A one-time migration must first save
`crontab -l` to an external backup, then remove only this exact legacy line:

```text
@reboot /usr/bin/env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin PM2_HOME=/home/ryze_yn/.pm2 /usr/bin/pm2 resurrect >> /home/ryze_yn/.pm2/reboot.log 2>&1
```

For a previously duplicated PM2 list, back up `~/.pm2/dump.pm2` and logs first,
stop all `attn-*` entries once, delete those exact entries, start the manifest,
and run `pm2 save` once. Normal deployments use only `startOrReload`.

Runtime data repair is dry-run by default. Applying it requires a new backup
directory outside `storage/`; changed JSONL files are copied there and orphaned
raw/summary temp files are moved into its quarantine tree.

```bash
python3 scripts/repair_runtime_data.py
python3 scripts/repair_runtime_data.py --apply \
  --backup-root /home/ryze_yn/attn-viewer-ops-backups/20260903T120000Z/data-repair
```

## ngrok fixed domain

Add your reserved ngrok domain to `.env`:

```bash
NGROK_DOMAIN=https://your-domain.ngrok.app
```

Then run it explicitly:

```bash
ATTN_NGROK_ENABLED=1 pm2 startOrReload ecosystem.config.cjs --update-env
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
- Apply the content-bearing rule before/after model output: keep material only
  when it contributes to the document's thesis, evidence, data interpretation,
  method, conclusion, assumptions, or risk analysis. Drop UI, publishing
  metadata, author bio, legal/compliance boilerplate, copyright, terms/privacy,
  subscription/login/share controls, comments/reactions, repeated headers/footers,
  and empty page regions. A disclaimer or risk sentence is kept only when the
  author uses it as part of a substantive analytical point.
