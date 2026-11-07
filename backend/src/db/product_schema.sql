-- product_schema.sql（刀3 DDL 拆分，源 = manager.py 实库 schema @0dbf55e 分包分支）
-- 途/聘/伴产品面表；FK 只许指向 users(id)；orders/subscriptions 归产品（裁决 3）。
-- 依赖：须先执行 core_schema.sql（users / user_identities）。

CREATE TABLE game_profiles (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    identity            TEXT,                  -- PlanetX: explorer | captain | wanderer
    personality_type    TEXT,                  -- MBTI or custom type
    personality_detail  TEXT,                  -- JSON blob with full analysis
    xp                  INTEGER DEFAULT 0,
    level               INTEGER DEFAULT 1,
    updated_at          TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(user_id)
);

CREATE TABLE fleets (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    captain_id      TEXT NOT NULL,
    description     TEXT DEFAULT '',
    invite_code     TEXT UNIQUE,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (captain_id) REFERENCES users(id)
);

CREATE TABLE fleet_members (
    id          TEXT PRIMARY KEY,
    fleet_id    TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    joined_at   TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (fleet_id) REFERENCES fleets(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(fleet_id, user_id)
);

CREATE TABLE mission_completions (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    mission_id  TEXT NOT NULL,
    xp_reward   INTEGER DEFAULT 0,
    completed_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(user_id, mission_id)
);

CREATE TABLE trust_memories (
    id              TEXT PRIMARY KEY,          -- UUID
    user_id         TEXT NOT NULL,
    session_type    TEXT NOT NULL,             -- quiz | fleet | match | ask | share
    session_id      TEXT NOT NULL,
    memory_content  TEXT NOT NULL,             -- JSON: structured behaviour snapshot
    memory_level    INTEGER DEFAULT 1,         -- 1=surface, 2=deep, 3=fragment, 4=taboo
    created_at      TEXT DEFAULT (datetime('now')),  -- immutable
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE trust_attestations (
    id                  TEXT PRIMARY KEY,          -- UUID
    candidate_id        TEXT NOT NULL,
    claim_type          TEXT NOT NULL,             -- identity | collaboration | communication | influence
    claim_statement     TEXT NOT NULL,
    evidence_type       TEXT NOT NULL,             -- quiz | fleet_consensus | dialogue_analysis | share_signal
    evidence_refs       TEXT DEFAULT '[]',         -- JSON array: trust_memories.id list
    verification_status TEXT DEFAULT 'unverified', -- verified | weak | unverified | contradicted
    confidence_score    REAL DEFAULT 0.0,          -- 0-1 internal only, never shown to users
    generated_by        TEXT DEFAULT 'trust_agent_v0',
    signature           TEXT DEFAULT '',                -- Ed25519 looma_sig_v1:...
    expires_at          TEXT DEFAULT NULL,              -- ISO 8601, 90 days from issued_at
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (candidate_id) REFERENCES users(id),
    UNIQUE(candidate_id, claim_type)               -- one attestation per candidate per claim type
);

CREATE TABLE enterprises (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    domain          TEXT,                      -- e.g. "genz.ltd"
    plan            TEXT DEFAULT 'free',       -- free | pro | enterprise
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE enterprise_users (
    id              TEXT PRIMARY KEY,
    enterprise_id   TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    role            TEXT DEFAULT 'member',     -- member | admin
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (enterprise_id) REFERENCES enterprises(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(enterprise_id, user_id)
);

CREATE TABLE candidates (
    id              TEXT PRIMARY KEY,
    enterprise_id   TEXT NOT NULL,
    user_id         TEXT,                      -- linked looma user (nullable)
    name            TEXT NOT NULL,
    email           TEXT,
    phone           TEXT,
    status          TEXT DEFAULT 'new',        -- new | contacted | interviewed | hired | rejected
    profile_data    TEXT,                      -- JSON blob (personality, skills, etc.)
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (enterprise_id) REFERENCES enterprises(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE job_posts (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    title           TEXT NOT NULL,
    company         TEXT DEFAULT '',
    description     TEXT DEFAULT '',
    requirements    TEXT DEFAULT '',
    status          TEXT DEFAULT 'active',     -- active | closed | draft
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE applications (
    id                TEXT PRIMARY KEY,
    seeker_user_id    TEXT NOT NULL,
    resume_id         TEXT NOT NULL,           -- documents.id (resume)
    job_id            TEXT NOT NULL,           -- documents.metadata.job_id or job_posts.id
    enterprise_id     TEXT DEFAULT '',
    status            TEXT DEFAULT 'submitted', -- submitted | withdrawn
    metadata          TEXT DEFAULT '{}',       -- JSON, no vector payloads
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    withdrawn_at      TEXT DEFAULT NULL,
    FOREIGN KEY (seeker_user_id) REFERENCES users(id)
);

CREATE TABLE sales_inquiries (
    id              TEXT PRIMARY KEY,
    user_id         TEXT,
    company_name    TEXT NOT NULL,
    contact_name    TEXT NOT NULL,
    contact_email   TEXT NOT NULL,
    contact_phone   TEXT DEFAULT '',
    scale           TEXT DEFAULT '',
    message         TEXT DEFAULT '',
    status          TEXT DEFAULT 'new',        -- new | contacted | closed
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE orders (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    plan_id         TEXT NOT NULL,
    tier            TEXT NOT NULL,
    amount          REAL NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'CNY',
    out_trade_no    TEXT UNIQUE NOT NULL,
    transaction_id  TEXT,
    status          TEXT DEFAULT 'pending',     -- pending | paid | expired | refunded
    prepay_id       TEXT,
    qr_code_url     TEXT,
    metadata_json   TEXT DEFAULT '{}',
    created_at      TEXT DEFAULT (datetime('now')),
    paid_at         TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE subscriptions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL UNIQUE,
    tier            TEXT NOT NULL,
    plan_id         TEXT NOT NULL,
    status          TEXT DEFAULT 'active',      -- active | expired | cancelled
    started_at      TEXT DEFAULT (datetime('now')),
    expires_at      TEXT NOT NULL,
    auto_renew      INTEGER DEFAULT 0,
    cancel_at_period_end INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE huawei_push_tokens (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    push_token      TEXT NOT NULL,
    created_at      INTEGER DEFAULT (strftime('%s','now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE invite_codes (
    id              TEXT PRIMARY KEY,
    code            TEXT UNIQUE NOT NULL,
    created_by      TEXT,                      -- user_id of creator
    used_by         TEXT,                      -- user_id of user who used it
    tier_grant      TEXT DEFAULT 'free',       -- tier granted when code is used
    expires_at      TEXT,
    used_at         TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (used_by) REFERENCES users(id)
);

CREATE TABLE invite_redemptions (
    id          TEXT PRIMARY KEY,
    code        TEXT NOT NULL,
    used_by     TEXT NOT NULL,
    used_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(code, used_by)
);

CREATE TABLE spread_bonus_grants (
    id          TEXT PRIMARY KEY,
    inviter_id  TEXT NOT NULL,
    invitee_id  TEXT NOT NULL,
    xp          INTEGER NOT NULL,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(inviter_id, invitee_id)
);

CREATE TABLE usage_logs (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    tokens_used     INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE llm_usage (
    id           TEXT PRIMARY KEY,
    user_id      TEXT,                          -- NULL = 系统/后台调用
    provider     TEXT NOT NULL,
    model        TEXT NOT NULL,
    tokens_in    INTEGER DEFAULT 0,
    tokens_out   INTEGER DEFAULT 0,
    cost_yuan    REAL DEFAULT 0,                -- 按 llm_catalog 折算
    latency_ms   INTEGER DEFAULT 0,
    status       TEXT DEFAULT 'ok',             -- ok / error
    error        TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE quota_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    resource TEXT NOT NULL,
    date TEXT NOT NULL,
    used INTEGER DEFAULT 0,
    daily_limit INTEGER NOT NULL,
    UNIQUE(user_id, resource, date)
);

CREATE TABLE boost_packs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    pack_name TEXT NOT NULL DEFAULT '标准加量包',
    credits INTEGER NOT NULL,
    credits_used INTEGER DEFAULT 0,
    price_yuan INTEGER DEFAULT 29,
    purchased_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    status TEXT DEFAULT 'active'
);

CREATE TABLE boost_consumptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    boost_pack_id INTEGER NOT NULL REFERENCES boost_packs(id),
    resource TEXT NOT NULL,
    credits_consumed INTEGER DEFAULT 1,
    consumed_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE poems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    dynasty TEXT NOT NULL DEFAULT '',
    theme TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    tags TEXT DEFAULT '',              -- comma-separated tags for filtering
    source TEXT DEFAULT 'imported',    -- imported | manual
    created_at TEXT DEFAULT (datetime('now')), publisher_id TEXT REFERENCES users(id), column_id TEXT REFERENCES columns(id),
    UNIQUE(title, author)
);

CREATE TABLE driver_profiles (
    id            TEXT PRIMARY KEY,            -- = users.id（1:1 驾驶员）
    display_name  TEXT,
    tagline       TEXT,
    avatar_url    TEXT,
    bio           TEXT,
    show_resume   INTEGER NOT NULL DEFAULT 1,  -- 橱窗模块开关（千人千面第一层）
    show_mbti     INTEGER NOT NULL DEFAULT 1,
    show_social   INTEGER NOT NULL DEFAULT 1,
    show_columns  INTEGER NOT NULL DEFAULT 1,
    theme         TEXT NOT NULL DEFAULT '{}',  -- 主题/布局 JSON
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE columns (
    id            TEXT PRIMARY KEY,
    driver_id     TEXT NOT NULL,               -- 归属驾驶员
    slug          TEXT NOT NULL,               -- 专栏 URL slug
    name          TEXT NOT NULL,               -- 诗词 / 人力 / 法务 / 电梯 / 物联网
    description   TEXT,
    content_type  TEXT NOT NULL DEFAULT 'article',
    icon          TEXT,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (driver_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE (driver_id, slug)
);

CREATE TABLE articles (
    id                TEXT PRIMARY KEY,
    driver_id         TEXT NOT NULL,
    column_id         TEXT,
    title             TEXT NOT NULL,
    slug              TEXT NOT NULL,
    excerpt           TEXT,
    content           TEXT NOT NULL,
    tags              TEXT DEFAULT '',
    status            TEXT NOT NULL DEFAULT 'published',   -- draft | published
    view_count        INTEGER NOT NULL DEFAULT 0,
    comment_count     INTEGER NOT NULL DEFAULT 0,
    content_embedding TEXT DEFAULT NULL,       -- JSON 数组占位；向量真源在 Chroma
    published_at      TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (driver_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (column_id) REFERENCES columns(id),
    UNIQUE (driver_id, slug)
);

CREATE TABLE challenge_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_key TEXT NOT NULL UNIQUE,          -- e.g. 2026-W29
    poem_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',    -- open | closed
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (poem_id) REFERENCES poems(id)
);

CREATE TABLE challenge_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    translation TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    license_accepted INTEGER NOT NULL DEFAULT 0,
    vote_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(round_id, user_id),
    FOREIGN KEY (round_id) REFERENCES challenge_rounds(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    file_path TEXT NOT NULL UNIQUE,
    doc_type TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    chunk_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    processed_at TEXT
);

CREATE TABLE chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    char_count INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE query_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_text TEXT NOT NULL,
    provider TEXT NOT NULL,
    response_time_ms REAL DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    rating INTEGER DEFAULT NULL,
    intent_label TEXT DEFAULT NULL,
    user_id TEXT DEFAULT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE narrative_sessions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT DEFAULT NULL,          -- nullable (guests can play)
    domain          TEXT NOT NULL,              -- which domain was chosen
    status          TEXT DEFAULT 'active',       -- active | completed | abandoned
    duration_seconds REAL DEFAULT 0,
    started_at      TEXT DEFAULT (datetime('now')),
    ended_at        TEXT DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE narrative_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    event_type      TEXT NOT NULL,              -- domain_enter | choice_made | convergence_reached | share_attempt | replay
    domain          TEXT DEFAULT NULL,
    choice          TEXT DEFAULT NULL,
    navigator_line  TEXT DEFAULT NULL,
    metadata_json   TEXT DEFAULT '{}',
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES narrative_sessions(id)
);

CREATE TABLE narrative_feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    resonated       INTEGER NOT NULL DEFAULT 0, -- 0/1: did Navigator touch you?
    navigator_quote TEXT DEFAULT NULL,           -- recalled Navigator line
    would_replay    INTEGER DEFAULT NULL,        -- 0/1/2 (no/maybe/yes)
    shared          INTEGER NOT NULL DEFAULT 0, -- 0/1
    share_channel   TEXT DEFAULT NULL,           -- wechat | moments | link | other
    open_feedback   TEXT DEFAULT NULL,           -- free-text qualitative
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES narrative_sessions(id),
    UNIQUE(session_id)
);

CREATE TABLE value_imprints (
    user_id         TEXT NOT NULL,
    survival        INTEGER NOT NULL DEFAULT 0,
    freedom         INTEGER NOT NULL DEFAULT 0,
    belonging       INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE navigator_memories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    memory_level    TEXT NOT NULL,              -- surface | deep | fragment | taboo
    content         TEXT NOT NULL,
    context         TEXT DEFAULT NULL,
    domain          TEXT DEFAULT NULL,
    choice          TEXT DEFAULT NULL,
    importance      REAL DEFAULT 1.0,
    referenced_count INTEGER DEFAULT 0,
    session_id      TEXT DEFAULT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE emergent_strategy_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    strategy_type   TEXT NOT NULL,              -- poetry_refuge | trust_farming | unknown_speedrun | mbti_rejector | cross_domain_hacker
    triggered_at    TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE domain_visits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    domain          TEXT NOT NULL,
    previous_domain TEXT DEFAULT NULL,
    interaction_level TEXT DEFAULT NULL,        -- intended | acceptable | forbidden
    echo_triggered  INTEGER NOT NULL DEFAULT 0, -- 0/1
    entered_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (session_id) REFERENCES narrative_sessions(id)
);

CREATE TABLE product_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name      TEXT NOT NULL,
    user_id         TEXT DEFAULT NULL,
    session_id      TEXT DEFAULT NULL,
    platform        TEXT DEFAULT 'unknown',
    share_code      TEXT DEFAULT NULL,
    source          TEXT DEFAULT 'client',
    success         INTEGER NOT NULL DEFAULT 1,
    properties_json TEXT DEFAULT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE micro_feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    context         TEXT NOT NULL,
    score           INTEGER NOT NULL,
    optional_text   TEXT DEFAULT NULL,
    user_id         TEXT DEFAULT NULL,
    session_id      TEXT DEFAULT NULL,
    platform        TEXT DEFAULT 'unknown',
    share_code      TEXT DEFAULT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE act1_sessions (
    session_id      TEXT PRIMARY KEY,
    state_json      TEXT NOT NULL,
    updated_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES narrative_sessions(id)
);

CREATE TABLE quiz_sessions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    questions_json  TEXT NOT NULL DEFAULT '[]',   -- JSON array of all QuizQuestion
    current_index   INTEGER NOT NULL DEFAULT 0,
    answers_json    TEXT NOT NULL DEFAULT '[]',   -- JSON array of {question_id, option_ids, score}
    total_score     INTEGER NOT NULL DEFAULT 0,
    total_questions INTEGER NOT NULL DEFAULT 0,
    correct_count   INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'active', -- active | completed
    result_type     TEXT DEFAULT '',
    insights_json   TEXT DEFAULT '[]',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE match_reports (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    resume_id       TEXT DEFAULT '',
    resume_snapshot TEXT DEFAULT '',
    title           TEXT DEFAULT '',
    status          TEXT DEFAULT 'completed',   -- draft | completed | archived | deleted
    summary         TEXT DEFAULT '',
    metadata        TEXT DEFAULT '{}',          -- JSON: { total_jobs, matched_at, pipeline_version }
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE match_report_items (
    id                      TEXT PRIMARY KEY,
    report_id               TEXT NOT NULL,
    job_title               TEXT NOT NULL,
    company_name            TEXT NOT NULL,
    location                TEXT DEFAULT '',
    salary_range            TEXT DEFAULT '',
    jd_snapshot             TEXT DEFAULT '',
    overall_score           REAL DEFAULT 0,
    background_match        REAL DEFAULT 0,
    skills_overlap          REAL DEFAULT 0,
    experience_relevance    REAL DEFAULT 0,
    seniority               REAL DEFAULT 0,
    language_requirement    REAL DEFAULT 0,
    company_score           REAL DEFAULT 0,
    salary_match            REAL DEFAULT 0,
    location_match          REAL DEFAULT 0,
    culture_workload_match  REAL DEFAULT 0,
    match_reason            TEXT DEFAULT '',
    matched_skills          TEXT DEFAULT '[]',
    missing_skills          TEXT DEFAULT '[]',
    fit_bullets             TEXT DEFAULT '[]',
    gap_analysis            TEXT DEFAULT '[]',
    improvement_plan        TEXT DEFAULT '',
    credit_snapshot         TEXT DEFAULT '{}',
    rank_order              INTEGER DEFAULT 0,
    created_at              TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (report_id) REFERENCES match_reports(id) ON DELETE CASCADE
);

CREATE TABLE report_sharing (
    id                  TEXT PRIMARY KEY,
    report_id           TEXT NOT NULL,
    user_id             TEXT NOT NULL,
    shared_with_type    TEXT NOT NULL DEFAULT 'career_partner',
    shared_with_id      TEXT DEFAULT '',
    shared_dimensions   TEXT NOT NULL DEFAULT '[]',
    purpose             TEXT DEFAULT '',
    status              TEXT DEFAULT 'active',   -- active | revoked | expired
    granted_at          TEXT DEFAULT (datetime('now')),
    revoked_at          TEXT DEFAULT NULL,
    expires_at          TEXT DEFAULT NULL,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (report_id) REFERENCES match_reports(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE share_codes (
    id              TEXT PRIMARY KEY,              -- UUID
    code            TEXT UNIQUE NOT NULL,           -- sc_{random}
    owner_id        TEXT NOT NULL,                  -- candidate user_id who generated it
    scope           TEXT NOT NULL DEFAULT '[]',     -- JSON array: authorised claim_types
    max_access_count INTEGER NOT NULL DEFAULT 10,
    access_count    INTEGER NOT NULL DEFAULT 0,
    expires_at      TEXT NOT NULL,                  -- ISO 8601
    status          TEXT NOT NULL DEFAULT 'active', -- active | revoked | expired
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (owner_id) REFERENCES users(id)
);

CREATE TABLE verification_audit_log (
    id              TEXT PRIMARY KEY,              -- UUID
    share_code      TEXT NOT NULL,                 -- which code was used
    owner_id        TEXT NOT NULL,                 -- candidate whose data was accessed
    verifier_info   TEXT DEFAULT '',               -- caller IP / user-agent / optional identity
    attestation_ids TEXT NOT NULL DEFAULT '[]',    -- JSON array of accessed attestation IDs
    result          TEXT NOT NULL DEFAULT 'success', -- success | expired | exhausted | not_found
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (owner_id) REFERENCES users(id)
);

CREATE TABLE timeline_events (
    id                TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL,
    event_kind        TEXT NOT NULL,
    occurred_at       TEXT NOT NULL,
    recorded_at       TEXT NOT NULL DEFAULT (datetime('now')),
    source_system     TEXT NOT NULL,
    source_ref        TEXT DEFAULT '',
    title             TEXT DEFAULT '',
    summary           TEXT DEFAULT '',
    payload_json      TEXT DEFAULT '{}',
    signal_quality    TEXT NOT NULL DEFAULT 'observed',
    confidence        REAL DEFAULT 0.5,
    weight_role       TEXT NOT NULL DEFAULT 'evidence',
    visibility        TEXT NOT NULL DEFAULT 'private',
    consent_scope     TEXT DEFAULT '[]',
    status            TEXT NOT NULL DEFAULT 'active',
    superseded_by     TEXT DEFAULT NULL,
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE match_consensus (
    id              TEXT PRIMARY KEY,
    fleet_id        TEXT NOT NULL,
    initiator_id    TEXT NOT NULL,
    candidate_id    TEXT NOT NULL,
    match_score     INTEGER NOT NULL,
    status          TEXT DEFAULT 'pending',
    reason          TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now')),
    verified_at     TEXT,
    expires_at      TEXT NOT NULL,
    FOREIGN KEY (initiator_id) REFERENCES users(id),
    FOREIGN KEY (candidate_id) REFERENCES users(id)
);

CREATE INDEX idx_game_profiles_user ON game_profiles(user_id);
CREATE INDEX idx_fleet_members_user ON fleet_members(user_id);
CREATE INDEX idx_missions_user ON mission_completions(user_id);
CREATE INDEX idx_trust_memories_user ON trust_memories(user_id);
CREATE INDEX idx_trust_memories_session ON trust_memories(session_type, session_id);
CREATE INDEX idx_trust_attestations_candidate ON trust_attestations(candidate_id);
CREATE INDEX idx_trust_attestations_type ON trust_attestations(claim_type, verification_status);
CREATE INDEX idx_enterprise_users_enterprise ON enterprise_users(enterprise_id);
CREATE INDEX idx_enterprise_users_user ON enterprise_users(user_id);
CREATE INDEX idx_candidates_enterprise ON candidates(enterprise_id);
CREATE INDEX idx_job_posts_user ON job_posts(user_id);
CREATE INDEX idx_job_posts_status ON job_posts(user_id, status);
CREATE INDEX idx_applications_seeker ON applications(seeker_user_id);
CREATE INDEX idx_applications_job ON applications(job_id);
CREATE INDEX idx_applications_status ON applications(status);
CREATE UNIQUE INDEX idx_applications_active_unique
    ON applications(seeker_user_id, resume_id, job_id) WHERE status = 'submitted';
CREATE INDEX idx_sales_inquiries_status ON sales_inquiries(status);
CREATE INDEX idx_orders_user ON orders(user_id, created_at);
CREATE INDEX idx_orders_trade_no ON orders(out_trade_no);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_subscriptions_user ON subscriptions(user_id);
CREATE INDEX idx_subscriptions_expires ON subscriptions(expires_at);
CREATE UNIQUE INDEX idx_push_token ON huawei_push_tokens(push_token);
CREATE INDEX idx_push_user ON huawei_push_tokens(user_id);
CREATE INDEX idx_invite_codes_code ON invite_codes(code);
CREATE INDEX idx_invite_redemptions_code ON invite_redemptions(code);
CREATE INDEX idx_usage_logs_user_date ON usage_logs(user_id, created_at);
CREATE INDEX idx_llm_usage_provider_date ON llm_usage(provider, created_at);
CREATE INDEX idx_llm_usage_user_date ON llm_usage(user_id, created_at);
CREATE INDEX idx_quota_records_user ON quota_records(user_id, resource, date);
CREATE INDEX idx_boost_packs_user ON boost_packs(user_id, status);
CREATE INDEX idx_boost_packs_expires ON boost_packs(expires_at);
CREATE INDEX idx_boost_consumptions_user ON boost_consumptions(user_id);
CREATE INDEX idx_poems_dynasty ON poems(dynasty);
CREATE INDEX idx_poems_author ON poems(author);
CREATE INDEX idx_poems_theme ON poems(theme);
CREATE INDEX idx_poems_title ON poems(title);
CREATE INDEX idx_columns_driver ON columns(driver_id);
CREATE INDEX idx_articles_driver ON articles(driver_id);
CREATE INDEX idx_articles_column ON articles(column_id);
CREATE INDEX idx_challenge_rounds_status ON challenge_rounds(status);
CREATE INDEX idx_challenge_rounds_ends ON challenge_rounds(ends_at);
CREATE INDEX idx_challenge_entries_round ON challenge_entries(round_id);
CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_chunks_document ON chunks(document_id);
CREATE INDEX idx_query_logs_time ON query_logs(created_at);
CREATE INDEX idx_query_logs_user ON query_logs(user_id);
CREATE INDEX idx_narrative_sessions_user ON narrative_sessions(user_id);
CREATE INDEX idx_narrative_sessions_domain ON narrative_sessions(domain);
CREATE INDEX idx_narrative_events_session ON narrative_events(session_id);
CREATE INDEX idx_narrative_events_type ON narrative_events(event_type);
CREATE INDEX idx_narrative_feedback_session ON narrative_feedback(session_id);
CREATE INDEX idx_navigator_memories_user ON navigator_memories(user_id);
CREATE INDEX idx_navigator_memories_level ON navigator_memories(memory_level);
CREATE INDEX idx_emergent_strategy_user ON emergent_strategy_log(user_id);
CREATE INDEX idx_domain_visits_user ON domain_visits(user_id);
CREATE INDEX idx_domain_visits_session ON domain_visits(session_id);
CREATE INDEX idx_product_events_name ON product_events(event_name);
CREATE INDEX idx_product_events_created ON product_events(created_at);
CREATE INDEX idx_product_events_share ON product_events(share_code);
CREATE INDEX idx_micro_feedback_context ON micro_feedback(context);
CREATE INDEX idx_product_events_time ON product_events(created_at);
CREATE INDEX idx_quiz_sessions_user ON quiz_sessions(user_id, created_at);
CREATE INDEX idx_match_reports_user ON match_reports(user_id);
CREATE INDEX idx_match_reports_created ON match_reports(created_at);
CREATE INDEX idx_match_reports_status ON match_reports(status);
CREATE INDEX idx_report_items_report ON match_report_items(report_id);
CREATE INDEX idx_report_items_company ON match_report_items(company_name);
CREATE INDEX idx_sharing_report ON report_sharing(report_id);
CREATE INDEX idx_sharing_user ON report_sharing(user_id);
CREATE INDEX idx_sharing_status ON report_sharing(status);
CREATE INDEX idx_sharing_type ON report_sharing(shared_with_type);
CREATE INDEX idx_share_codes_code ON share_codes(code);
CREATE INDEX idx_share_codes_owner ON share_codes(owner_id);
CREATE INDEX idx_verification_audit_owner ON verification_audit_log(owner_id, created_at);
CREATE INDEX idx_verification_audit_code ON verification_audit_log(share_code);
CREATE INDEX idx_timeline_user_time
    ON timeline_events(user_id, occurred_at DESC);
CREATE INDEX idx_timeline_user_kind
    ON timeline_events(user_id, event_kind, occurred_at);
CREATE INDEX idx_timeline_source
    ON timeline_events(source_system, source_ref);
CREATE INDEX idx_match_consensus_initiator
    ON match_consensus(initiator_id, status);
CREATE INDEX idx_match_consensus_candidate
    ON match_consensus(candidate_id, status);
CREATE UNIQUE INDEX idx_trust_attestations_claim ON trust_attestations(candidate_id, claim_type);
CREATE INDEX idx_poems_publisher ON poems(publisher_id);
CREATE INDEX idx_poems_column ON poems(column_id);
CREATE UNIQUE INDEX idx_fleets_invite_code ON fleets(invite_code);

-- ============================================
-- signal_* 只读视图（裁决 2：产品侧经只读视图读，核独占写权；SQLite 视图无 INSTEAD OF 触发器即天然只读）
-- ============================================
CREATE VIEW IF NOT EXISTS v_core_signal_ingest AS SELECT * FROM signal_ingest;
CREATE VIEW IF NOT EXISTS v_core_signal_outbox AS SELECT * FROM signal_outbox;
CREATE VIEW IF NOT EXISTS v_core_signal_dlq  AS SELECT * FROM signal_dlq;
