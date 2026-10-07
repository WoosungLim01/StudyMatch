-- StudyMatch sample database schema (SQLite)
--
-- Normalizes the flat sample/*.json files into a proper relational schema:
--   - student no longer duplicates course/section (that's course_membership's job)
--   - availability.blocks (a list) becomes its own availability_block table
--   - archetype centroids and personality traits stay as wide columns
--     (they're genuinely single-valued per row, not a repeating group -
--     splitting those into a generic key/value table would be the EAV
--     anti-pattern, not better normalization)
--
-- Matching: compatibility_score = weighted 6-axis similarity (0-100,
-- algorithm/compatibility.py); groups of 4-5 are formed per course by an ILP
-- maximizing within-group compatibility (algorithm/grouping.py).
--
-- Matching scope note: availability / availability_block and the
-- study_style_score column on pairwise_compatibility are valid, fully-
-- populated input data - they are simply not used to compute
-- compatibility_score or group_score right now (personality similarity only).
--
-- Survey instrument: personality_profile's 6 axes (planning, session_mode,
-- reliability, structure, intensity, collaboration) are scored from the
-- 24-item Likert survey stored raw in survey_response - see
-- ../algorithm/scoring.py for the item bank and scoring function.
--
-- Topic tracking (a `topic` lookup table + academic strong/weak/can_help/
-- needs_help tagging) was deliberately removed - academic_profile now only
-- carries course_confidence/target_grade. See README.md.

PRAGMA foreign_keys = ON;

CREATE TABLE university (
    university_id TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    location       TEXT
);

CREATE TABLE course (
    course_id      TEXT PRIMARY KEY,
    university_id  TEXT NOT NULL REFERENCES university(university_id),
    course_code    TEXT NOT NULL,
    course_title   TEXT NOT NULL,
    section        TEXT NOT NULL,
    semester       TEXT NOT NULL
);

CREATE TABLE student (
    student_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    year        TEXT,
    gender      TEXT,
    major       TEXT,
    -- provenance: lets fake and real people coexist in the same tables while
    -- staying distinguishable (filterable, and safe to bulk-delete the fake ones).
    source      TEXT NOT NULL DEFAULT 'synthetic' CHECK (source IN ('synthetic', 'real'))
);

-- Login account. Deliberately separate from `student`: an account exists
-- BEFORE the survey is ever taken (you log in, then get sent to the survey),
-- so student_id starts NULL and is set once - that's also how login knows
-- whether to route someone to /survey or /home. Named user_account (not
-- `user`) to dodge the reserved-word gotcha that bites plenty of SQL engines.
-- Two sign-in paths share this one row shape: password accounts have
-- password_hash set and google_sub NULL; Google accounts have the reverse.
-- Matched by email on Google sign-in, so the same person can't end up with
-- two separate accounts just by choosing a different sign-in method.
--
-- Email verification: password accounts start unverified (verified_at
-- NULL) with a 6-digit verify_token emailed to them; login is refused
-- until the code is entered together with the password (verify-code endpoint). Google accounts are auto-verified at creation -
-- Google already confirmed the email on its end (userinfo's
-- email_verified), asking again would be redundant.
CREATE TABLE user_account (
    user_id         TEXT PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash   TEXT,    -- NULL for Google-only accounts (no password set)
    google_sub      TEXT UNIQUE,    -- Google's stable per-user ID; NULL for password-only accounts
    created_at      TEXT NOT NULL,
    student_id      TEXT UNIQUE REFERENCES student(student_id),
    verified_at     TEXT,    -- NULL until the email is confirmed
    verify_token    TEXT UNIQUE    -- 6-digit code emailed on signup; NULL once verified
);

CREATE TABLE session (
    session_token   TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES user_account(user_id),
    created_at      TEXT NOT NULL,
    -- same ISO-8601 UTC format as created_at, so plain string comparison orders correctly
    expires_at      TEXT NOT NULL
);

CREATE TABLE course_membership (
    student_id          TEXT NOT NULL REFERENCES student(student_id),
    course_id           TEXT NOT NULL REFERENCES course(course_id),
    section             TEXT,
    semester            TEXT,
    looking_for_group   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (student_id, course_id)
);

-- The 4 theory-defined study types (algorithm/clustering.py TYPES: Study
-- Captain, Focused Architect, Collaborative Explorer, Independent Sprinter),
-- one row each, each row also holding its component of the Gaussian mixture
-- that assigns students to types. Display layer only - never an input to
-- compatibility or group formation.
CREATE TABLE archetype (
    archetype_id                TEXT PRIMARY KEY,
    name                        TEXT NOT NULL,
    description                 TEXT,
    member_count                INTEGER,
    -- descriptive: members' average on each survey axis (1-5), refreshed on
    -- every reclassification. Not part of the model.
    c_planning                  REAL, c_session_mode  REAL, c_reliability  REAL,
    c_structure                 REAL, c_intensity     REAL, c_collaboration REAL,
    -- the stored mixture component, so a new signup is classified without a re-fit
    weight                      REAL,   -- mixing proportion
    component                   TEXT    -- JSON {"mean": [2], "covariance": [[2x2]]} over the
                                        -- (self-regulation, social mode) family scores
);

-- Key/value metadata about the stored type model: key 'archetype_model' holds
-- JSON {source: theory|fitted, n_fit, covariance_type, loglik_threshold, note, fitted_at}.
CREATE TABLE model_meta (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

-- Six axis scores (1-5, averaged from the 24 raw Likert items in
-- survey_response below) driving matching. See ../algorithm/scoring.py for
-- the item bank and the reverse-coding/averaging that produces these.
CREATE TABLE personality_profile (
    student_id                TEXT NOT NULL REFERENCES student(student_id),
    course_id                 TEXT NOT NULL REFERENCES course(course_id),
    planning                  REAL CHECK (planning BETWEEN 1 AND 5),
    session_mode               REAL CHECK (session_mode BETWEEN 1 AND 5),
    reliability                 REAL CHECK (reliability BETWEEN 1 AND 5),
    structure                   REAL CHECK (structure BETWEEN 1 AND 5),
    intensity                   REAL CHECK (intensity BETWEEN 1 AND 5),
    collaboration                REAL CHECK (collaboration BETWEEN 1 AND 5),
    archetype_id                TEXT REFERENCES archetype(archetype_id),
    preferred_role              TEXT,
    archetype_strength          REAL,   -- GMM posterior of archetype_id, 0-100 (display only)
    response_flag               TEXT,   -- NULL | straight_line | inconsistent | atypical (algorithm/quality.py; admin only)
    PRIMARY KEY (student_id, course_id)
);

-- Raw answers to the 24-item entry survey ("Version 3" of the MSLQ-informed
-- redesign) — one row per item per student, 5-point Likert (1=Strongly
-- Disagree .. 5=Strongly Agree), reverse-worded items stored AS ANSWERED (not
-- pre-flipped). Kept alongside the computed axis scores above so scoring can
-- be audited or re-run without re-surveying anyone. item_number matches the
-- id field in algorithm/scoring.py's SURVEY_ITEMS.
CREATE TABLE survey_response (
    student_id   TEXT NOT NULL REFERENCES student(student_id),
    course_id    TEXT NOT NULL REFERENCES course(course_id),
    item_number  INTEGER NOT NULL CHECK (item_number BETWEEN 1 AND 24),
    response     INTEGER NOT NULL CHECK (response BETWEEN 1 AND 5),
    PRIMARY KEY (student_id, course_id, item_number)
);

-- Kept as valid input data; excluded from compatibility/group scoring (see schema.sql header).
CREATE TABLE availability (
    student_id                        TEXT NOT NULL REFERENCES student(student_id),
    course_id                         TEXT NOT NULL REFERENCES course(course_id),
    preferred_study_period             TEXT,
    preferred_session_duration         INTEGER,
    preferred_sessions_per_week        INTEGER,
    preferred_location                 TEXT,
    online_vs_in_person_preference     TEXT,
    PRIMARY KEY (student_id, course_id)
);

CREATE TABLE availability_block (
    block_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   TEXT NOT NULL,
    course_id    TEXT NOT NULL,
    day          TEXT NOT NULL,
    start_time   TEXT NOT NULL,
    end_time     TEXT NOT NULL,
    FOREIGN KEY (student_id, course_id) REFERENCES availability(student_id, course_id)
);

-- Kept as valid input data; excluded from compatibility/group scoring (see schema.sql header).
CREATE TABLE academic_profile (
    student_id          TEXT NOT NULL REFERENCES student(student_id),
    course_id           TEXT NOT NULL REFERENCES course(course_id),
    course_confidence   INTEGER,
    target_grade        TEXT,
    PRIMARY KEY (student_id, course_id)
);

CREATE TABLE pairwise_compatibility (
    student_a                 TEXT NOT NULL REFERENCES student(student_id),
    student_b                 TEXT NOT NULL REFERENCES student(student_id),
    course_id                 TEXT NOT NULL REFERENCES course(course_id),
    compatibility_score       REAL NOT NULL,   -- == similarity_score: weighted 6-axis similarity, 0-100
    similarity_score          REAL NOT NULL,
    schedule_compatible        INTEGER NOT NULL,   -- valid data, not used in compatibility_score
    weekly_overlap_minutes      INTEGER NOT NULL,   -- valid data, not used in compatibility_score
    study_style_score           REAL NOT NULL,       -- informational only, not used in compatibility_score
    -- course_id is part of the key: personality is per-course, so the same pair
    -- can have a different score in each course they share
    PRIMARY KEY (student_a, student_b, course_id)
);

CREATE TABLE study_group (
    group_id          TEXT PRIMARY KEY,
    course_id         TEXT NOT NULL REFERENCES course(course_id),
    group_name        TEXT,
    max_members       INTEGER,
    current_members   INTEGER,
    created_at        TEXT,
    group_score       REAL,   -- == avg_pairwise; no diversity/balance term anymore
    avg_pairwise      REAL,
    worst_pairwise    REAL
);

CREATE TABLE group_membership (
    group_id     TEXT NOT NULL REFERENCES study_group(group_id),
    student_id   TEXT NOT NULL REFERENCES student(student_id),
    joined_at    TEXT,
    group_role   TEXT,
    PRIMARY KEY (group_id, student_id)
);

CREATE TABLE match_data (
    match_id                TEXT PRIMARY KEY,
    student_id               TEXT NOT NULL REFERENCES student(student_id),
    recommended_group_id      TEXT NOT NULL REFERENCES study_group(group_id),
    compatibility_score        REAL,
    accepted                   INTEGER,
    rejected                   INTEGER,
    timestamp                  TEXT
);

CREATE TABLE course_chat_message (
    message_id   TEXT PRIMARY KEY,
    course_id    TEXT NOT NULL REFERENCES course(course_id),
    student_id   TEXT NOT NULL REFERENCES student(student_id),
    type         TEXT,
    text         TEXT,
    upvotes      INTEGER,
    timestamp    TEXT
);

-- Private chat for one study group's members (ui/chat.html). Separate from
-- course_chat_message, which is the course-wide Q&A board. message_id is
-- monotonically increasing so clients poll with "?after=<last id seen>".
-- app.py also creates this table on startup (IF NOT EXISTS), so databases
-- built before it existed - including the live Turso one - pick it up on deploy.
CREATE TABLE IF NOT EXISTS group_chat_message (
    message_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id     TEXT NOT NULL REFERENCES study_group(group_id),
    student_id   TEXT NOT NULL REFERENCES student(student_id),
    text         TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_group_chat_message_group ON group_chat_message(group_id, message_id);

CREATE TABLE group_feedback (
    feedback_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id                     TEXT NOT NULL REFERENCES study_group(group_id),
    student_id                   TEXT NOT NULL REFERENCES student(student_id),
    satisfaction_score            INTEGER,
    meetings_attended             INTEGER,
    meetings_per_week             INTEGER,
    weeks_in_group                 INTEGER,
    left_group                     INTEGER,
    would_match_again              INTEGER,
    perceived_personality_fit       INTEGER,
    group_productivity              INTEGER,
    group_chat_activity             TEXT,
    peer_helpfulness_rating          INTEGER,
    peer_reliability_rating          INTEGER,
    timestamp                        TEXT,
    UNIQUE (group_id, student_id)
);
