# StudyMatch — Sample Database ER Diagram

Schema for `data/studymatch.db` (SQLite), built by `build_database.py` from
`schema.sql` + `sample/*.json`. GitHub renders the diagram below natively;
see `schema.sql` for the full DDL (types, `CHECK` constraints, defaults).

Rendered version with row counts and design-decision notes:
https://claude.ai/code/artifact/ea7b2a43-c040-44fe-9049-af37e590cddc

## Design decisions

- **Matching scope**: compatibility is personality similarity only.
  `availability` / `availability_block` and `academic_profile` are fully
  populated, real input data — just excluded from `compatibility_score` and
  `group_score`. The `study_style_score` / `academic_score` columns on
  `pairwise_compatibility` are computed and stored the same way: zero weight.
- **No complementarity**: the old formula rewarded personality *differences*
  on 4 traits. Dropped — a good pair is simply a similar one across all 14
  traits now. `group_score` lost its diversity/"balance" term the same way.
- **Wide columns, not EAV**: personality traits and archetype centroids stay
  as wide columns — each is genuinely single-valued per row, so splitting
  them into a generic key/value table would be the EAV anti-pattern, not
  better normalization.
- **Junction tables where there were real lists**: `availability_block` and
  `academic_profile_topic` exist because their source fields were lists
  (multiple time blocks, multiple topics) — genuine 1NF repeating groups,
  correctly split out.
- **De-duplication**: `student` no longer repeats `course` / `course_section`
  — `course_membership` already owns that relationship (and now also owns
  `looking_for_group`, which is really per-course, not per-student).
- **Provenance**: `student.source` (`'synthetic'` or `'real'`) lets fake and
  real people coexist in the same tables while staying distinguishable. See
  `add_student.py` — it adds a real student's raw data, assigns them an
  archetype by nearest *existing* centroid (no re-clustering), computes their
  `pairwise_compatibility` against course-mates, and generates recruiting
  recommendations — all as pure inserts, never touching an existing
  `study_group`/`group_membership` row or another student's data.
  `build_database.py`'s destructive rebuild refuses to run over real rows
  unless you pass `--force`.

## Diagram

