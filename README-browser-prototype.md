# Goodreads browser prototype

This experimental workflow tests read-only extraction from the Goodreads shelf pages using a Playwright browser state supplied by the repository owner.

## Authentication setup

1. On a trusted computer, sign in to Goodreads in a local Playwright-controlled Chromium browser.
2. Save the browser context storage state to a JSON file. Treat this file like a password: it contains session cookies.
3. Add its complete JSON content as a GitHub Actions repository secret named \`GOODREADS_STORAGE_STATE_JSON\`.
4. Run **Goodreads browser prototype (read-only)** manually from the Actions tab, selecting this prototype branch.

Do not commit the storage-state file, paste it into chat, or put it in ordinary repository variables. Rotate/revoke the Goodreads session if the secret is exposed. The workflow reads the secret at runtime and does not print it.

## Scope and safety

- The script only performs GET-style page navigation and DOM reads.
- It does not submit forms, change shelves, rate books, or update reading progress.
- The workflow has \`contents: read\` permission and does not commit data.
- The result is uploaded as a short-lived Actions artifact (3 days), not published to the repository.
- This is an experiment, not a verified production sync. Goodreads may change its page structure or restrict automated browsing.
- The script deliberately fails if it cannot recognize the page or the first page of a shelf, rather than treating a parsing failure as an empty shelf.

## Prototype output

The artifact contains per-shelf lists and a merged book list with Goodreads book IDs, titles, authors, links, shelf memberships, and progress text only when a recognized progress element is present.
