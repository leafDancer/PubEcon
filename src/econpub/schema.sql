PRAGMA foreign_keys = ON;

-- One row per harvest attempt. Raw pages are also kept on disk so a run can
-- be audited or resumed without touching the network again.
CREATE TABLE IF NOT EXISTS harvest_runs (
    run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL DEFAULT 'running',
    params_json  TEXT,
    records_seen INTEGER NOT NULL DEFAULT 0,
    error        TEXT
);

-- Verbatim API payloads. Keeping the source record lets us re-derive parsed
-- fields later without re-hitting the API.
CREATE TABLE IF NOT EXISTS source_records (
    record_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    source_key   TEXT NOT NULL,
    run_id       INTEGER,
    fetched_at   TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE (source, source_key),
    FOREIGN KEY (run_id) REFERENCES harvest_runs(run_id)
);

CREATE TABLE IF NOT EXISTS papers (
    paper_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    doi                TEXT NOT NULL UNIQUE,
    doi_synthetic      INTEGER NOT NULL DEFAULT 0,
    title              TEXT,
    item_type          TEXT,
    content_type       TEXT NOT NULL DEFAULT 'article',
    is_duplicate       INTEGER NOT NULL DEFAULT 0,
    duplicate_of_paper_id INTEGER,
    journal_code       TEXT,
    container_title    TEXT,
    issn               TEXT,
    publisher          TEXT,
    volume             TEXT,
    issue              TEXT,
    page_first         TEXT,
    page_last          TEXT,
    published_year     INTEGER,
    published_month    INTEGER,
    published_day      INTEGER,
    published_date     TEXT,
    published_print_date  TEXT,
    published_online_date TEXT,
    abstract           TEXT,
    abstract_available INTEGER NOT NULL DEFAULT 0,
    abstract_source    TEXT,
    abstract_aea       TEXT,
    abstract_openalex  TEXT,
    citation_count     INTEGER,
    openalex_id        TEXT,
    openalex_cited_by_count INTEGER,
    openalex_publication_date TEXT,
    openalex_type      TEXT,
    openalex_source_id TEXT,
    date_source        TEXT,
    date_confidence    TEXT,
    aea_url            TEXT,
    aea_fetched_at     TEXT,
    url                TEXT,
    retraction_status   TEXT,
    retracts_paper_id   INTEGER,
    retracted_by_paper_id INTEGER,
    is_pp              INTEGER NOT NULL DEFAULT 0,
    pp_confidence      TEXT,
    source_primary     TEXT NOT NULL DEFAULT 'crossref',
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(published_year);
CREATE INDEX IF NOT EXISTS idx_papers_type ON papers(item_type);
CREATE INDEX IF NOT EXISTS idx_papers_duplicate ON papers(is_duplicate);
CREATE INDEX IF NOT EXISTS idx_papers_retraction ON papers(retraction_status);

-- Author entities are provisional in M1: ORCID is authoritative when present,
-- otherwise a normalised full-name key is used and flagged for review.
CREATE TABLE IF NOT EXISTS authors (
    author_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_id             TEXT,
    canonical_name        TEXT NOT NULL,
    given_name            TEXT,
    family_name           TEXT,
    orcid                 TEXT,
    orcid_source          TEXT,
    orcid_match_confidence TEXT,
    wikidata_id           TEXT,
    openalex_id           TEXT,
    openalex_match_confidence TEXT,
    openalex_works_count  INTEGER,
    openalex_cited_by_count INTEGER,
    openalex_last_institution_id TEXT,
    openalex_last_institution_name TEXT,
    name_key              TEXT NOT NULL DEFAULT '',
    match_key             TEXT NOT NULL DEFAULT '',
    suffix                TEXT,
    merged_variants       INTEGER NOT NULL DEFAULT 1,
    resolution_method     TEXT NOT NULL,
    resolution_confidence TEXT NOT NULL,
    needs_review          INTEGER NOT NULL DEFAULT 0,
    review_status         TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_authors_orcid
    ON authors(orcid) WHERE orcid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_authors_name_key ON authors(name_key);
CREATE INDEX IF NOT EXISTS idx_authors_match_key ON authors(match_key);
CREATE INDEX IF NOT EXISTS idx_authors_openalex
    ON authors(openalex_id) WHERE openalex_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS authorships (
    authorship_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id          INTEGER NOT NULL,
    author_id         INTEGER,
    author_order      INTEGER NOT NULL,
    given_name        TEXT,
    family_name       TEXT,
    full_name         TEXT,
    affiliation_raw   TEXT,
    institution_hint  TEXT,
    institution_source TEXT,
    openalex_author_id TEXT,
    openalex_author_name TEXT,
    openalex_orcid TEXT,
    openalex_institution_id TEXT,
    openalex_institution_name TEXT,
    openalex_raw_affiliation TEXT,
    openalex_match_method TEXT,
    openalex_match_confidence TEXT,
    orcid             TEXT,
    suffix            TEXT,
    match_key         TEXT,
    sequence          TEXT,
    is_corresponding  INTEGER,
    rank_raw          TEXT,
    rank_category     TEXT,
    FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES authors(author_id),
    UNIQUE (paper_id, author_order)
);

CREATE INDEX IF NOT EXISTS idx_authorships_author ON authorships(author_id);
CREATE INDEX IF NOT EXISTS idx_authorships_rank ON authorships(rank_category);
CREATE INDEX IF NOT EXISTS idx_authorships_match_key ON authorships(match_key);

-- Every spelling variant that was merged into a canonical author. Kept even
-- after a canonical author row is rebuilt so the decision is auditable.
CREATE TABLE IF NOT EXISTS author_aliases (
    alias_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id    INTEGER NOT NULL,
    given_name   TEXT,
    family_name  TEXT,
    full_name    TEXT,
    orcid        TEXT,
    suffix       TEXT,
    name_key     TEXT,
    match_key    TEXT,
    first_year   INTEGER,
    last_year    INTEGER,
    paper_count  INTEGER,
    created_at   TEXT NOT NULL,
    FOREIGN KEY (author_id) REFERENCES authors(author_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_author_aliases_author ON author_aliases(author_id);

-- Author pairs that look like one person by name but have conflicting
-- affiliation/suffix evidence. They remain separate until reviewed.
CREATE TABLE IF NOT EXISTS author_merge_candidates (
    candidate_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id_a   INTEGER NOT NULL,
    author_id_b   INTEGER NOT NULL,
    reason        TEXT NOT NULL,
    institution_a TEXT,
    institution_b TEXT,
    year_a        INTEGER,
    year_b        INTEGER,
    evidence      TEXT,
    review_notes  TEXT,
    reviewed_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TEXT NOT NULL,
    FOREIGN KEY (author_id_a) REFERENCES authors(author_id),
    FOREIGN KEY (author_id_b) REFERENCES authors(author_id)
);

CREATE TABLE IF NOT EXISTS institutions (
    institution_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name    TEXT NOT NULL,
    normalized_name TEXT UNIQUE,
    country         TEXT,
    country_code    TEXT,
    ror             TEXT,
    type            TEXT,
    openalex_id     TEXT,
    created_at      TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_institutions_openalex
    ON institutions(openalex_id) WHERE openalex_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS paper_topics (
    paper_id INTEGER NOT NULL,
    scheme   TEXT NOT NULL,
    code     TEXT,
    label    TEXT NOT NULL,
    score    REAL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (paper_id, scheme, label),
    FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE
);

-- One authorship can carry several publish-time institutions (e.g. a
-- university and NBER). The flat `authorships.institution_hint` remains the
-- Crossref string; this table stores resolved entities with provenance.
CREATE TABLE IF NOT EXISTS authorship_institutions (
    authorship_id  INTEGER NOT NULL,
    institution_id INTEGER NOT NULL,
    source         TEXT NOT NULL,
    is_primary     INTEGER NOT NULL DEFAULT 0,
    raw_name       TEXT,
    PRIMARY KEY (authorship_id, institution_id, source),
    FOREIGN KEY (authorship_id) REFERENCES authorships(authorship_id) ON DELETE CASCADE,
    FOREIGN KEY (institution_id) REFERENCES institutions(institution_id)
);

-- Every OpenAlex author ID observed for a canonical author. Multiple rows for
-- one canonical author indicate a possible over-merge; one OpenAlex ID shared
-- by several canonical authors indicates a possible under-merge.
CREATE TABLE IF NOT EXISTS author_openalex_evidence (
    evidence_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id    INTEGER NOT NULL,
    openalex_id  TEXT NOT NULL,
    paper_count  INTEGER NOT NULL DEFAULT 0,
    first_year   INTEGER,
    last_year    INTEGER,
    institutions TEXT,
    is_consistent INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    UNIQUE (author_id, openalex_id),
    FOREIGN KEY (author_id) REFERENCES authors(author_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_author_openalex_author
    ON author_openalex_evidence(author_id);
CREATE INDEX IF NOT EXISTS idx_author_openalex_openalex
    ON author_openalex_evidence(openalex_id);

-- Stable identity ledger. Unlike `authors`, this table survives author-table
-- rebuilds, so a person's public identifier can remain stable while internal
-- author_id values are recomputed.
CREATE TABLE IF NOT EXISTS author_identity_ledger (
    stable_id        TEXT PRIMARY KEY,
    orcid            TEXT,
    openalex_id      TEXT,
    canonical_name   TEXT,
    given_name       TEXT,
    family_name      TEXT,
    name_key         TEXT,
    match_key        TEXT,
    first_year       INTEGER,
    last_year        INTEGER,
    institutions     TEXT,
    current_author_id INTEGER,
    status           TEXT NOT NULL DEFAULT 'active',
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_identity_ledger_orcid
    ON author_identity_ledger(orcid) WHERE orcid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_identity_ledger_openalex
    ON author_identity_ledger(openalex_id) WHERE openalex_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_identity_ledger_name
    ON author_identity_ledger(match_key);

CREATE TABLE IF NOT EXISTS author_identity_events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_id      TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    related_stable_id TEXT,
    author_id      INTEGER,
    reason         TEXT,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_identity_events_stable
    ON author_identity_events(stable_id);

-- Proposed split of one canonical author into several OpenAlex-ID groups.
-- A row with status='applied' is a completed identity split.
CREATE TABLE IF NOT EXISTS author_split_candidates (
    split_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id      INTEGER NOT NULL,
    openalex_id    TEXT NOT NULL,
    proposed_name  TEXT,
    paper_count    INTEGER NOT NULL DEFAULT 0,
    first_year     INTEGER,
    last_year      INTEGER,
    institutions   TEXT,
    evidence       TEXT,
    status         TEXT NOT NULL DEFAULT 'proposed',
    created_at     TEXT NOT NULL,
    UNIQUE (author_id, openalex_id),
    FOREIGN KEY (author_id) REFERENCES authors(author_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_split_candidates_author
    ON author_split_candidates(author_id);

-- Permanent "these are different people" rules. They survive author-table
-- rebuilds and are consulted by the name resolver so a confirmed split is not
-- silently re-merged on the next run.
CREATE TABLE IF NOT EXISTS author_separation_rules (
    rule_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    left_openalex_id   TEXT,
    right_openalex_id  TEXT,
    left_authorship_id INTEGER,
    right_authorship_id INTEGER,
    reason             TEXT,
    created_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_separation_rules_left_oa
    ON author_separation_rules(left_openalex_id);
CREATE INDEX IF NOT EXISTS idx_separation_rules_right_oa
    ON author_separation_rules(right_openalex_id);

-- Structured CV facts. Deliberately stores only degree/position facts, not
-- personal data such as birth dates, addresses, or emails.
CREATE TABLE IF NOT EXISTS career_events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id      INTEGER NOT NULL,
    event_type     TEXT NOT NULL,
    title          TEXT,
    institution    TEXT,
    institution_id INTEGER,
    start_year     INTEGER,
    end_year       INTEGER,
    is_current     INTEGER,
    source_url     TEXT,
    source_type    TEXT,
    source_snippet TEXT,
    event_key      TEXT,
    confidence     TEXT,
    created_at     TEXT NOT NULL,
    FOREIGN KEY (author_id) REFERENCES authors(author_id),
    FOREIGN KEY (institution_id) REFERENCES institutions(institution_id)
);

CREATE INDEX IF NOT EXISTS idx_career_author ON career_events(author_id);

-- CV and homepage sources discovered for an author. Raw documents live on
-- disk (ignored by git); the database stores provenance and status only.
CREATE TABLE IF NOT EXISTS author_cv_sources (
    source_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id      INTEGER NOT NULL,
    url            TEXT NOT NULL,
    source_type    TEXT NOT NULL,
    fetched_at     TEXT,
    content_hash   TEXT,
    local_path     TEXT,
    status         TEXT NOT NULL DEFAULT 'candidate',
    notes          TEXT,
    created_at     TEXT NOT NULL,
    UNIQUE (author_id, url),
    FOREIGN KEY (author_id) REFERENCES authors(author_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cv_sources_author ON author_cv_sources(author_id);
CREATE INDEX IF NOT EXISTS idx_cv_sources_status ON author_cv_sources(status);

-- Historical faculty/homepage snapshots retrieved from the Wayback Machine.
-- Each row is one archived URL tied to one paper year for an author.
CREATE TABLE IF NOT EXISTS author_wayback_snapshots (
    snapshot_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id         INTEGER NOT NULL,
    source_url        TEXT NOT NULL,
    original_url      TEXT,
    snapshot_timestamp TEXT NOT NULL,
    snapshot_url      TEXT NOT NULL,
    paper_year        INTEGER,
    status            TEXT NOT NULL DEFAULT 'candidate',
    content_hash      TEXT,
    local_path        TEXT,
    fetched_at        TEXT,
    notes             TEXT,
    created_at        TEXT NOT NULL,
    UNIQUE (author_id, snapshot_url, paper_year),
    FOREIGN KEY (author_id) REFERENCES authors(author_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_wayback_author
    ON author_wayback_snapshots(author_id);
CREATE INDEX IF NOT EXISTS idx_wayback_status
    ON author_wayback_snapshots(status);

-- The central inference table: what was this author's stage when this paper
-- was published? Every row must carry evidence and a confidence level.
CREATE TABLE IF NOT EXISTS career_assignments (
    assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    authorship_id INTEGER NOT NULL UNIQUE,
    author_id     INTEGER NOT NULL,
    paper_id      INTEGER NOT NULL,
    stage         TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    confidence    TEXT NOT NULL,
    source_url    TEXT,
    notes         TEXT,
    career_event_id INTEGER,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (authorship_id) REFERENCES authorships(authorship_id) ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES authors(author_id),
    FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_career_assign_stage ON career_assignments(stage);

CREATE TABLE IF NOT EXISTS coauthorship_edges (
    author_a_id INTEGER NOT NULL,
    author_b_id INTEGER NOT NULL,
    paper_id    INTEGER NOT NULL,
    year        INTEGER,
    PRIMARY KEY (author_a_id, author_b_id, paper_id),
    FOREIGN KEY (author_a_id) REFERENCES authors(author_id),
    FOREIGN KEY (author_b_id) REFERENCES authors(author_id),
    FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE
);

-- Cached graph statistics, one row per scope ('ALL' or a journal code).
CREATE TABLE IF NOT EXISTS network_statistics (
    scope              TEXT PRIMARY KEY,
    nodes              INTEGER NOT NULL,
    edges              INTEGER NOT NULL,
    components         INTEGER NOT NULL,
    largest_component  INTEGER NOT NULL,
    average_degree     REAL,
    average_path_length REAL,
    diameter           INTEGER,
    average_clustering REAL,
    pairs              INTEGER,
    details_json       TEXT,
    generated_at       TEXT NOT NULL
);
