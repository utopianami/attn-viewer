# attn-viewer

Translation-focused reader for URLs and PDFs.

## Local page

```bash
npm start
```

The local server listens on `http://127.0.0.1:3000`.

## ngrok fixed domain

Add your reserved ngrok domain to `.env`:

```bash
NGROK_DOMAIN=https://your-domain.ngrok.app
```

Then run:

```bash
npm run tunnel
```

If ngrok is not already authenticated on this machine, also add `NGROK_AUTHTOKEN`
to `.env`. The tunnel script passes the token to ngrok without printing it.

## Translation generation

The prototype can call Codex CLI to generate Korean summaries, paragraph notes,
sentence translations, and chart interpretations for a document sample.

```bash
codex login
```

Optional `.env` overrides:

```bash
CODEX_BIN=codex
CODEX_MODEL=
CODEX_TRANSLATION_TIMEOUT_MS=240000
```
