# Goodreads Reading Sync

A small, read-only sync that snapshots the public Goodreads shelves for the profile
[Omar Shafie](https://www.goodreads.com/user/show/34901135-omar-shafie).

## What it tracks

The daily sync prioritizes the custom shelves **`1st priority`** and **`next`**, and also captures:

- `currently-reading`
- `to-read`
- `read`

It writes:

- `data/goodreads.json` — latest successful snapshot, including the UTC retrieval time and per-shelf counts.
- `data/history.jsonl` — a history record when shelf contents change (not just when the timestamp changes).

The workflow runs daily at 05:17 UTC and can also be started manually from the **Actions** tab.

## How it works

Goodreads' retired public API is not used. The script reads the legacy public shelf RSS feeds, which do not require API keys for public shelves. Custom shelf names are URL-encoded automatically.

The script fetches all configured shelves before writing files. If any shelf request fails, the run fails and the last successful snapshot is preserved. It never writes to Goodreads.

## First run

1. Open the repository's **Actions** tab.
2. Select **Sync Goodreads shelves**.
3. Choose **Run workflow**.
4. Open the run and inspect its logs and the resulting `data/goodreads.json`.

If Goodreads blocks the feed or the profile/shelves are not public, the action will fail rather than replacing the snapshot with incomplete data.

## Limits and privacy

- This repository is public, so the resulting shelf snapshot and reading history are public too.
- Goodreads RSS feeds may limit the number of books returned per page. The script checks pages until the feed ends, with a safety limit of 20 pages per shelf.
- No credentials, API keys, or personal access tokens are required.
