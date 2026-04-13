-- AI-PA CRM — PostgreSQL Schema
-- Run as superuser to create DB, user, then switch to ai_crm_user for tables.
--
-- Usage:
--   psql -h 100.90.102.95 -U postgres -f schema.sql

-- ------------------------------------------------------------
-- Database & user
-- ------------------------------------------------------------

CREATE USER ai_crm_user WITH PASSWORD 'CHANGE_ME';
CREATE DATABASE ai_crm OWNER ai_crm_user;

\connect ai_crm

-- ------------------------------------------------------------
-- locations
-- One row per physical location of the business.
-- A single-location business has one row.
-- ------------------------------------------------------------

CREATE TABLE locations (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    address     TEXT,
    timezone    TEXT NOT NULL DEFAULT 'UTC',
    metadata    JSONB NOT NULL DEFAULT '{}',  -- channel IDs, operating hours, etc.
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------
-- contacts
-- One row per known person or company.
-- file_path: relative path to their CRM markdown file (nullable).
-- contact_type: free text — business defines its own (client, lead, technician, vendor, etc.)
-- ------------------------------------------------------------

CREATE TABLE contacts (
    id              SERIAL PRIMARY KEY,
    display_name    TEXT NOT NULL,
    contact_type    TEXT NOT NULL,               -- 'client_corporate', 'client_residential', 'lead', 'technician', 'vendor', etc.
    file_path       TEXT UNIQUE,                 -- e.g. 'wiki/clients/residential/singh-household.md'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------
-- contact_locations
-- Many-to-many: a contact can be associated with multiple locations.
-- is_primary: the location that manages this contact's record.
-- ------------------------------------------------------------

CREATE TABLE contact_locations (
    id          SERIAL PRIMARY KEY,
    contact_id  INT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    location_id INT NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    is_primary  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (contact_id, location_id)
);

-- ------------------------------------------------------------
-- contact_identifiers
-- Multiple identifiers per contact for inbound message matching.
-- Unique per (type, value) so a phone number maps to exactly one contact.
-- ------------------------------------------------------------

CREATE TABLE contact_identifiers (
    id              SERIAL PRIMARY KEY,
    contact_id      INT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    identifier_type TEXT NOT NULL,   -- 'phone', 'email', 'whatsapp', 'telegram_id', 'ip'
    identifier_value TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (identifier_type, identifier_value)
);

-- ------------------------------------------------------------
-- messages
-- Every message in or out, full content.
-- contact_id is nullable: unknown senders before a lead record is created.
-- location_id: which location this message came through.
-- topic: free text intent label (inquiry, complaint, booking, quote, follow-up, etc.)
-- ------------------------------------------------------------

CREATE TABLE messages (
    id                SERIAL PRIMARY KEY,
    contact_id        INT REFERENCES contacts(id) ON DELETE SET NULL,
    location_id       INT REFERENCES locations(id) ON DELETE SET NULL,
    channel           TEXT NOT NULL,    -- 'telegram', 'whatsapp', 'email'
    direction         TEXT NOT NULL,    -- 'inbound', 'outbound'
    content           TEXT NOT NULL,
    summary           TEXT,             -- one-line AI-written summary for the CRM file
    topic             TEXT,             -- intent: 'inquiry', 'complaint', 'quote', 'booking', etc.
    status            TEXT NOT NULL DEFAULT 'received',  -- 'received', 'pending_approval', 'sent', 'rejected'
    channel_metadata  JSONB NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------
-- message_threads
-- Links inbound → draft → final outbound. Tracks the approval lifecycle.
-- ------------------------------------------------------------

CREATE TABLE message_threads (
    id                  SERIAL PRIMARY KEY,
    inbound_message_id  INT REFERENCES messages(id) ON DELETE SET NULL,
    outbound_message_id INT REFERENCES messages(id) ON DELETE SET NULL,
    draft_content       TEXT,
    final_content       TEXT,       -- may differ from draft if owner edited
    status              TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'approved', 'edited', 'rejected'
    approved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------
-- event_log
-- Append-only raw activity log. No foreign keys.
-- Designed for quick parsing and troubleshooting.
-- Query: SELECT * FROM event_log ORDER BY created_at DESC LIMIT 50;
-- ------------------------------------------------------------

CREATE TABLE event_log (
    id              SERIAL PRIMARY KEY,
    location_id     INT,             -- loose reference, no FK constraint
    identifier      TEXT,            -- e.g. '+60 12-777-6666', 'abc@gmail.com'
    identifier_type TEXT,            -- 'phone', 'email', 'whatsapp', 'telegram_id', 'ip'
    channel         TEXT,            -- 'telegram', 'whatsapp', 'email'
    direction       TEXT,            -- 'in', 'out'
    event_type      TEXT,            -- 'message_received', 'draft_created', 'approved', 'rejected', 'edited', 'record_created', 'record_updated', 'error'
    note            TEXT,            -- free text description
    ref_id          TEXT,            -- loose reference to message_id or thread_id (no FK)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------
-- Indexes
-- ------------------------------------------------------------

CREATE INDEX idx_contact_identifiers_lookup
    ON contact_identifiers (identifier_type, identifier_value);

CREATE INDEX idx_messages_contact
    ON messages (contact_id);

CREATE INDEX idx_messages_status
    ON messages (status);

CREATE INDEX idx_event_log_identifier
    ON event_log (identifier, identifier_type);

CREATE INDEX idx_event_log_created
    ON event_log (created_at DESC);

-- ------------------------------------------------------------
-- Grants
-- ------------------------------------------------------------

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ai_crm_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ai_crm_user;

-- ------------------------------------------------------------
-- Seed: default location
-- ------------------------------------------------------------

INSERT INTO locations (name, address, timezone)
VALUES ('Main', NULL, 'Asia/Kuala_Lumpur');
