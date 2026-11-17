# CSV Analysis with Metabase

Analysis of CSV files with **PostgreSQL** + **Metabase**. Everything is reproducible: one script
loads the data, configures a fresh Metabase and recreates every question and dashboard.

```
data/*.csv ──► PostgreSQL ◄── Metabase ◄── dashboards/metabase_export.json
             (load_csvs.py)            (metabase_io.py import)
```

## Reproduce the dashboards

You need **Python 3.10+** and either **Docker** (option A) or a local Java + PostgreSQL (option B).

### 1. Start PostgreSQL and Metabase

**Option A — Docker (easiest)**

```bash
docker compose up -d
```

**Option B — without Docker**

- Install [Java 21+](https://adoptium.net/) and [PostgreSQL 16](https://www.postgresql.org/download/).
- Create the database: `CREATE DATABASE interview;` (user `postgres`, password `metabase`,
  or point `PG_URL` at your own credentials, see [Configuration](#configuration)).
- Download Metabase **v0.65.4** from
  [https://downloads.metabase.com/v0.65.4/metabase.jar](https://downloads.metabase.com/v0.65.4/metabase.jar) into `metabase/metabase.jar`.
- Start it: `start-metabase.bat` (Windows) or `./start-metabase.sh` (macOS/Linux).

### 2. Load the data and recreate the dashboards

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python metabase_io.py import
```

This single command:

1. loads every CSV in `data/` into PostgreSQL (one table per file);
2. waits for Metabase, creates the admin user (UI in English) and connects it to PostgreSQL;
3. recreates all questions and dashboards from `dashboards/metabase_export.json`
   in the **Interview Analysis** collection.

### 3. Open Metabase

Go to [http://localhost:3000](http://localhost:3000) and log in with **`admin@example.com` / `Interview2026!`**.
The script prints the direct link to each dashboard.

---

## Repository layout

| Path                                | Purpose                                                                   |
| ----------------------------------- | ------------------------------------------------------------------------- |
| `data/`                           | Input CSV files                                                           |
| `dashboards/metabase_export.json` | Questions + dashboards exported from Metabase (portable, no internal ids) |
| `sql/`                            | SQL queries used in the analysis                                          |
| `load_csvs.py`                    | CSV → PostgreSQL loader                                                  |
| `metabase_io.py`                  | Export / import of Metabase questions and dashboards                      |
| `docker-compose.yml`              | PostgreSQL 16 + Metabase v0.65.4                                          |
| `start-metabase.bat` / `.sh`    | Run Metabase from the JAR without Docker                                  |

## Updating the analysis (author workflow)

1. Drop new CSVs into `data/` and run `python load_csvs.py`
   (or `python load_csvs.py data/file.csv` for a single file).
2. Build questions and dashboards in Metabase.
3. Export them into the repository and commit:
   ```bash
   python metabase_io.py export
   git add -A && git commit -m "Update analysis" && git push
   ```

Only content that uses the PostgreSQL database is exported (Metabase's built-in examples are
ignored). Questions built with the visual editor and with SQL are both supported, including
filters, text cards, tabs and questions based on other questions.

### How the CSV loader works

- auto-detects delimiter (`,` `;` tab `|`) and encoding (UTF-8 / Latin-1);
- converts column names to `snake_case` (`Order Date` → `order_date`);
- parses date-like text columns as timestamps;
- table name = file name in `snake_case`; existing tables are replaced.

## Configuration

All settings are environment variables; the defaults match `docker-compose.yml`.

| Variable                  | Default                                                              | Used for                               |
| ------------------------- | -------------------------------------------------------------------- | -------------------------------------- |
| `PG_URL`                | `postgresql+psycopg2://postgres:metabase@localhost:5432/interview` | Loading CSVs                           |
| `MB_URL`                | `http://localhost:3000`                                            | Metabase API                           |
| `MB_USER` / `MB_PASS` | `admin@example.com` / `Interview2026!`                           | Metabase admin login                   |
| `MB_PG_HOST`            | auto (`localhost`, then `postgres`)                              | Host Metabase uses to reach PostgreSQL |

```bash
# Windows PowerShell
$env:PG_URL="postgresql+psycopg2://user:password@localhost:5432/mydb"
# macOS/Linux
export PG_URL=postgresql+psycopg2://user:password@localhost:5432/mydb
```

## Troubleshooting

- **Port 5432 already in use** (a local PostgreSQL is running): start Docker's PostgreSQL on
  another port and point the scripts at it:
  ```powershell
  # Windows PowerShell
  $env:PG_PORT="5433"; docker compose up -d
  $env:PG_URL="postgresql+psycopg2://postgres:metabase@localhost:5433/interview"
  python metabase_io.py import
  ```
  ```bash
  # macOS/Linux
  PG_PORT=5433 docker compose up -d
  export PG_URL=postgresql+psycopg2://postgres:metabase@localhost:5433/interview
  python metabase_io.py import
  ```
- **No `dashboards/metabase_export.json` yet:** `import` still loads the data and configures
  Metabase; only the dashboard step is skipped.
- **Metabase takes a while to start** the first time (~1–2 min); the import script waits for it.
- **Running the import again** archives the previous *Interview Analysis* collection and
  recreates it, so it is safe to repeat.
