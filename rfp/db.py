"""SQLite persistence: evaluation criteria, RFP runs, supplier results."""
import json
import os
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get("RFP_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "rfp.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_criteria (
    criterion_id INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT NOT NULL,
    weight       REAL NOT NULL CHECK (weight >= 0),
    max_score    REAL NOT NULL CHECK (max_score > 0),
    is_active    INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);
CREATE TABLE IF NOT EXISTS rfp_runs (
    rfp_run_id    TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    llm_provider  TEXT,
    llm_model     TEXT,
    warnings_json TEXT,
    run_json      TEXT
);
-- Rows are created 'pending' when the batch starts (step 3) and filled in when results are persisted (step 9).
CREATE TABLE IF NOT EXISTS supplier_results (
    rfp_run_id        TEXT NOT NULL REFERENCES rfp_runs(rfp_run_id),
    supplier_name     TEXT NOT NULL,
    submission_date   TEXT NOT NULL,
    experience_rating REAL NOT NULL,
    source_file       TEXT,
    status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'scored', 'failed')),
    absolute_score    REAL,
    ppi               REAL,
    final_rank        INTEGER,
    result_json       TEXT,
    PRIMARY KEY (rfp_run_id, supplier_name)
);
"""

SEED_CRITERIA = [
    (1, "Technical Capability", "Architecture, integrations, scalability, technical fit", 30, 10),
    (2, "Implementation Plan", "Timeline, milestones, staffing, risk plan", 20, 10),
    (3, "Commercial Value", "Pricing clarity, total cost, assumptions", 20, 10),
    (4, "Security & Compliance", "Controls, certifications, privacy, auditability", 20, 10),
    (5, "Support & Experience", "Support model, similar projects, references", 10, 10),
]


def connect(path=None):
    path = path or DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path=None):
    """Create tables; seed criteria only when the table is empty (never overwrites user edits)."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM evaluation_criteria").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO evaluation_criteria (criterion_id, name, description, weight, max_score, is_active)"
                " VALUES (?, ?, ?, ?, ?, 1)", SEED_CRITERIA)


def get_criteria(path=None, active_only=True):
    sql = "SELECT * FROM evaluation_criteria" + (" WHERE is_active = 1" if active_only else "") + " ORDER BY criterion_id"
    with connect(path) as conn:
        return [dict(r) for r in conn.execute(sql)]


def save_criteria(rows, path=None):
    with connect(path) as conn:
        conn.executemany(
            "UPDATE evaluation_criteria SET name=?, description=?, weight=?, max_score=?, is_active=? WHERE criterion_id=?",
            [(r["name"], r["description"], float(r["weight"]), float(r["max_score"]), int(bool(r["is_active"])),
              int(r["criterion_id"])) for r in rows])


def create_run(run_id, created_at, provider, model, suppliers, path=None):
    """Step 3: the batch row and one 'pending' entry per supplier, in one transaction."""
    with connect(path) as conn:
        conn.execute("INSERT INTO rfp_runs (rfp_run_id, created_at, status, llm_provider, llm_model) VALUES (?, ?, 'running', ?, ?)",
                     (run_id, created_at, provider, model))
        conn.executemany(
            "INSERT INTO supplier_results (rfp_run_id, supplier_name, submission_date, experience_rating, source_file)"
            " VALUES (?, ?, ?, ?, ?)",
            [(run_id, s["supplier_name"], s["submission_date"], s["experience_rating"], s.get("filename")) for s in suppliers])


def fail_run(run_id, error, path=None):
    with connect(path) as conn:
        conn.execute("UPDATE rfp_runs SET status='failed', warnings_json=? WHERE rfp_run_id=?", (json.dumps([error]), run_id))
        conn.execute("UPDATE supplier_results SET status='failed' WHERE rfp_run_id=?", (run_id,))


def get_supplier_rows(run_id, path=None):
    with connect(path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM supplier_results WHERE rfp_run_id=? ORDER BY final_rank, supplier_name", (run_id,))]


def complete_run(run, path=None):
    """Step 9: fill in every supplier entry and the full run JSON in one transaction."""
    with connect(path) as conn:
        conn.executemany(
            "UPDATE supplier_results SET status='scored', absolute_score=?, ppi=?, final_rank=?, result_json=?"
            " WHERE rfp_run_id=? AND supplier_name=?",
            [(s["absolute_score"], s["ppi"], s["final_rank"], json.dumps(s), run["rfp_run_id"], s["supplier_name"])
             for s in run["suppliers"]])
        conn.execute("UPDATE rfp_runs SET status='completed', warnings_json=?, run_json=? WHERE rfp_run_id=?",
                     (json.dumps(run["warnings"]), json.dumps(run), run["rfp_run_id"]))


def list_runs(path=None):
    with connect(path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT rfp_run_id, created_at, status, llm_provider, llm_model FROM rfp_runs ORDER BY created_at DESC")]


def load_run(run_id, path=None):
    with connect(path) as conn:
        row = conn.execute("SELECT run_json FROM rfp_runs WHERE rfp_run_id=?", (run_id,)).fetchone()
    return json.loads(row["run_json"]) if row and row["run_json"] else None
