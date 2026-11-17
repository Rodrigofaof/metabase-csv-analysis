"""Loads every CSV in ./data into PostgreSQL (schema public) and asks Metabase to
sync, so the tables show up right away in the SQL editor.

Usage:
    python load_csvs.py               # load everything in ./data
    python load_csvs.py path.csv      # load only the given files

Configuration (environment variables, defaults match docker-compose.yml):
    PG_URL    postgresql+psycopg2://postgres:metabase@localhost:5432/interview
    MB_URL    http://localhost:3000
    MB_USER   admin@example.com  Metabase admin login (only used for the sync step)
    MB_PASS   Interview2026!
"""
import csv
import os
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import create_engine

PG_URL = os.getenv("PG_URL", "postgresql+psycopg2://postgres:metabase@localhost:5432/interview")
MB_URL = os.getenv("MB_URL", "http://localhost:3000")
MB_USER = os.getenv("MB_USER", "admin@example.com")
MB_PASS = os.getenv("MB_PASS", "Interview2026!")

DATA_DIR = Path(__file__).parent / "data"


def snake(name: str) -> str:
    """'Order Date (UTC)' -> 'order_date_utc'"""
    name = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    if not name:
        name = "col"
    if name[0].isdigit():
        name = "c_" + name
    return name


def read_csv(path: Path) -> pd.DataFrame:
    """Auto-detects delimiter and encoding."""
    for enc in ("utf-8-sig", "latin-1"):
        try:
            with open(path, encoding=enc, newline="") as f:
                sample = f.read(64_000)
            try:
                sep = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                sep = ","
            return pd.read_csv(path, sep=sep, encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Could not read {path}")


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Converts text columns that look like dates (>=90% parseable)."""
    for col in df.columns:
        if not (pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col])):
            continue
        sample = df[col].dropna().astype(str).head(500)
        if sample.empty or not sample.str.contains(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}").mean() > 0.9:
            continue
        parsed = pd.to_datetime(df[col], errors="coerce", format="mixed")
        if parsed.notna().mean() >= 0.9 * df[col].notna().mean():
            df[col] = parsed
    return df


def dedupe(cols):
    seen, out = {}, []
    for c in cols:
        if c in seen:
            seen[c] += 1
            c = f"{c}_{seen[c]}"
        else:
            seen[c] = 0
        out.append(c)
    return out


def sync_metabase():
    if not (MB_USER and MB_PASS):
        print("Metabase sync skipped (set MB_USER / MB_PASS), or use Admin > Databases > Sync.")
        return
    try:
        s = requests.Session()
        tok = s.post(f"{MB_URL}/api/session", json={"username": MB_USER, "password": MB_PASS}, timeout=10).json()["id"]
        s.headers["X-Metabase-Session"] = tok
        for db in s.get(f"{MB_URL}/api/database", timeout=10).json()["data"]:
            if db["engine"] == "postgres":
                s.post(f"{MB_URL}/api/database/{db['id']}/sync_schema", timeout=10)
                print(f"Metabase: schema sync requested for '{db['name']}'.")
    except Exception as e:  # Metabase not running, wrong credentials, etc.
        print(f"(Warning) Metabase sync failed: {e}. Use Admin > Databases > Sync.")


def main():
    files = [Path(p) for p in sys.argv[1:]] or sorted(DATA_DIR.glob("*.csv"))
    if not files:
        print(f"No CSV files found in {DATA_DIR}")
        return
    engine = create_engine(PG_URL)
    for path in files:
        df = read_csv(path)
        df.columns = dedupe([snake(c) for c in df.columns])
        df = parse_dates(df)
        table = snake(path.stem)
        df.to_sql(table, engine, if_exists="replace", index=False, chunksize=5000, method="multi")
        print(f"{path.name:40s} -> {table:30s} {len(df):>9,} rows, {len(df.columns)} columns")
        print("   " + ", ".join(f"{c}:{t}" for c, t in df.dtypes.astype(str).items()))
    sync_metabase()


if __name__ == "__main__":
    main()
