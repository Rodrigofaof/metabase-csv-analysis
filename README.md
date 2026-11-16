# CSV Analysis with Metabase

Local analytics environment used for a data-analysis interview: CSV files are loaded
into **PostgreSQL** and explored with **Metabase** (questions, charts and dashboards).

```
data/*.csv  ──(load_csvs.py)──►  PostgreSQL  ◄──  Metabase (http://localhost:3000)
```

## Repository layout

| Path | Purpose |
|------|---------|
| `data/` | Input CSV files (`sample_sales.csv` is a small test file) |
| `load_csvs.py` | Loads every CSV in `data/` into PostgreSQL (one table per file) |
| `sql/` | SQL queries used for the analysis |
| `docker-compose.yml` | PostgreSQL + Metabase in one command (recommended) |
| `start-metabase.bat` / `.sh` | Run Metabase from the JAR without Docker |
| `requirements.txt` | Python dependencies for the loader |

---

## Option A — Docker (recommended)

**Requirements:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) and Python 3.10+.

```bash
git clone <this-repo-url>
cd <repo-folder>

# 1. Start PostgreSQL + Metabase
docker compose up -d

# 2. Load the CSVs into PostgreSQL
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python load_csvs.py
```

Then open <http://localhost:3000> (first start takes ~1 minute) and continue with
[First-time Metabase setup](#first-time-metabase-setup). When adding the database, use
**Host `postgres`** (the Docker service name).

Stop everything with `docker compose down` (add `-v` to also delete the data).

## Option B — Without Docker

**Requirements:**
- Java 21+ ([Eclipse Temurin](https://adoptium.net/))
- PostgreSQL 14+ ([download](https://www.postgresql.org/download/))
- Python 3.10+

1. Create the database (user `postgres`, password `metabase`, or adjust `PG_URL` below):
   ```sql
   CREATE DATABASE interview;
   ```
2. Download the Metabase JAR from <https://www.metabase.com/start/oss/jar> and save it as
   `metabase/metabase.jar`.
3. Start Metabase:
   - Windows: double-click `start-metabase.bat`
   - macOS/Linux: `./start-metabase.sh`
4. Load the CSVs (same as Option A, step 2).

When adding the database in Metabase, use **Host `localhost`**.

---

## First-time Metabase setup

1. Open <http://localhost:3000> and create your admin account.
2. Add a database → **PostgreSQL**:

   | Field | Value |
   |-------|-------|
   | Host | `postgres` (Docker) or `localhost` (no Docker) |
   | Port | `5432` |
   | Database name | `interview` |
   | Username / Password | `postgres` / `metabase` |

3. Tables appear under **Browse data**; use **New → SQL query** or **New → Question**
   to build charts, and **New → Dashboard** to combine them.

## Loading new CSVs

Drop the files into `data/` and run:

```bash
python load_csvs.py                    # every CSV in data/
python load_csvs.py data/orders.csv    # only specific files
```

The loader:
- auto-detects delimiter (`,` `;` tab `|`) and encoding (UTF-8 / Latin-1);
- converts column names to `snake_case` (`Order Date` → `order_date`);
- parses date-like text columns as timestamps;
- replaces the table if it already exists (table name = file name in `snake_case`).

To make the new tables appear in Metabase immediately, set your Metabase credentials and
the loader will trigger a schema sync (otherwise use **Admin → Databases → Sync**):

```bash
# Windows PowerShell
$env:MB_USER="you@example.com"; $env:MB_PASS="your-password"
# macOS/Linux
export MB_USER=you@example.com MB_PASS=your-password
```

### Configuration

| Variable | Default |
|----------|---------|
| `PG_URL` | `postgresql+psycopg2://postgres:metabase@localhost:5432/interview` |
| `MB_URL` | `http://localhost:3000` |
| `MB_USER` / `MB_PASS` | empty (sync skipped) |

## Troubleshooting

- **Port 5432 already in use:** a local PostgreSQL is running. Stop it, or change the
  mapping in `docker-compose.yml` to `"5433:5432"` and set
  `PG_URL=postgresql+psycopg2://postgres:metabase@localhost:5433/interview`.
- **Metabase page does not load:** wait for the first start (`docker compose logs -f metabase`).
- **Tables missing in Metabase:** Admin → Databases → your database → *Sync database schema now*.
