#!/usr/bin/env python3
"""Read public Goodreads shelf RSS feeds and save a normalized snapshot.

This is read-only: it never changes Goodreads shelves or reviews. Goodreads may
reject requests from hosted CI networks; in that case, retry the same public RSS
URL through cors.dev's HTTPS fetch proxy.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

USER_ID = os.environ.get("GOODREADS_USER_ID", "34901135")
SHELVES = [
    "1st_priority",
    "next",
    "currently-reading",
    "to-read",
    "read",
    "audio",
]
BASE_URL = f"https://www.goodreads.com/review/list_rss/{USER_ID}"
PROXY_PREFIX = "https://proxy.cors.dev/"
OUT = Path("data/goodreads.json")
HISTORY = Path("data/history.jsonl")
MAX_PAGES_PER_SHELF = 20
DELAY_SECONDS = 1.0
USER_AGENT = "goodreads-reading-sync/1.1 (personal read-only shelf backup)"
ACCEPT = "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8"


def text(item: ET.Element, tag: str) -> str:
    node = item.find(tag)
    return (node.text or "").strip() if node is not None else ""


def parse_item(item: ET.Element) -> dict:
    # RSS fields vary by Goodreads endpoint/version. Preserve shelf labels and any
    # progress fields if Goodreads happens to expose them; never infer a percentage.
    shelf_text = text(item, "shelves") or text(item, "user_shelves")
    shelf_names = [part.strip() for part in shelf_text.replace("|", ",").split(",") if part.strip()]
    shelves_node = item.find("shelves")
    if shelves_node is not None:
        for node in shelves_node.findall(".//shelf"):
            name = (node.get("name") or (node.text or "")).strip()
            if name:
                shelf_names.append(name)
    shelf_names = list(dict.fromkeys(shelf_names))
    progress = {}
    for field in ("user_progress", "percent_complete", "reading_progress", "progress", "current_page", "pages_read"):
        value = text(item, field)
        if value:
            progress[field] = value

    return {
        "goodreads_book_id": text(item, "book_id"),
        "title": text(item, "title"),
        "author": text(item, "author_name"),
        "link": text(item, "link"),
        "isbn": text(item, "isbn"),
        "isbn13": text(item, "isbn13"),
        "user_rating": text(item, "user_rating"),
        "average_rating": text(item, "average_rating"),
        "pages": text(item, "num_pages"),
        "publication_year": text(item, "publication_year"),
        "cover_url": text(item, "book_image_url"),
        "date_added": text(item, "date_added"),
        "date_read": text(item, "date_read"),
        "shelves": shelf_names,
        "tags": shelf_names.copy(),
        "progress": progress or None,
    }


def _read_feed(url: str, *, via_proxy: bool) -> list[dict]:
    request_url = f"{PROXY_PREFIX}{url}" if via_proxy else url
    request = urllib.request.Request(
        request_url,
        headers={"User-Agent": USER_AGENT, "Accept": ACCEPT},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        body = response.read()
        status = response.status

    if status != 200:
        raise RuntimeError(f"HTTP {status}")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        preview = body[:160].decode("utf-8", errors="replace")
        raise RuntimeError(f"response was not valid RSS/XML ({preview!r})") from exc

    channel = root.find("channel")
    if channel is None:
        raise RuntimeError("response did not contain an RSS channel")
    return [parse_item(node) for node in channel.findall("item")]


def fetch_page(shelf: str, page: int) -> list[dict]:
    query = urllib.parse.urlencode({"shelf": shelf, "page": page})
    url = f"{BASE_URL}?{query}"
    try:
        return _read_feed(url, via_proxy=False)
    except (urllib.error.URLError, TimeoutError, RuntimeError) as direct_error:
        print(
            f"  Direct Goodreads feed unavailable for shelf={shelf!r}, page={page} "
            f"({type(direct_error).__name__}); retrying through public RSS proxy."
        )
        try:
            books = _read_feed(url, via_proxy=True)
            print(f"  Proxy fallback succeeded for shelf={shelf!r}, page={page}")
            return books
        except (urllib.error.URLError, TimeoutError, RuntimeError) as proxy_error:
            raise RuntimeError(
                f"Could not fetch shelf={shelf!r}, page={page} directly "
                f"({direct_error}) or through RSS proxy ({proxy_error})"
            ) from proxy_error


def fetch_shelf(shelf: str) -> list[dict]:
    books: list[dict] = []
    seen: set[str] = set()
    for page in range(1, MAX_PAGES_PER_SHELF + 1):
        items = fetch_page(shelf, page)
        added_this_page = 0
        for book in items:
            book_id = book["goodreads_book_id"] or book["link"] or book["title"]
            if not book_id or book_id in seen:
                continue
            seen.add(book_id)
            books.append(book)
            added_this_page += 1
        if not items or added_this_page == 0:
            break
        if len(items) < 100:
            break
        time.sleep(DELAY_SECONDS)
    else:
        print(f"Warning: shelf {shelf!r} reached the {MAX_PAGES_PER_SHELF}-page safety limit")
    return books


def main() -> None:
    # Fetch every shelf before writing anything. A failure must not replace a good snapshot
    # with a partial one that looks complete.
    shelves: dict[str, list[dict]] = {}
    for index, shelf in enumerate(SHELVES):
        print(f"Fetching Goodreads shelf: {shelf}")
        shelves[shelf] = fetch_shelf(shelf)
        print(f"  Retrieved {len(shelves[shelf])} unique books")
        # This is an intentionally small, curated queue. Goodreads can silently ignore
        # an unrecognized shelf parameter and return a much larger default list; fail
        # safely rather than mislabeling that list as the user's priority queue.
        if shelf == "1st_priority" and len(shelves[shelf]) > 200:
            raise RuntimeError(
                "The 1st_priority shelf returned more than 200 books; refusing to save "
                "a likely unfiltered/default feed. Check the exact Goodreads shelf name."
            )
        if index < len(SHELVES) - 1:
            time.sleep(DELAY_SECONDS)

    # Derive explicit memberships from the feeds we successfully fetched. This makes
    # custom shelves such as "audio" visible even when RSS omits shelf metadata on items.
    memberships: dict[str, set[str]] = {}
    for shelf_name, books in shelves.items():
        for book in books:
            book_id = book["goodreads_book_id"] or book["link"] or book["title"]
            if book_id:
                memberships.setdefault(book_id, set()).add(shelf_name)
    for books in shelves.values():
        for book in books:
            book_id = book["goodreads_book_id"] or book["link"] or book["title"]
            known = set(book.get("tags") or [])
            known.update(memberships.get(book_id, set()))
            book["tags"] = sorted(known)
            book["shelves"] = sorted(set(book.get("shelves") or []) | known)

    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot = {
        "schema_version": 2,
        "source": "Goodreads public shelf RSS",
        "progress_note": "Progress is recorded only when exposed by RSS; public shelf RSS may not provide current reading percentage or page.",
        "goodreads_user_id": USER_ID,
        "retrieved_at_utc": retrieved_at,
        "shelves": shelves,
        "shelf_counts": {name: len(books) for name, books in shelves.items()},
        "status": "success",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.parent.mkdir(parents=True, exist_ok=True)

    # History records only content changes, not a daily timestamp-only refresh.
    content_for_comparison = {
        "goodreads_user_id": USER_ID,
        "shelves": shelves,
        "shelf_counts": snapshot["shelf_counts"],
    }
    previous_content = None
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8"))
            previous_content = {
                "goodreads_user_id": previous.get("goodreads_user_id"),
                "shelves": previous.get("shelves"),
                "shelf_counts": previous.get("shelf_counts"),
            }
        except (json.JSONDecodeError, OSError):
            previous_content = None

    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if previous_content != content_for_comparison:
        with HISTORY.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "recorded_at_utc": retrieved_at,
                "change_type": "initial_snapshot" if previous_content is None else "shelf_content_changed",
                "shelf_counts": snapshot["shelf_counts"],
                "shelves": shelves,
            }, ensure_ascii=False, separators=(",", ":")) + "\n")
        print("Recorded a shelf-content change in data/history.jsonl")
    else:
        print("Shelf contents are unchanged; history was not extended.")

    print(f"Saved snapshot to {OUT} at {retrieved_at}")


if __name__ == "__main__":
    main()