```mermaid
erDiagram
    UNIVERSITY ||--o{ COURSE : offers
    COURSE ||--o{ TOPIC : "defines pool"
    STUDENT ||--o{ COURSE_MEMBERSHIP : "enrolls via"
    COURSE ||--o{ COURSE_MEMBERSHIP : "enrolled via"
    STUDENT ||--o{ PERSONALITY_PROFILE : completes
    COURSE ||--o{ PERSONALITY_PROFILE : scopes
    ARCHETYPE ||--o{ PERSONALITY_PROFILE : classifies
    STUDENT ||--o{ AVAILABILITY : sets
    COURSE ||--o{ AVAILABILITY : scopes
    AVAILABILITY ||--o{ AVAILABILITY_BLOCK : contains
    STUDENT ||--o{ ACADEMIC_PROFILE : has
    COURSE ||--o{ ACADEMIC_PROFILE : scopes
    ACADEMIC_PROFILE ||--o{ ACADEMIC_PROFILE_TOPIC : tags
    TOPIC ||--o{ ACADEMIC_PROFILE_TOPIC : "tagged as"
    STUDENT ||--o{ PAIRWISE_COMPATIBILITY : "scored as A"
    STUDENT ||--o{ PAIRWISE_COMPATIBILITY : "scored as B"
    COURSE ||--o{ PAIRWISE_COMPATIBILITY : scopes
    COURSE ||--o{ STUDY_GROUP : hosts
    STUDY_GROUP ||--o{ GROUP_MEMBERSHIP : has
    STUDENT ||--o{ GROUP_MEMBERSHIP : joins
    STUDY_GROUP ||--o{ MATCH_DATA : "recommended in"
    STUDENT ||--o{ MATCH_DATA : receives
    COURSE ||--o{ COURSE_CHAT_MESSAGE : hosts
    STUDENT ||--o{ COURSE_CHAT_MESSAGE : posts
    STUDY_GROUP ||--o{ GROUP_FEEDBACK : receives
    STUDENT ||--o{ GROUP_FEEDBACK : gives

    UNIVERSITY {
        string university_id PK
        string name
        string location
    }
    COURSE {
        string course_id PK
        string university_id FK
        string course_code
        string course_title
        string section
        string semester
    }
    TOPIC {
        int topic_id PK
        string course_id FK
        string name
    }
    STUDENT {
        string student_id PK
        string name
        string year
        string gender
        string major
        string source
    }
    COURSE_MEMBERSHIP {
        string student_id PK "also FK"
        string course_id PK "also FK"
        string section
        string semester
        int looking_for_group
    }
    ARCHETYPE {
        string archetype_id PK
        string name
        string description
        int member_count
        float c_seriousness
        float c_structure
        float c_accountability
        float c_social_preference
        float c_communication_frequency
        float c_competitiveness
        float c_preparation
        float c_leadership
        float c_talkativeness
        float c_assertiveness
        float c_helpfulness
        float c_collaboration
        float c_study_pace
        float c_patience
    }
    PERSONALITY_PROFILE {
        string student_id PK "also FK"
        string course_id PK "also FK"
        int seriousness
        int structure
        int accountability
        int social_preference
        int communication_frequency
        int competitiveness
        int preparation
        int leadership
        int talkativeness
        int assertiveness
        int helpfulness
        int collaboration
        int study_pace
        int patience
        string archetype_id FK
        string preferred_role
    }
    AVAILABILITY {
        string student_id PK "also FK"
        string course_id PK "also FK"
        string preferred_study_period
        int preferred_session_duration
        int preferred_sessions_per_week
        string preferred_location
        string online_vs_in_person_preference
    }
    AVAILABILITY_BLOCK {
        int block_id PK
        string student_id FK
        string course_id FK
        string day
        string start_time
        string end_time
    }
    ACADEMIC_PROFILE {
        string student_id PK "also FK"
        string course_id PK "also FK"
        int course_confidence
        string target_grade
    }
    ACADEMIC_PROFILE_TOPIC {
        string student_id PK "also FK"
        string course_id PK "also FK"
        int topic_id PK "also FK"
        string relation PK
    }
    PAIRWISE_COMPATIBILITY {
        string student_a PK "also FK"
        string student_b PK "also FK"
        string course_id FK
        float compatibility_score
        float similarity_score
        int schedule_compatible
        int weekly_overlap_minutes
        float study_style_score
        float academic_score
    }
    STUDY_GROUP {
        string group_id PK
        string course_id FK
        string group_name
        int max_members
        int current_members
        string created_at
        float group_score
        float avg_pairwise
        float worst_pairwise
    }
    GROUP_MEMBERSHIP {
        string group_id PK "also FK"
        string student_id PK "also FK"
        string joined_at
        string group_role
    }
    MATCH_DATA {
        string match_id PK
        string student_id FK
        string recommended_group_id FK
        float compatibility_score
        int accepted
        int rejected
        string timestamp
    }
    COURSE_CHAT_MESSAGE {
        string message_id PK
        string course_id FK
        string student_id FK
        string type
        string text
        int upvotes
        string timestamp
    }
    GROUP_FEEDBACK {
        int feedback_id PK
        string group_id FK
        string student_id FK
        int satisfaction_score
        int meetings_attended
        int meetings_per_week
        int weeks_in_group
        int left_group
        int would_match_again
        int perceived_personality_fit
        int group_productivity
        string group_chat_activity
        int peer_helpfulness_rating
        int peer_reliability_rating
        string timestamp
    }
```

**Notation**: `||` = exactly one, `o{` = zero or many. `PK "also FK"` marks a
composite key column that is also a foreign key.
