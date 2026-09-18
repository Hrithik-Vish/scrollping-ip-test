# ScrollPing IP viability test — setup & readout guide

## What this is
A throwaway test harness, separate from the real ScrollPing codebase, to
answer: do asurascans / hivetoons / kunmanga (and secondarily mgeko /
mangadex / vortexscans) block requests from GitHub-hosted Actions runner
IPs, and if so, immediately or after repeated hits?

## Where to put these files
Two options — pick whichever is less disruptive to your real repo:

1. **New throwaway repo** (recommended): create a fresh public repo just
   for this test, e.g. `scrollping-ip-test`. Put `ip_test.py` at the repo
   root and `.github/workflows/ip-test.yml` at
   `.github/workflows/ip-test.yml`. Delete the whole repo once the test
   window is done.
2. **A branch on your real repo**: put `ip_test.py` in a `test/` folder
   and the workflow file in `.github/workflows/`, on a branch you don't
   merge to main. If you do this, drop the `working-directory:
   scrollping-test` lines in the workflow and adjust paths to match
   wherever you place the files.

Don't mix this into your real `main.py` pipeline or `scraper_logs` table —
it's deliberately separate so you're not touching the actual app while
gathering data.

## Running it
- Push the repo/branch with both files in place.
- Go to the Actions tab → "ScrollPing IP Viability Test" → "Run workflow"
  to trigger it manually once, just to confirm it runs end to end and
  commits a `results.csv` with 6 rows.
- After that, it fires automatically every hour via the cron schedule.
  Just leave it running for 1-3 days. No need to touch anything.

## While it's running
- Every run appends 6 rows (one per site) to `results.csv` and commits
  that file back to the repo — you'll see the commit history fill up in
  the repo automatically.
- If a run fails to commit (e.g. the CSV changed at the exact same moment
  from two runs, unlikely but possible), that specific hour's data point
  is lost — with hourly runs over 1-3 days you'll have plenty of data
  regardless of the occasional gap.

## Reading results.csv after the window closes
Columns, and what to actually look at:

- **status_code** — `200` is a request that went through; `EXCEPTION`
  means the request itself failed (timeout/connection refused), which is
  a different failure mode than being served a block page.
- **response_length** — real homepage/category HTML is normally tens of
  KB. A `200` with a tiny `response_length` is a red flag even though the
  status code looks fine.
- **looks_blocked** — a heuristic (checks for text like "checking your
  browser", "captcha", "cloudflare", or a too-short response). Not proof
  by itself — treat it as a flag to go look at that row more closely, not
  a verdict.
- **found_links** — the real signal. This reuses the same chapter-link
  regex as your actual `parsing.py`. A `200` status with `found_links: 0`
  usually means you got a challenge page or the site's layout doesn't
  match your regex — either way, that hour's fetch wouldn't have worked
  for the real scraper even though the HTTP request "succeeded."

### Computing your pass rate per site
Easiest done by opening results.csv in Excel/Sheets or a quick pandas
one-liner once the window's done:

```python
import pandas as pd
df = pd.read_csv("results.csv")
df["success"] = (df["status_code"] == 200) & (df["found_links"] > 0) & (~df["looks_blocked"])
print(df.groupby("site_name")["success"].mean() * 100)
```

That gives you a success percentage per site. Compare against the
threshold from your earlier plan:
- **>= 90%** — clean, no anti-bot needed
- **70-90%** — borderline; check if failures cluster in bursts (rate
  limiting, might fix with a longer interval) or are scattered across the
  whole window (persistent detection — zenrows candidate)
- **< 70%** — treat as blocked; this is where your limited zenrows budget
  should go, prioritized to asurascans / hivetoons / kunmanga first since
  those are your core sites

Also worth eyeballing: does a site's success rate *decay* over the 3 days
(starts at 100%, drops to 40% by day 3)? That pattern means the block is
tightening with volume, which is a more urgent signal than a site that's
just steadily mediocre the whole time.
