# Real-Time Environment Control Data Dashboard

A [Streamlit](https://streamlit.io/) dashboard for researchers studying environmental
conditions (temperature, humidity, and equipment on/off cycles) in a Black Soldier Fly
(BSF) farm. Sensor devices write readings into MongoDB; the dashboard reads that data
and turns it into readable trends, live snapshots, and variable-to-variable comparisons.

## 1. How it works

### Data flow

```
Sensor devices (per cage) --> MongoDB Atlas ("devices.records" collection)
                                        |
                                        v
                         4_scripts/dashboard_v3.py (Streamlit app)
                                        |
                                        v
                        Browser: charts, snapshots, correlations, CSV export
```

Each cage's controller writes one document per reading. A document looks like this:

```json
{
  "_id": "68590b357854d2cb24b1d10d",
  "ts": 1750666036.95,
  "env_id": 1,
  "env_type": "cage",
  "t": 26.6,
  "h": 65.8,
  "intake": false,
  "exhaust": true,
  "atomizer": false,
  "heating": false
}
```

| Field | Meaning |
|---|---|
| `ts` | Unix timestamp (seconds) of the reading |
| `env_id` | Which cage/enclosure the reading belongs to |
| `env_type` | Type of enclosure (currently always `"cage"`) |
| `t` | Temperature (°C) |
| `h` | Humidity (%) |
| `intake`, `exhaust`, `atomizer`, `heating` | On/off state of each piece of climate-control equipment |

The dashboard doesn't hardcode this schema beyond `t`/`h`/`env_id`. On every load it
inspects whatever fields are present and sorts them automatically:

- Fields that only ever hold `True`/`False` are treated as **equipment fields** — the
  dashboard reports these as a **duty-cycle percentage** (share of a time period the
  equipment was on) once you aggregate above "Raw".
- Numeric fields (like `t`, `h`) are treated as **continuous measurements** and averaged
  over a period instead.
- Anything unexpected (e.g. a field that occasionally holds a list/array instead of a
  plain value) is skipped rather than crashing the app, and is listed in the sidebar so
  it's not silently ignored.

This means adding a new sensor or a new piece of equipment on the device side generally
requires **no dashboard code changes** — it shows up automatically as a new variable you
can filter, chart, and compare.

### The three analysis modes

The sidebar lets you pick what you're trying to do:

- **General Analysis** — every selected variable plotted over time, one row per
  variable, colored by cage. You choose a **time resolution** (Raw / 15-minute average /
  Hourly average / Daily average) and a **smoothness** level (a rolling average applied
  on top, for oscillating data that's still noisy even after aggregating). Also includes
  a summary statistics table and a CSV download of exactly what's plotted.
- **Last Update** — a live snapshot per cage: latest temperature/humidity, current
  equipment on/off state, and how long ago the reading came in (with a warning if a cage
  hasn't reported recently). You can check the latest reading within your selected time
  range, or the single latest reading ever recorded, regardless of the date filter.
- **Compare Variables** — a correlation matrix across every selected variable, plus a
  focused scatter plot and Pearson correlation coefficient for any two variables you
  pick (e.g. temperature vs. humidity, or temperature vs. heating duty cycle).

### Performance

The dashboard caches the MongoDB connection and the fetched data (`st.cache_resource` /
`st.cache_data`). Only changing the time range triggers a new database query; switching
modes, filters, or smoothing settings re-uses already-fetched data, which is why the
first load of a time range is the slow step and everything after it should be fast.

### Project history

The dashboard evolved through three versions (`4_scripts/dashboard_v1.py` →
`dashboard_v2.py` → `dashboard_v3.py`), moving from local `.env` file credentials to
Streamlit's `secrets.toml` mechanism so it could be deployed on Streamlit Community
Cloud. `dashboard_v3.py` is the current, actively developed version — `v1`/`v2` are kept
for reference only and are **not** guaranteed to run against the current
`requirements.txt` (it's trimmed to just what `v3` needs). `3_notebooks/1_extract.ipynb`
is the original notebook used to explore the MongoDB schema and connection before the
dashboard existed.

### Branding

The app is styled black/green as a Tryento-branded tool rather than a default-looking
Streamlit app:

- `.streamlit/config.toml` sets the base dark theme (background, accent green, text
  color) — this is Streamlit's official theming mechanism, so it applies consistently
  whether run locally or on Streamlit Community Cloud.
- `4_scripts/dashboard_v3.py` injects additional CSS on top (custom header, hidden
  Streamlit menu/footer, styled metrics/buttons) and loads the icon mark from
  `img/logo.png`, used both as the browser favicon and next to the "Tryento" text
  wordmark in the page header. If that file is ever missing, it falls back to an emoji
  favicon and a text-only wordmark — replace `img/logo.png` to update the branding, no
  code changes needed.

## 2. Repository structure

```
.
├── .streamlit/
│   └── config.toml          # Theme (dark + green) and server settings — safe to commit
├── img/
│   └── logo.png             # Tryento icon mark — used as favicon + header badge
├── 3_notebooks/
│   └── 1_extract.ipynb      # Exploratory notebook: MongoDB connection + schema check
├── 4_scripts/
│   ├── dashboard_v1.py      # Original version (local .env credentials) — reference only
│   ├── dashboard_v2.py      # Second iteration — reference only
│   └── dashboard_v3.py      # Current dashboard — run this one
├── requirements.txt         # Python dependencies (for dashboard_v3.py)
└── LICENSE
```

## 3. Running it locally

### Prerequisites

- Python 3.11+
- `pip`
- `git`
- Access to the project's MongoDB Atlas cluster (ask a maintainer for read credentials),
  **or** your own MongoDB instance seeded with documents matching the schema above (see
  [section 4](#4-testing-without-the-real-database)).

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/Tryento/tryento-data-dash.git
cd tryento-data-dash

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

### Configure database credentials

The dashboard reads its MongoDB credentials from Streamlit's secrets file, which is
**not** committed to git (it holds a real password). Create it yourself:

```bash
mkdir .streamlit   # if it doesn't already exist
```

Create `.streamlit/secrets.toml` in the repo root with:

```toml
[database]
user = "your_mongodb_username"
password = "your_mongodb_password"
host = "cluster0.yrpctoh.mongodb.net"   # or your own cluster's host
```

Without this file (or with it missing the `user`/`password` keys), the app stops with
"Database credentials missing" instead of trying to connect.

### Run it

```bash
streamlit run 4_scripts/dashboard_v3.py
```

Streamlit will print a local URL (typically `http://localhost:8501`) — open it in your
browser.

## 4. Testing without the real database

If you don't have credentials for the production cluster, you can point `host` (and
`user`/`password`) at your own free [MongoDB Atlas](https://www.mongodb.com/cloud/atlas)
cluster, or a local MongoDB instance. Either way, the database must be named `devices`
with a collection named `records`. To seed it with a few days of realistic-looking test
data, run something like:

```python
import random
import time
from pymongo import MongoClient

client = MongoClient("<your connection string>")
records = client.devices.records

now = time.time()
docs = []
for cage in (1, 2, 3):
    state = {"intake": False, "exhaust": False, "atomizer": False, "heating": False}
    for minutes_ago in range(0, 3 * 24 * 60, 5):  # 3 days of data, every 5 minutes
        for k in state:
            if random.random() < 0.05:
                state[k] = not state[k]
        docs.append({
            "ts": now - minutes_ago * 60,
            "env_id": cage,
            "env_type": "cage",
            "t": 27 + random.uniform(-3, 3),
            "h": 65 + random.uniform(-10, 10),
            **state,
        })

records.insert_many(docs)
```

## 5. Production readiness

Before launching this for company-wide use, note what's already in place and what's
still worth deciding on:

**Already handled:**
- **Pinned dependencies** (`requirements.txt`) so a fresh deploy installs the exact
  versions this was tested against, not whatever is newest that day.
- **Fast failure on database issues**: the MongoDB client has an 8-second connection/
  server-selection timeout, so an unreachable cluster surfaces an error in ~8s instead
  of hanging for pymongo's default ~30s.
- **No internal details leaked to end users**: unexpected errors show a plain, generic
  message in the UI; the full exception (including anything that might reveal
  connection details or query internals) is sent to the server-side log via Python's
  `logging` module instead — visible in Streamlit Cloud's **"Manage app" → logs** panel,
  not to whoever is looking at the dashboard.
- **Caching** (`st.cache_resource` / `st.cache_data`) so normal use (switching modes,
  filters, smoothing) doesn't repeatedly hit the database.
- **Responsive layout**: multi-column sections (KPI cards, side-by-side pickers) wrap
  onto multiple rows on narrow screens instead of squeezing into unreadable slivers, and
  header/metric text scales down below 640px width.
- **Secrets hygiene**: `.streamlit/secrets.toml` is gitignored; see the security note at
  the end of this file if a credential is ever accidentally exposed.

**Worth deciding before/at launch:**
- **Who can access the app.** Streamlit Community Cloud apps are public by default (a
  private-viewer allowlist is a paid feature). If this dashboard shouldn't be open to
  anyone with the URL, that changes the hosting choice — see the note at the end of
  section 6 below.
- **MongoDB Atlas network access list.** Make sure the cluster's IP allowlist includes
  `0.0.0.0/0` (or Streamlit Cloud's egress IPs specifically) — otherwise the deployed app
  won't be able to reach the database even with correct credentials.
- **Database user permissions.** The credentials in `secrets.toml` should be a
  **read-only** MongoDB user scoped to just the `devices` database if possible, since
  this app never needs to write data.
- **Who owns the Streamlit Cloud account** the app is deployed under, and whether that's
  a shared company account vs. a personal one someone might leave.

## 6. Deploying (Streamlit Community Cloud)

This app is a **Streamlit app**, not a static site — it needs a persistent Python
process to serve it, so it can't run on static/serverless hosts like Netlify or Vercel.
[Streamlit Community Cloud](https://streamlit.io/cloud) is the natural home for it: it's
free, built specifically for Streamlit apps, and the app already targets it via
`st.secrets`.

1. **Push this repo to GitHub** (it already lives at
   `github.com/Tryento/tryento-data-dash`, so this step may already be done — just make
   sure your latest changes are pushed).
2. Go to **[share.streamlit.io](https://share.streamlit.io)** and sign in with GitHub.
3. Click **"New app"**, then pick:
   - Repository: `Tryento/tryento-data-dash`
   - Branch: whichever branch you want live (e.g. `main`)
   - Main file path: `4_scripts/dashboard_v3.py`
4. Before (or right after) deploying, open **"Advanced settings" → "Secrets"** and paste
   in the same content as your local `.streamlit/secrets.toml`:
   ```toml
   [database]
   user = "your_mongodb_username"
   password = "your_mongodb_password"
   host = "cluster0.yrpctoh.mongodb.net"
   ```
5. Click **Deploy**. Streamlit installs `requirements.txt` and starts the app — you'll
   get a URL like `https://<your-app-name>.streamlit.app`.
6. Any time you push new commits to the deployed branch, the app redeploys
   automatically. Updating secrets later is done from the app's **Settings → Secrets**
   panel in the Streamlit Cloud dashboard (never commit them to git).

By default the deployed app is **public to anyone with the URL** — Streamlit Community
Cloud's free tier doesn't support a private-viewer allowlist (that's a paid "Streamlit
in Snowflake" / private-cloud feature). If this needs to stay internal to the company,
options are: keep the URL unlisted and treat it like an unlisted doc (simplest, but not
real access control), or move to a host that supports it — a container host (Render,
Railway, Fly.io) behind a company VPN or with basic-auth in front, for example.

A custom domain (instead of `*.streamlit.app`) also isn't available on the free tier.
If either of those becomes a requirement, the alternative is a container host that keeps
a persistent process running — e.g. Render, Railway, or Fly.io — which support custom
domains and access control but need a bit more setup (a `Dockerfile` or
platform-specific build config). Ask if you want help setting one of those up.

## 7. Troubleshooting

| Symptom | Likely cause |
|---|---|
| "Database credentials missing" | `.streamlit/secrets.toml` doesn't exist or is missing the `user`/`password` keys. |
| "MongoDB connection failed" | Wrong host/credentials, or your IP isn't in the Atlas cluster's network access list. |
| "No data available for the selected time range" | The date range doesn't overlap any documents — try "Last 30 days" or a wider custom range. |
| Dashboard feels slow | Only the *first* load of a given time range hits the database; subsequent interactions (filters, modes, smoothing) should be fast thanks to caching. If it's still slow, the time range may be returning a very large number of documents — try a shorter range. |

## Security note

`secrets.toml` contains a real database password and must never be committed. It's
already listed in `.gitignore`. If you ever suspect a credential has been committed or
leaked, rotate it in MongoDB Atlas immediately.
