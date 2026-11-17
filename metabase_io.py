"""Export / import Metabase questions and dashboards so anyone can reproduce them.

    python metabase_io.py export   # from YOUR Metabase -> dashboards/metabase_export.json
    python metabase_io.py import   # into a fresh Metabase: loads CSVs, creates the admin user,
                                   # connects PostgreSQL and recreates every question/dashboard

Metabase stores internal numeric ids (tables, columns, questions). The export replaces them
with portable names ({"__table__": "public.sales"}, {"__field__": ["public.sales", "amount"]})
and the import resolves those names against the target instance, so it works on any machine.

Configuration (environment variables):
    MB_URL     http://localhost:3000
    MB_USER    admin@example.com    admin login (created by `import` on a fresh Metabase)
    MB_PASS    Interview2026!
    PG_URL     see load_csvs.py
    MB_PG_HOST host Metabase uses to reach PostgreSQL (auto-detected: localhost, postgres, ...)
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from sqlalchemy.engine import make_url

import load_csvs

MB_URL = load_csvs.MB_URL
MB_USER = load_csvs.MB_USER
MB_PASS = load_csvs.MB_PASS
PG = make_url(load_csvs.PG_URL)

EXPORT_FILE = Path(__file__).parent / "dashboards" / "metabase_export.json"
COLLECTION = "Interview Analysis"
DB_NAME = "Interview (Postgres)"


# --------------------------------------------------------------------------- API client
class Metabase:
    def __init__(self, url=MB_URL):
        self.url = url.rstrip("/")
        self.s = requests.Session()

    def call(self, method, path, **kw):
        r = self.s.request(method, f"{self.url}/api{path}", timeout=120, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else None

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None):
        return self.call("POST", path, json=body or {})

    def put(self, path, body):
        return self.call("PUT", path, json=body)

    def wait_until_up(self, timeout=300):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if requests.get(f"{self.url}/api/health", timeout=5).json().get("status") == "ok":
                    return
            except requests.RequestException:
                pass
            print("Waiting for Metabase to start...")
            time.sleep(5)
        sys.exit(f"Metabase is not reachable at {self.url}")

    def login(self, user=MB_USER, password=MB_PASS):
        r = self.s.post(f"{self.url}/api/session", json={"username": user, "password": password}, timeout=30)
        if r.status_code >= 400:
            sys.exit(f"Login failed for {user}: set MB_USER / MB_PASS to your Metabase admin login.")
        self.s.headers["X-Metabase-Session"] = r.json()["id"]

    def version(self):
        return self.get("/session/properties")["version"]["tag"]


def postgres_dbs(mb):
    return [d for d in mb.get("/database")["data"] if d["engine"] == "postgres"]


def id_maps(mb, db_id):
    """table id -> 'schema.table', field id -> ['schema.table', 'column'] (and the reverse)."""
    meta = mb.get(f"/database/{db_id}/metadata", params={"include_hidden": "true"})
    tables, fields = {}, {}
    for t in meta["tables"]:
        tname = f"{t['schema']}.{t['name']}"
        tables[t["id"]] = tname
        for f in t["fields"]:
            fields[f["id"]] = (tname, f["name"])
    return tables, fields


# --------------------------------------------------------------------------- id <-> name
def to_portable(x, tables, fields, cards):
    def field(i):
        if i not in fields:
            raise KeyError(f"field id {i} does not belong to the exported database")
        return {"__field__": list(fields[i])}

    def card(i):
        return {"__card__": f"card-{i}"} if i in cards else i

    def walk(x):
        if isinstance(x, dict):
            out = {}
            for k, v in x.items():
                if isinstance(k, str) and k.startswith("["):  # column_settings keys are JSON strings
                    try:
                        k = "__json__" + json.dumps(walk(json.loads(k)))
                    except (ValueError, KeyError):
                        pass
                if k in ("source-table", "table_id") and isinstance(v, int):
                    out[k] = {"__table__": tables[v]}
                elif k in ("source-field", "field_id", "field-id") and isinstance(v, int):
                    out[k] = field(v)
                elif k in ("source-card", "card_id", "card-id") and isinstance(v, int):
                    out[k] = card(v)
                elif k == "database" and isinstance(v, int):
                    out[k] = {"__database__": True}
                else:
                    out[k] = walk(v)
            return out
        if isinstance(x, list):
            x = list(x)
            if x and x[0] == "field":  # legacy ["field", id, opts] and new ["field", opts, id]
                for i in (1, 2):
                    if i < len(x) and isinstance(x[i], int):
                        x[i] = field(x[i])
            elif x and x[0] == "metric":  # metrics are cards
                for i in (1, 2):
                    if i < len(x) and isinstance(x[i], int):
                        x[i] = card(x[i])
            return [walk(i) for i in x]
        return x

    return walk(x)


def from_portable(x, db_id, tables, fields, cards):
    def walk(x):
        if isinstance(x, dict):
            if set(x) == {"__field__"}:
                key = tuple(x["__field__"])
                if key not in fields:
                    sys.exit(f"Column {key[0]}.{key[1]} not found in Metabase. Was the CSV loaded?")
                return fields[key]
            if set(x) == {"__table__"}:
                if x["__table__"] not in tables:
                    sys.exit(f"Table {x['__table__']} not found in Metabase. Was the CSV loaded?")
                return tables[x["__table__"]]
            if set(x) == {"__card__"}:
                return cards[x["__card__"]]
            if set(x) == {"__database__"}:
                return db_id
            out = {}
            for k, v in x.items():
                if k.startswith("__json__"):
                    k = json.dumps(walk(json.loads(k[8:])), separators=(",", ":"))
                out[k] = walk(v)
            return out
        if isinstance(x, list):
            return [walk(i) for i in x]
        return x

    return walk(x)


def card_refs(obj):
    """Keys of other exported cards this object depends on."""
    found = set()

    def walk(x):
        if isinstance(x, dict):
            if set(x) == {"__card__"}:
                found.add(x["__card__"])
            for k, v in x.items():
                if isinstance(k, str) and k.startswith("__json__"):
                    walk(json.loads(k[8:]))
                walk(v)
        elif isinstance(x, list):
            for i in x:
                walk(i)

    walk(obj)
    return found


# --------------------------------------------------------------------------- export
CARD_KEYS = ("name", "description", "display", "type", "dataset_query", "visualization_settings", "parameters")
DASHCARD_KEYS = ("row", "col", "size_x", "size_y", "parameter_mappings", "visualization_settings")


def export(args):
    mb = Metabase()
    mb.wait_until_up()
    mb.login()
    dbs = postgres_dbs(mb)
    if args.database:
        dbs = [d for d in dbs if d["name"] == args.database]
    if len(dbs) != 1:
        sys.exit("Found %d PostgreSQL databases in Metabase; choose one with --database: %s"
                 % (len(dbs), [d["name"] for d in postgres_dbs(mb)]))
    db = dbs[0]
    tables, fields = id_maps(mb, db["id"])

    cards = {c["id"]: c for c in mb.get("/card") if c["database_id"] == db["id"] and not c.get("archived")}
    out_cards = []
    for cid in sorted(cards):
        c = mb.get(f"/card/{cid}")
        out_cards.append({"key": f"card-{cid}",
                          **to_portable({k: c.get(k) for k in CARD_KEYS}, tables, fields, cards)})

    out_dash = []
    for d in mb.get("/dashboard"):
        d = mb.get(f"/dashboard/{d['id']}")
        dcs = d.get("dashcards", [])
        used = [dc["card_id"] for dc in dcs if dc.get("card_id")]
        if not used or any(cid not in cards for cid in used):
            continue  # dashboard is empty or uses another database (e.g. Metabase examples)
        out_dash.append(to_portable({
            "name": d["name"],
            "description": d.get("description"),
            "parameters": d.get("parameters", []),
            "tabs": [{"id": t["id"], "name": t["name"]} for t in d.get("tabs", [])],
            "dashcards": [{
                "card_id": dc.get("card_id"),
                "dashboard_tab_id": dc.get("dashboard_tab_id"),
                "series": [s["id"] for s in dc.get("series", [])],
                **{k: dc.get(k) for k in DASHCARD_KEYS},
            } for dc in dcs],
        }, tables, fields, cards))

    EXPORT_FILE.parent.mkdir(exist_ok=True)
    EXPORT_FILE.write_text(json.dumps({
        "metabase_version": mb.version(),
        "source_database": db["name"],
        "cards": out_cards,
        "dashboards": out_dash,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Exported {len(out_cards)} questions and {len(out_dash)} dashboards from '{db['name']}' "
          f"to {EXPORT_FILE.relative_to(Path.cwd()) if EXPORT_FILE.is_relative_to(Path.cwd()) else EXPORT_FILE}")
    for d in out_dash:
        print("   dashboard:", d["name"])


# --------------------------------------------------------------------------- import
def setup_or_login(mb):
    props = mb.get("/session/properties")
    if props.get("has-user-setup"):
        mb.login()
        return
    r = mb.post("/setup", {
        "token": props["setup-token"],
        "user": {"email": MB_USER, "password": MB_PASS, "first_name": "Admin", "last_name": "User",
                 "site_name": "Interview"},
        "prefs": {"site_name": "Interview", "site_locale": "en", "allow_tracking": False},
    })
    mb.s.headers["X-Metabase-Session"] = r["id"]
    print(f"Created Metabase admin user {MB_USER}")


def connect_postgres(mb):
    for d in postgres_dbs(mb):
        if d["details"].get("dbname") == PG.database:
            print(f"Using existing Metabase database '{d['name']}'")
            mb.post(f"/database/{d['id']}/sync_schema")
            return d["id"]
    hosts = [os.getenv("MB_PG_HOST")] if os.getenv("MB_PG_HOST") else [PG.host, "postgres", "host.docker.internal"]
    errors = []
    for host in dict.fromkeys(hosts):
        try:
            d = mb.post("/database", {"engine": "postgres", "name": DB_NAME, "details": {
                "host": host, "port": PG.port or 5432, "dbname": PG.database,
                "user": PG.username, "password": PG.password, "ssl": False}})
            print(f"Connected Metabase to PostgreSQL at {host}:{PG.port or 5432}/{PG.database}")
            return d["id"]
        except RuntimeError as e:
            errors.append(f"{host}: {e}")
    sys.exit("Metabase could not connect to PostgreSQL:\n  " + "\n  ".join(errors))


def wait_for_tables(mb, db_id, needed, timeout=300):
    t0 = time.time()
    while True:
        tables, fields = id_maps(mb, db_id)
        missing = needed - {t for t, _ in fields.values()}  # table synced *with* its columns
        if not missing:
            return tables, fields
        if time.time() - t0 > timeout:
            sys.exit(f"Metabase did not finish syncing tables: {sorted(missing)}")
        print(f"Waiting for Metabase to sync {len(missing) or ''} table(s)...")
        time.sleep(5)


def needed_tables(obj):
    found = set()

    def walk(x):
        if isinstance(x, dict):
            if set(x) == {"__table__"}:
                found.add(x["__table__"])
            elif set(x) == {"__field__"}:
                found.add(x["__field__"][0])
            for k, v in x.items():
                if isinstance(k, str) and k.startswith("__json__"):
                    walk(json.loads(k[8:]))
                walk(v)
        elif isinstance(x, list):
            for i in x:
                walk(i)

    walk(obj)
    return found


def import_(args):
    if not EXPORT_FILE.exists():
        sys.exit(f"{EXPORT_FILE} not found. Run `python metabase_io.py export` on the source Metabase first.")
    data = json.loads(EXPORT_FILE.read_text(encoding="utf-8"))

    if not args.skip_load:
        print("== Loading CSVs into PostgreSQL")
        sys.argv = sys.argv[:1]
        load_csvs.sync_metabase = lambda: None  # synced below
        load_csvs.main()

    print("== Configuring Metabase")
    mb = Metabase()
    mb.wait_until_up()
    if mb.version() != data["metabase_version"]:
        print(f"(Warning) export made with Metabase {data['metabase_version']}, this is {mb.version()}")
    setup_or_login(mb)
    db_id = connect_postgres(mb)
    tables, fields = wait_for_tables(mb, db_id, needed_tables(data))
    tables = {v: k for k, v in tables.items()}
    fields = {v: k for k, v in fields.items()}

    # fresh collection on every run, previous one is archived
    for c in mb.get("/collection"):
        if c.get("name") == COLLECTION and not c.get("archived") and isinstance(c.get("id"), int):
            mb.put(f"/collection/{c['id']}", {"archived": True})
            print(f"Archived previous '{COLLECTION}' collection")
    coll_id = mb.post("/collection", {"name": COLLECTION, "color": "#509EE3"})["id"]

    # questions, in dependency order
    new_ids, pending = {}, list(data["cards"])
    while pending:
        ready = [c for c in pending if card_refs(c) - {c["key"]} <= set(new_ids)]
        if not ready:
            sys.exit("Circular references between questions: " + ", ".join(c["name"] for c in pending))
        for c in ready:
            body = from_portable({k: c.get(k) for k in CARD_KEYS}, db_id, tables, fields, new_ids)
            new_ids[c["key"]] = mb.post("/card", {**body, "collection_id": coll_id})["id"]
            pending.remove(c)
    print(f"Created {len(new_ids)} questions")

    # dashboards
    for d in data["dashboards"]:
        d = from_portable(d, db_id, tables, fields, new_ids)
        new = mb.post("/dashboard", {"name": d["name"], "description": d.get("description"),
                                     "collection_id": coll_id})
        tab_ids = {t["id"]: -(i + 1) for i, t in enumerate(d["tabs"])}
        mb.put(f"/dashboard/{new['id']}", {
            "parameters": d["parameters"],
            "tabs": [{"id": tab_ids[t["id"]], "name": t["name"]} for t in d["tabs"]],
            "dashcards": [{
                "id": -(i + 1),
                "card_id": dc["card_id"],
                "dashboard_tab_id": tab_ids.get(dc["dashboard_tab_id"]),
                "series": [{"id": s} for s in dc["series"]],
                **{k: dc[k] for k in DASHCARD_KEYS},
            } for i, dc in enumerate(d["dashcards"])],
        })
        print(f"Dashboard ready: {MB_URL}/dashboard/{new['id']}  ({d['name']})")

    print(f"\nDone. Open {MB_URL} and log in as {MB_USER} / {MB_PASS}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="export questions/dashboards from your Metabase")
    e.add_argument("--database", help="Metabase database name to export (if more than one PostgreSQL)")
    i = sub.add_parser("import", help="recreate everything in a (fresh) Metabase")
    i.add_argument("--skip-load", action="store_true", help="do not reload the CSVs first")
    args = p.parse_args()
    export(args) if args.cmd == "export" else import_(args)


if __name__ == "__main__":
    main()
