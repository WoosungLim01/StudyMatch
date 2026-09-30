"""
StudyMatch — persist the study-type model (algorithm/clustering.py) in the
database and (re)classify students against it.

  archetype   one row per type: component weight/mean/covariance + display fields
  model_meta  key 'archetype_model': source, n_fit, covariance_type,
              loglik_threshold, note, fitted_at

Used by build_database.py (initial load), add_student.py (classify one new
student) and refit_archetypes.py (re-fit + reclassify everyone).
"""

import json

from algorithm.clustering import TYPES, classify
from algorithm.quality import response_flag
from algorithm.scoring import AXES

META_KEY = "archetype_model"
META_FIELDS = ("source", "n_fit", "covariance_type", "loglik_threshold", "note")


def save_model(cur, model, fitted_at):
    for c in model["components"]:
        cur.execute(
            """INSERT INTO archetype (archetype_id, name, description, member_count, weight, component)
               VALUES (?,?,?,0,?,?)
               ON CONFLICT(archetype_id) DO UPDATE SET
                   name=excluded.name, description=excluded.description,
                   weight=excluded.weight, component=excluded.component""",
            (c["archetype_id"], c["name"], c["description"], c["weight"],
             json.dumps({"mean": c["mean"], "covariance": c["covariance"]})),
        )
    meta = {k: model[k] for k in META_FIELDS} | {"fitted_at": fitted_at}
    cur.execute("INSERT OR REPLACE INTO model_meta VALUES (?,?)", (META_KEY, json.dumps(meta)))


def load_model(cur):
    """The stored model, or None if no type model has been saved yet."""
    row = cur.execute("SELECT value FROM model_meta WHERE key=?", (META_KEY,)).fetchone()
    if row is None:
        return None
    model = json.loads(row[0])
    by_id = {r[0]: r for r in cur.execute(
        "SELECT archetype_id, name, description, weight, component FROM archetype"
    ).fetchall()}
    for tid, *_ in TYPES:
        if tid not in by_id or not isinstance(json.loads(by_id[tid][4] or "null"), dict):
            return None  # rows from an older model format - refit_archetypes.py rewrites them
    model["components"] = [
        {"archetype_id": tid, "name": by_id[tid][1], "description": by_id[tid][2],
         "weight": by_id[tid][3], **json.loads(by_id[tid][4])}
        for tid, *_ in TYPES
    ]
    return model


def classify_student(traits, responses, model):
    """-> (archetype_id, archetype_strength, response_flag)"""
    result = classify(traits, model)
    return result["archetype_id"], result["strength"], response_flag(responses, atypical=result["atypical"])


def reclassify_all(cur, model):
    """Re-type every personality_profile row against `model` and refresh per-type stats."""
    profiles = cur.execute(f"SELECT student_id, course_id, {','.join(AXES)} FROM personality_profile").fetchall()
    responses = {}
    for sid, cid, item, val in cur.execute("SELECT student_id, course_id, item_number, response FROM survey_response"):
        responses.setdefault((sid, cid), {})[item] = val
    for sid, cid, *vals in profiles:
        aid, strength, flag = classify_student(dict(zip(AXES, vals)), responses[(sid, cid)], model)
        cur.execute(
            "UPDATE personality_profile SET archetype_id=?, archetype_strength=?, response_flag=? "
            "WHERE student_id=? AND course_id=?",
            (aid, strength, flag, sid, cid),
        )
    refresh_type_stats(cur)
    # drop type rows left over from an older model (e.g. the discovered-k GMM)
    keep = [tid for tid, *_ in TYPES]
    cur.execute(f"DELETE FROM archetype WHERE archetype_id NOT IN ({','.join('?' * len(keep))})", keep)


def refresh_type_stats(cur):
    """member_count and the descriptive c_* columns (members' average per axis)."""
    for tid, *_ in TYPES:
        row = cur.execute(
            f"SELECT COUNT(*), {','.join(f'AVG({a})' for a in AXES)} FROM personality_profile WHERE archetype_id=?",
            (tid,),
        ).fetchone()
        avgs = [round(v, 2) if v is not None else None for v in row[1:]]
        cur.execute(
            f"UPDATE archetype SET member_count=?, {','.join(f'c_{a}=?' for a in AXES)} WHERE archetype_id=?",
            (row[0], *avgs, tid),
        )
