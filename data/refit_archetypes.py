"""
StudyMatch — re-fit the study-type model on the live database and
reclassify everyone. Run occasionally (e.g. once a term), not per signup.

  python data/refit_archetypes.py              # fit + save + reclassify
  python data/refit_archetypes.py --dry-run    # report only, change nothing

Fits on a random sample of at most clustering.FIT_SAMPLE_MAX students (all
of them, real and synthetic, are eligible), so it stays cheap at any
scale; reclassifying is one cheap prediction per student. The 4 types and
their names never change - only the mixture's weights/means/covariances.
If the new fit would change what a type means (a component drifting to
another type's theory center, or collapsing), it is rejected and the
theory model is used instead; the printout says so.

Types are display-only, so this never touches groups or compatibility.
"""

import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.resolve().parent))
from algorithm.clustering import family_scores, fit_model
from algorithm.scoring import AXES
from data.archetype_store import load_model, reclassify_all, save_model


def main():
    dry = "--dry-run" in sys.argv
    con = sqlite3.connect(HERE / "studymatch.db")
    con.execute("PRAGMA foreign_keys = ON")
    cur = con.cursor()

    X = np.array([family_scores(dict(zip(AXES, r))) for r in
                  cur.execute(f"SELECT {','.join(AXES)} FROM personality_profile").fetchall()], dtype=float)
    before = Counter(r[0] for r in cur.execute("SELECT archetype_id FROM personality_profile"))
    old = load_model(cur)
    model = fit_model(X)

    print(f"{len(X)} students -> model source: {model['source']} ({model['covariance_type']})"
          + (f" - {model['note']}" if model["note"] else ""))
    for c in model["components"]:
        old_w = next((o["weight"] for o in old["components"] if o["archetype_id"] == c["archetype_id"]), None) if old else None
        print(f"  {c['name']:<24} weight {c['weight']:.3f}" + (f" (was {old_w:.3f})" if old_w is not None else "")
              + f"  center self-regulation={c['mean'][0]:.2f} social={c['mean'][1]:.2f}")
    if dry:
        print("dry run - nothing saved")
        return

    save_model(cur, model, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    reclassify_all(cur, model)
    con.commit()
    after = Counter(r[0] for r in cur.execute("SELECT archetype_id FROM personality_profile"))
    flags = Counter(r[0] for r in cur.execute("SELECT response_flag FROM personality_profile") if r[0])
    print("type counts:", dict(after), "(before:", dict(before), ")")
    print("response flags:", dict(flags) or "none")


if __name__ == "__main__":
    main()
