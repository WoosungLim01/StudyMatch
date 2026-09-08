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
-- Matching scope note: availability / availability_block and the
-- study_style_score column on pairwise_compatibility are valid, fully-
-- populated input data - they are simply not used to compute
-- compatibility_score or group_score right now (personality similarity only).
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

CREATE TABLE course_membership (
    student_id          TEXT NOT NULL REFERENCES student(student_id),
    course_id           TEXT NOT NULL REFERENCES course(course_id),
    section             TEXT,
    semester            TEXT,
    looking_for_group   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (student_id, course_id)
);

CREATE TABLE archetype (
    archetype_id                TEXT PRIMARY KEY,
    name                        TEXT NOT NULL,
    description                 TEXT,
    member_count                INTEGER,
    -- centroid, 1-5 scale, one column per personality trait (mirrors personality_profile)
    c_seriousness               REAL, c_structure     REAL, c_accountability REAL,
    c_social_preference         REAL, c_communication_frequency REAL, c_competitiveness REAL,
    c_preparation               REAL, c_leadership    REAL, c_talkativeness  REAL,
    c_assertiveness             REAL, c_helpfulness   REAL, c_collaboration  REAL,
    c_study_pace                REAL, c_patience      REAL
);

CREATE TABLE personality_profile (
    student_id                TEXT NOT NULL REFERENCES student(student_id),
    course_id                 TEXT NOT NULL REFERENCES course(course_id),
    seriousness               INTEGER CHECK (seriousness BETWEEN 1 AND 5),
    structure                 INTEGER CHECK (structure BETWEEN 1 AND 5),
    accountability             INTEGER CHECK (accountability BETWEEN 1 AND 5),
    social_preference          INTEGER CHECK (social_preference BETWEEN 1 AND 5),
    communication_frequency    INTEGER CHECK (communication_frequency BETWEEN 1 AND 5),
    competitiveness            INTEGER CHECK (competitiveness BETWEEN 1 AND 5),
    preparation                INTEGER CHECK (preparation BETWEEN 1 AND 5),
    leadership                 INTEGER CHECK (leadership BETWEEN 1 AND 5),
    talkativeness               INTEGER CHECK (talkativeness BETWEEN 1 AND 5),
    assertiveness               INTEGER CHECK (assertiveness BETWEEN 1 AND 5),
    helpfulness                 INTEGER CHECK (helpfulness BETWEEN 1 AND 5),
    collaboration                INTEGER CHECK (collaboration BETWEEN 1 AND 5),
    study_pace                  INTEGER CHECK (study_pace BETWEEN 1 AND 5),
    patience                    INTEGER CHECK (patience BETWEEN 1 AND 5),
    archetype_id                TEXT REFERENCES archetype(archetype_id),
    preferred_role              TEXT,
    PRIMARY KEY (student_id, course_id)
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
    compatibility_score       REAL NOT NULL,   -- == similarity_score; the only scored input right now
    similarity_score          REAL NOT NULL,
    schedule_compatible        INTEGER NOT NULL,   -- valid data, not used in compatibility_score
    weekly_overlap_minutes      INTEGER NOT NULL,   -- valid data, not used in compatibility_score
    study_style_score           REAL NOT NULL,       -- informational only, not used in compatibility_score
    PRIMARY KEY (student_a, student_b)
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
