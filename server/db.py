import json
import sqlite3
from datetime import datetime

_DB_PATH = None


def init(db_path):
    global _DB_PATH
    _DB_PATH = db_path
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS meetings(
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'queued',
          step TEXT NOT NULL DEFAULT 'uploaded',
          error TEXT,
          duration REAL NOT NULL DEFAULT 0,
          audio_file TEXT,
          meta TEXT,
          project TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS segments(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
          ord INTEGER NOT NULL,
          t_start REAL NOT NULL,
          t_end REAL NOT NULL,
          text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_segments_m ON segments(meeting_id);
        CREATE TABLE IF NOT EXISTS artifacts(
          meeting_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          content TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(meeting_id, kind)
        );
        """
    )
    # 旧库迁移：补 project 列
    cols = [r[1] for r in con.execute("PRAGMA table_info(meetings)").fetchall()]
    if "project" not in cols:
        con.execute("ALTER TABLE meetings ADD COLUMN project TEXT NOT NULL DEFAULT ''")
    con.commit()
    con.close()


def connect():
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------- meetings ----------

def create_meeting(mid, title, created, project="", meta=None):
    with connect() as con:
        con.execute(
            "INSERT INTO meetings(id,title,status,step,project,meta,created_at) VALUES(?,?,?,?,?,?,?)",
            (mid, title, "queued", "uploaded", (project or "")[:40],
             json.dumps(meta or {}, ensure_ascii=False), created),
        )


def update_meeting(mid, **fields):
    keys = ",".join(f"{k}=?" for k in fields)
    with connect() as con:
        con.execute(f"UPDATE meetings SET {keys} WHERE id=?", (*fields.values(), mid))


def get_meeting(mid):
    with connect() as con:
        row = con.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone()
        return dict(row) if row else None


def list_meetings(project=None):
    with connect() as con:
        rows = con.execute(
            "SELECT m.*, "
            " (SELECT COUNT(*) FROM artifacts a WHERE a.meeting_id=m.id AND a.kind='summary') HAS_SUMMARY "
            "FROM meetings m ORDER BY m.created_at DESC"
        ).fetchall()
        out = [dict(r) for r in rows]
        return out if project is None else [r for r in out if r.get("project", "") == project]


def list_projects():
    """非空项目及会议数，按数量降序"""
    with connect() as con:
        rows = con.execute(
            "SELECT project AS name, COUNT(*) AS count FROM meetings "
            "WHERE project != '' GROUP BY project ORDER BY count DESC, name"
        ).fetchall()
        return [dict(r) for r in rows]


def rename_project(old, new):
    new = (new or "").strip()[:40]
    with connect() as con:
        con.execute("UPDATE meetings SET project=? WHERE project=?", (new, old))
    return new


def dissolve_project(name):
    """解散分组：会议保留，project 置空"""
    with connect() as con:
        con.execute("UPDATE meetings SET project='' WHERE project=?", (name,))


def delete_meeting(mid):
    with connect() as con:
        con.execute("DELETE FROM segments WHERE meeting_id=?", (mid,))
        con.execute("DELETE FROM artifacts WHERE meeting_id=?", (mid,))
        con.execute("DELETE FROM meetings WHERE id=?", (mid,))


# ---------- segments ----------

def replace_segments(mid, segs):
    """segs: list[(ord,t_start,t_end,text)]"""
    with connect() as con:
        con.execute("DELETE FROM segments WHERE meeting_id=?", (mid,))
        con.executemany(
            "INSERT INTO segments(meeting_id,ord,t_start,t_end,text) VALUES(?,?,?,?,?)",
            [(mid, *s) for s in segs],
        )


def list_segments(mid):
    with connect() as con:
        rows = con.execute(
            "SELECT ord,t_start,t_end,text FROM segments WHERE meeting_id=? ORDER BY ord", (mid,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- artifacts ----------

def upsert_artifact(mid, kind, content):
    with connect() as con:
        con.execute(
            "INSERT INTO artifacts(meeting_id,kind,content,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(meeting_id,kind) DO UPDATE SET content=excluded.content,"
            "updated_at=excluded.updated_at",
            (mid, kind, content, now()),
        )


def get_artifact(mid, kind):
    with connect() as con:
        row = con.execute(
            "SELECT content,updated_at FROM artifacts WHERE meeting_id=? AND kind=?", (mid, kind)
        ).fetchone()
        return dict(row) if row else None
