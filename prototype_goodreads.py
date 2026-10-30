#!/usr/bin/env python3
"""Experimental, read-only Goodreads shelf reader using an authenticated browser state.

The script never performs login, submits forms, or clicks Goodreads write controls.
It only navigates shelf-list pages and extracts visible book metadata.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

USER_ID = os.environ.get("GOODREADS_USER_ID", "34901135")
SHELVES = [
    "1st_priority",
    "next",
    "currently-reading",
    "to-read",
    "read",
    "audio",
]
BASE = f"https://www.goodreads.com/review/list/{USER_ID}"
MAX_PAGES = 30
PER_PAGE = 100


def extract_rows(page, shelf: str) -> list[dict]:
    # Goodreads has used more than one shelf-list markup. Prefer semantic table
    # rows, then fall back to elements carrying a Goodreads book identifier.
    rows = page.locator("tr.bookalike").evaluate_all("""els => els.map(row => {
      const title = row.querySelector('a.bookTitle, a[href*="/book/show/"]');
      const author = row.querySelector('a.authorName, .authorName');
      const id = row.getAttribute('id') || '';
      const bookLink = title ? title.href : '';
      const match = bookLink.match(/\\/book\\/show\\/(\\d+)/) || id.match(/(?:review_|book_)(\\d+)/);
      const progressNode = row.querySelector('[class*="progress"], [data-testid*="progress"]');
      return {
        goodreads_book_id: match ? match[1] : '',
        title: title ? title.innerText.trim() : '',
        author: author ? author.innerText.trim() : '',
        link: bookLink,
        row_text: row.innerText.trim(),
        progress_text: progressNode ? progressNode.innerText.trim() : ''
      };
    })""")
    if not rows:
        rows = page.locator("[data-book-id]").evaluate_all("""els => els.map(row => {
          const title = row.querySelector('a[href*="/book/show/"]');
          const author = row.querySelector('a.authorName, .authorName');
          return {
            goodreads_book_id: row.getAttribute('data-book-id') || '',
            title: title ? title.innerText.trim() : '',
            author: author ? author.innerText.trim() : '',
            link: title ? title.href : '',
            row_text: row.innerText.trim(),
            progress_text: ''
          };
        })""")

    result = []
    for item in rows:
        if not item["title"] or not item["link"]:
            continue
        item.pop("row_text", None)
        item["shelves"] = [shelf]
        item["progress"] = item.pop("progress_text") or None
        result.append(item)
    return result


def main() -> None:
    state = os.environ.get("GOODREADS_STORAGE_STATE_JSON")
    if not state:
        raise RuntimeError("Missing GOODREADS_STORAGE_STATE_JSON secret.")
    storage = json.loads(state)
    if not isinstance(storage, dict) or "cookies" not in storage:
        raise RuntimeError("Storage state is not a valid Playwright storage-state JSON object.")

    all_shelves: dict[str, list[dict]] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=storage)
        page = context.new_page()
        page.set_default_timeout(20000)

        # Verify the supplied state is authenticated before touching shelf pages.
        response = page.goto(f"https://www.goodreads.com/user/show/{USER_ID}", wait_until="domcontentloaded")
        if response and response.status >= 400:
            raise RuntimeError(f"Goodreads profile returned HTTP {response.status}.")
        if "sign_in" in urlparse(page.url).path or page.locator("form[action*='sign_in']").count():
            raise RuntimeError("The supplied browser state is not authenticated; Goodreads redirected to sign-in.")

        for shelf in SHELVES:
            books: list[dict] = []
            seen: set[str] = set()
            for number in range(1, MAX_PAGES + 1):
                url = f"{BASE}?shelf={shelf}&per_page={PER_PAGE}&page={number}"
                response = page.goto(url, wait_until="domcontentloaded")
                if response and response.status >= 400:
                    raise RuntimeError(f"Shelf {shelf!r}, page {number}: HTTP {response.status}.")
                if "sign_in" in urlparse(page.url).path:
                    raise RuntimeError(f"Authentication expired while reading shelf {shelf!r}.")
                page.wait_for_timeout(1200)
                rows = extract_rows(page, shelf)
                if number == 1 and not rows:
                    # Do not interpret unknown markup or a Goodreads error page as an empty shelf.
                    body = page.locator("body").inner_text()[:500]
                    raise RuntimeError(
                        f"No recognizable book rows on shelf {shelf!r}. "
                        f"Page title={page.title()!r}; body preview={body!r}"
                    )
                added = 0
                for book in rows:
                    key = book["goodreads_book_id"] or book["link"]
                    if key and key not in seen:
                        seen.add(key)
                        books.append(book)
                        added += 1
                if not rows or added == 0 or len(rows) < PER_PAGE:
                    break
            else:
                raise RuntimeError(f"Shelf {shelf!r} reached {MAX_PAGES} pages; refusing partial output.")
            all_shelves[shelf] = books
            print(f"{shelf}: {len(books)} books")

        browser.close()

    # Merge shelf memberships without losing shelf-specific counts.
    merged: dict[str, dict] = {}
    for shelf, books in all_shelves.items():
        for book in books:
            key = book["goodreads_book_id"] or book["link"]
            if key not in merged:
                merged[key] = {**book, "shelves": []}
            merged[key]["shelves"] = sorted(set(merged[key]["shelves"]) | {shelf})

    snapshot = {
        "schema_version": 1,
        "source": "Goodreads authenticated browser (read-only prototype)",
        "goodreads_user_id": USER_ID,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "shelf_counts": {name: len(items) for name, items in all_shelves.items()},
        "shelves": all_shelves,
        "books": list(merged.values()),
        "status": "prototype_success",
    }
    out = Path("prototype-output/goodreads-prototype.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(merged)} unique books to {out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
