"""One source of truth: a local SQLite file (data/vm.sqlite).

Tables: ventures, blocks (state machine per block), ledger (every paid call), cache (raw API data, 30 days),
gates (owner decisions), events (log). Files a human reads (reports, CSVs) live in ventures/<slug>/.
"""
import datetime as dt
import json
import sqlite3
import threading

from .config import S

_lock = threading.RLock()
_conn = None
_conn_path = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS ventures(
  slug TEXT PRIMARY KEY, idea TEXT, one_liner TEXT, source TEXT, country TEXT, lang TEXT,
  status TEXT, created TEXT, updated TEXT, pivot_note TEXT DEFAULT '', data TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS blocks(
  slug TEXT, block TEXT, status TEXT, attempts INTEGER DEFAULT 0, verdict TEXT DEFAULT '',
  summary TEXT DEFAULT '', error TEXT DEFAULT '', started TEXT, finished TEXT,
  PRIMARY KEY(slug, block));
CREATE TABLE IF NOT EXISTS ledger(
  id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT, block TEXT, provider TEXT, endpoint TEXT,
  usd REAL, counted INTEGER, cached INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, created TEXT, value TEXT);
CREATE TABLE IF NOT EXISTS gates(slug TEXT, gate TEXT, decision TEXT, note TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT, ts TEXT, kind TEXT, text TEXT);
"""


def now():
    return dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def db():
    global _conn, _conn_path
    path = S.data_dir / "vm.sqlite"
    with _lock:
        if _conn is None or _conn_path != path:
            path.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            _conn_path = path
        return _conn


def q(sql, args=()):
    with _lock:
        return db().execute(sql, args).fetchall()


def x(sql, args=()):
    with _lock:
        db().execute(sql, args)


# ---------- ventures ----------
def venture(slug):
    r = q("SELECT * FROM ventures WHERE slug=?", (slug,))
    if not r:
        return None
    v = dict(r[0])
    v["data"] = json.loads(v["data"] or "{}")
    return v


def ventures():
    out = []
    for r in q("SELECT * FROM ventures ORDER BY created DESC"):
        v = dict(r)
        v["data"] = json.loads(v["data"] or "{}")
        out.append(v)
    return out


def create_venture(slug, idea, source, country, lang):
    x("INSERT INTO ventures(slug,idea,one_liner,source,country,lang,status,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
      (slug, idea, "", source, country, lang, "active", now(), now()))


def update_venture(slug, **fields):
    if "data" in fields and not isinstance(fields["data"], str):
        fields["data"] = json.dumps(fields["data"], ensure_ascii=False)
    fields["updated"] = now()
    cols = ", ".join(f"{k}=?" for k in fields)
    x(f"UPDATE ventures SET {cols} WHERE slug=?", (*fields.values(), slug))


def set_data(slug, **kv):
    v = venture(slug)
    d = v["data"]
    d.update(kv)
    update_venture(slug, data=d)


# ---------- blocks ----------
def block(slug, b):
    r = q("SELECT * FROM blocks WHERE slug=? AND block=?", (slug, b))
    return dict(r[0]) if r else {"slug": slug, "block": b, "status": "PENDING", "attempts": 0, "verdict": "", "summary": "", "error": ""}


def blocks(slug):
    return {r["block"]: dict(r) for r in q("SELECT * FROM blocks WHERE slug=?", (slug,))}


def set_block(slug, b, **fields):
    cur = block(slug, b)
    cur.update(fields)
    x("INSERT OR REPLACE INTO blocks(slug,block,status,attempts,verdict,summary,error,started,finished) VALUES(?,?,?,?,?,?,?,?,?)",
      (slug, b, cur["status"], cur.get("attempts", 0), cur.get("verdict", ""), cur.get("summary", ""),
       cur.get("error", ""), cur.get("started"), cur.get("finished")))


def reset_blocks(slug, block_ids):
    for b in block_ids:
        x("DELETE FROM blocks WHERE slug=? AND block=?", (slug, b))


# ---------- money ----------
def ledger_add(slug, blk, provider, endpoint, usd, counted=True, cached=False):
    x("INSERT INTO ledger(slug,block,provider,endpoint,usd,counted,cached,ts) VALUES(?,?,?,?,?,?,?,?)",
      (slug or "", blk or "", provider, endpoint, float(usd or 0), int(bool(counted)), int(bool(cached)), now()))


def spent(slug, blocks_in=None):
    sql, args = "SELECT COALESCE(SUM(usd),0) s FROM ledger WHERE slug=? AND counted=1", [slug]
    if blocks_in:
        sql += f" AND block IN ({','.join('?' * len(blocks_in))})"
        args += list(blocks_in)
    return float(q(sql, args)[0]["s"])


def ledger(slug):
    return [dict(r) for r in q("SELECT * FROM ledger WHERE slug=? ORDER BY id", (slug,))]


# ---------- cache ----------
def cache_get(key, days):
    r = q("SELECT created, value FROM cache WHERE key=?", (key,))
    if not r:
        return None
    age = dt.datetime.now() - dt.datetime.fromisoformat(r[0]["created"])
    if age.total_seconds() > days * 86400:
        return None
    return json.loads(r[0]["value"])


def cache_put(key, value):
    x("INSERT OR REPLACE INTO cache(key,created,value) VALUES(?,?,?)", (key, now(), json.dumps(value, ensure_ascii=False)))


# ---------- gates / events ----------
def add_gate(slug, gate, decision, note=""):
    x("INSERT INTO gates(slug,gate,decision,note,ts) VALUES(?,?,?,?,?)", (slug, gate, decision, note, now()))


def gates(slug):
    return [dict(r) for r in q("SELECT * FROM gates WHERE slug=? ORDER BY ts", (slug,))]


def last_gate(slug, gate):
    r = q("SELECT * FROM gates WHERE slug=? AND gate=? ORDER BY rowid DESC LIMIT 1", (slug, gate))
    return dict(r[0]) if r else None


def log(slug, kind, text):
    x("INSERT INTO events(slug,ts,kind,text) VALUES(?,?,?,?)", (slug, now(), kind, text))


def events(slug, limit=200):
    return [dict(r) for r in q("SELECT * FROM events WHERE slug=? ORDER BY id DESC LIMIT ?", (slug, limit))]
