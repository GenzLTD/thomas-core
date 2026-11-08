-- profile scope：画像事实层。Chroma 只检索，本表是唯一事实源。
-- 追加写入，不改历史行。FK 只指向 core 的 users.id。

CREATE TABLE profile_events (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    domain              TEXT NOT NULL,          -- career/learning/life/social/health/creative
    event_type          TEXT NOT NULL,          -- quiz_result / ask_interaction / consent_change
    payload_json        TEXT NOT NULL,
    source              TEXT,                   -- game / ask / manual
    consent_scope       TEXT NOT NULL,          -- 摄入时点的授权范围快照
    enterprise_visible  INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX idx_pe_user_time ON profile_events(user_id, created_at);
CREATE INDEX idx_pe_domain ON profile_events(user_id, domain, created_at);
