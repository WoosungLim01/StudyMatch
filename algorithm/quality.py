"""
StudyMatch — survey response-quality flags. Admin-facing only: a flag never
blocks signup and never changes scoring, typing or matching.

Checked on the RAW 24 answers (before reverse-coding), because low-effort
patterns are invisible after scoring: answering "5" to everything flips the
reverse items to 1, so every axis lands near the middle and looks like a
perfectly ordinary profile.

Flags, first match wins:
  straight_line - STRAIGHT_LINE_SHARE or more of the 24 answers are the same option
  inconsistent  - on INCONSISTENT_MIN_AXES or more axes, the student agreed
                  (or disagreed) with both a statement and its reverse-worded
                  counterpart
  atypical      - the 6-axis profile fits none of the 4 study types well
                  (GMM log-likelihood in the bottom ATYPICAL_PERCENTILE of the
                  fit sample - see algorithm/clustering.py)
"""

from collections import Counter

from algorithm.scoring import AXES, ITEMS_BY_AXIS

STRAIGHT_LINE_SHARE = 20 / 24
INCONSISTENT_MIN_AXES = 3
AGREE, DISAGREE = 4, 2  # raw means >= 4 = agrees, <= 2 = disagrees


def response_flag(responses, atypical=False):
    """responses: {item id: raw 1-5}. Returns one flag string or None."""
    top_count = Counter(responses.values()).most_common(1)[0][1]
    if top_count >= STRAIGHT_LINE_SHARE * len(responses):
        return "straight_line"

    contradictions = 0
    for axis in AXES:
        normal = [responses[it["id"]] for it in ITEMS_BY_AXIS[axis] if not it["reverse"]]
        reverse = [responses[it["id"]] for it in ITEMS_BY_AXIS[axis] if it["reverse"]]
        n_mean, r_mean = sum(normal) / len(normal), sum(reverse) / len(reverse)
        if (n_mean >= AGREE and r_mean >= AGREE) or (n_mean <= DISAGREE and r_mean <= DISAGREE):
            contradictions += 1
    if contradictions >= INCONSISTENT_MIN_AXES:
        return "inconsistent"

    return "atypical" if atypical else None
