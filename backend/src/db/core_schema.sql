-- core_schema.sql（刀3 DDL 拆分，源 = manager.py 实库 schema @0dbf55e 分包分支）
-- R1：core 独占 users / user_identities 写权；本文件 7 表由 thomas_core 全权拥有。
-- 同库不拆文件：product_schema.sql 与本文件建在同一 DB；FK 只许 product -> users.id。

CREATE TABLE users (
    id              TEXT PRIMARY KEY,          -- looma uuid4
    email           TEXT UNIQUE,               -- Web registration (nullable for miniprogram-only)
    email_hash      TEXT,                      -- sha256(lower(trim(email))) for chain B user_id_hash
    password_hash   TEXT,                      -- bcrypt hash (nullable for miniprogram-only)
    wechat_openid   TEXT UNIQUE,               -- WeChat miniprogram login
    supabase_uid    TEXT UNIQUE,               -- Supabase Auth user UUID (THOMAS 统一身份, RFC supabase-unified-auth-v1)
    principal_sub   TEXT UNIQUE,               -- GFCC principal.sub（认钱认人）；缺省 bootstrap=id
    name            TEXT DEFAULT '',
    tier            TEXT DEFAULT 'free',       -- free | supporter | pro
    role            TEXT DEFAULT 'user',       -- user | admin
    is_early_adopter INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE user_identities (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    provider        TEXT NOT NULL,              -- google | apple | wechat | email
    provider_uid    TEXT NOT NULL,              -- platform-specific user ID (sub / openid / email)
    provider_email  TEXT,                       -- email from provider (if available)
    provider_name   TEXT,                       -- display name from provider
    metadata_json   TEXT DEFAULT '{}',          -- extra provider data (avatar, locale, etc.)
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(provider, provider_uid)
);

CREATE TABLE signal_ingest (
    signal_type      TEXT NOT NULL,
    user_email_hash  TEXT NOT NULL,
    nonce            TEXT NOT NULL,
    payload_json     TEXT,
    created_at       TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (signal_type, user_email_hash, nonce)
);

CREATE TABLE signal_outbox (
    id              TEXT PRIMARY KEY,
    nonce           TEXT NOT NULL UNIQUE,
    signal_type     TEXT NOT NULL,                      -- personality_beacon | consensus_match | ...
    body            TEXT NOT NULL,                      -- json.dumps(envelope, separators=(",", ":")) 原文
    status          TEXT NOT NULL DEFAULT 'pending',    -- pending | delivered
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    delivered_at    TEXT
);

CREATE TABLE signal_dlq (
    id              TEXT PRIMARY KEY,
    nonce           TEXT NOT NULL UNIQUE,
    signal_type     TEXT NOT NULL,
    body            TEXT NOT NULL,
    reason          TEXT NOT NULL,                      -- permanent_4xx | network_error
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    moved_at        TEXT DEFAULT (datetime('now')),
    replayed_at     TEXT                                -- 值班重发成功时间
);

CREATE TABLE consents (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    scope           TEXT NOT NULL,              -- e.g. 'resume_upload', 'credit_query'
    purpose         TEXT DEFAULT '',            -- human-readable purpose
    status          TEXT DEFAULT 'granted',     -- granted | revoked | expired
    ip              TEXT DEFAULT '',
    user_agent      TEXT DEFAULT '',
    granted_at      TEXT DEFAULT (datetime('now')),
    revoked_at      TEXT DEFAULT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE audit_logs (
    id              TEXT PRIMARY KEY,
    actor           TEXT NOT NULL,              -- user_id performing the action
    action          TEXT NOT NULL,              -- e.g. 'resume_parse', 'credit_check'
    resource_type   TEXT NOT NULL,              -- e.g. 'resume', 'job', 'consent'
    resource_id     TEXT DEFAULT '',
    consent_id      TEXT DEFAULT '',            -- associated consent record
    metadata        TEXT DEFAULT '{}',          -- JSON, NO PII
    ip              TEXT DEFAULT '',
    user_agent      TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_wechat_openid ON users(wechat_openid);
CREATE INDEX idx_user_identities_user ON user_identities(user_id);
CREATE INDEX idx_user_identities_provider ON user_identities(provider, provider_uid);
CREATE INDEX idx_signal_outbox_status ON signal_outbox(status, created_at);
CREATE INDEX idx_signal_dlq_moved ON signal_dlq(moved_at);
CREATE UNIQUE INDEX idx_consents_active ON consents(user_id, scope) WHERE status='granted';
CREATE INDEX idx_consents_user ON consents(user_id);
CREATE INDEX idx_consents_scope ON consents(scope);
CREATE INDEX idx_audit_logs_actor ON audit_logs(actor);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_time ON audit_logs(created_at);
CREATE INDEX idx_users_email_hash ON users(email_hash);
CREATE UNIQUE INDEX idx_users_supabase_uid ON users(supabase_uid);
CREATE UNIQUE INDEX idx_users_principal_sub ON users(principal_sub);
CREATE TRIGGER trg_users_role_check_insert
BEFORE INSERT ON users
FOR EACH ROW WHEN NEW.role IS NOT NULL
     AND NEW.role NOT IN ('user','enterprise','admin','driver')
BEGIN
    SELECT RAISE(ABORT, 'users.role must be one of: user enterprise admin driver');
END;
CREATE TRIGGER trg_users_role_check_update
BEFORE UPDATE OF role ON users
FOR EACH ROW WHEN NEW.role IS NOT NULL
     AND NEW.role NOT IN ('user','enterprise','admin','driver')
BEGIN
    SELECT RAISE(ABORT, 'users.role must be one of: user enterprise admin driver');
END;

-- invitation.v1，not_required。opaque handle 不编码身份。策略只登记允许签发的组合。
CREATE TABLE IF NOT EXISTS invitations (
    id                TEXT PRIMARY KEY,
    tenant            TEXT NOT NULL,
    audience          TEXT NOT NULL,
    purpose           TEXT NOT NULL,
    issuer_sub        TEXT NOT NULL,
    recipient_sub     TEXT,
    status            TEXT NOT NULL DEFAULT 'active',
    max_redemptions   INTEGER NOT NULL DEFAULT 1,
    redemption_count  INTEGER NOT NULL DEFAULT 0,
    device_policy     TEXT NOT NULL DEFAULT 'not_required',
    extensions_json   TEXT NOT NULL DEFAULT '{}',
    idempotency_key   TEXT NOT NULL UNIQUE,
    issued_at         TEXT NOT NULL,
    expires_at        TEXT NOT NULL,
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_invitations_tenant_audience
    ON invitations(tenant, audience, status);

CREATE TABLE IF NOT EXISTS invitation_redemptions (
    id                       TEXT PRIMARY KEY,
    invitation_id            TEXT NOT NULL,
    audience                 TEXT NOT NULL,
    purpose                  TEXT NOT NULL,
    redeemer_sub             TEXT NOT NULL,
    device_verification_json TEXT NOT NULL DEFAULT '{}',
    idempotency_key          TEXT NOT NULL UNIQUE,
    redeemed_at              TEXT NOT NULL,
    FOREIGN KEY (invitation_id) REFERENCES invitations(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_redemptions_invite_redeemer
    ON invitation_redemptions(invitation_id, redeemer_sub);

CREATE TABLE IF NOT EXISTS tenant_audience_policies (
    tenant        TEXT NOT NULL,
    audience      TEXT NOT NULL,
    purpose       TEXT NOT NULL,
    issue_allowed INTEGER NOT NULL DEFAULT 0,
    device_policy TEXT NOT NULL DEFAULT 'not_required',
    PRIMARY KEY (tenant, audience, purpose)
);

INSERT OR IGNORE INTO tenant_audience_policies
    (tenant, audience, purpose, issue_allowed, device_policy)
VALUES
    ('genzer.terminal', 'genzer.terminal.registration', 'account_registration', 1, 'not_required');

-- 设备证明信封。credential_id 只用于查找。默认策略仍是上面那条 not_required。
CREATE TABLE IF NOT EXISTS device_challenges (
    challenge_id      TEXT PRIMARY KEY,
    nonce             TEXT NOT NULL,
    audience          TEXT NOT NULL,
    principal_binding TEXT NOT NULL,
    purpose           TEXT NOT NULL,
    invitation_id     TEXT NOT NULL,
    expires_at        TEXT NOT NULL,
    consumed          INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS device_credentials (
    credential_id  TEXT PRIMARY KEY,
    principal_sub  TEXT NOT NULL,
    audience       TEXT NOT NULL,
    verifier_ref   TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',
    enrolled_at    TEXT DEFAULT (datetime('now'))
);

-- 认账最小闭环：计数器回滚即拒绝，jti 在有效期内不能再用。不是设备总表。
CREATE TABLE IF NOT EXISTS device_counter (
    credential_id TEXT PRIMARY KEY,
    last_cnt      INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pop_replay (
    jti           TEXT PRIMARY KEY,
    credential_id TEXT NOT NULL,
    expire_at     TEXT NOT NULL,
    seen_at       TEXT DEFAULT (datetime('now'))
);
