# TODO

## URL Upload

- Add `POST /api/uploads/url` and document it in `openapi.yaml` first.
- Fetch public URLs server-side, store the original HTML for debugging, then extract the readable article body.
- Convert extracted article HTML to markdown and save it into the same document shape used by PDFs:
  - `storage/users/<username>/documents/<id>.json`
  - `storage/users/<username>/converted/<id>.md`
  - `storage/users/<username>/assets/<id>/manifest.json`
- Use established parsing tools instead of ad hoc selectors:
  - `jsdom` for DOM parsing
  - `@mozilla/readability` for main article extraction
  - `turndown` for HTML-to-markdown conversion
- Collect only article-body images at first. Resolve relative image URLs against the source URL, download them into the user-scoped asset folder, and skip tiny logos/icons/avatar-like images.
- Reuse the existing document list, delete, reader, progress, and translation flow after URL conversion.
- Treat login-gated URLs as unsupported in the first version. Show a clear message telling the user to upload a saved PDF/HTML export instead.
- Avoid accepting user cookies or passwords for third-party sites. If authenticated capture becomes necessary later, prefer a browser extension or bookmarklet that sends the already-rendered page content.

## Public Share Links

- Goal: let a logged-in user share the existing read-only reader view with someone who is not logged in.
- Create shares explicitly from an existing document. Do not make every document public by default.
- Use the same reader layout as the logged-in article screen, but hide home/list/back/share/translate/delete controls for public visitors.
- Serve public documents, PDFs, and assets only through share-token routes. Do not expose usernames, local paths, session IDs, or current-user document URLs.
- Store share records in user-scoped storage, for example:

```text
storage/users/<username>/shares/<shareId>.json
```

- The share record should point to the source document and contain the public token, created time, optional expiry, and enabled/disabled status.
- Public share responses should remap PDF and asset URLs to `/api/shares/{token}/...`.
- Deleting the source document should revoke or remove its share links.
- Add share management later:
  - list existing links
  - revoke a link
  - rotate/regenerate a link
  - optional expiry
- Add rate limiting or lightweight abuse protection before exposing public unauthenticated routes broadly.
