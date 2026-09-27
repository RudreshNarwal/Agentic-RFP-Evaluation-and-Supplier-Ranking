"""Create the SQLite database and seed the five sample evaluation criteria (weights 30/20/20/20/10, max 10).

    python seed_db.py          # create + seed if empty
    python seed_db.py --reset  # delete DB (criteria + all runs) and start fresh
"""
import sys
from pathlib import Path

from rfp import db

if "--reset" in sys.argv:
    Path(db.DB_PATH).unlink(missing_ok=True)
db.init_db()
for c in db.get_criteria(active_only=False):
    print(f"{c['criterion_id']}. {c['name']:<24} weight={c['weight']:>5}  max={c['max_score']}  active={c['is_active']}")
print(f"DB ready: {db.DB_PATH}")
