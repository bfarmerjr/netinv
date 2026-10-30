-- SPDX-License-Identifier: AGPL-3.0-or-later
-- NetInv — Copyright (C) 2026 Bill Farmer, Jr. See LICENSE.
CREATE TABLE IF NOT EXISTS node (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    ip          TEXT NOT NULL,
    fqdn        TEXT,
    url         TEXT,
    notes       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    -- Primary tag ("role"); must be one of the node's tags.
    role_tag_id INTEGER REFERENCES tag(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS tag (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS check_item (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS node_tag (
    node_id INTEGER NOT NULL REFERENCES node(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    PRIMARY KEY (node_id, tag_id)
);

CREATE TABLE IF NOT EXISTS tag_check (
    tag_id   INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    check_id INTEGER NOT NULL REFERENCES check_item(id) ON DELETE CASCADE,
    PRIMARY KEY (tag_id, check_id)
);

-- Current state of a check on a node. Missing row means "pending".
-- Rows are kept when a check stops applying, so re-adding a tag restores state.
CREATE TABLE IF NOT EXISTS check_status (
    node_id    INTEGER NOT NULL REFERENCES node(id) ON DELETE CASCADE,
    check_id   INTEGER NOT NULL REFERENCES check_item(id) ON DELETE CASCADE,
    state      TEXT NOT NULL CHECK (state IN ('pending', 'compliant', 'na')),
    changed_at TEXT NOT NULL,
    PRIMARY KEY (node_id, check_id)
);

-- Audit log of every state change. Names are snapshotted so history
-- survives renames and deletions.
CREATE TABLE IF NOT EXISTS status_log (
    id         INTEGER PRIMARY KEY,
    node_id    INTEGER REFERENCES node(id) ON DELETE SET NULL,
    check_id   INTEGER REFERENCES check_item(id) ON DELETE SET NULL,
    node_name  TEXT NOT NULL,
    check_name TEXT NOT NULL,
    old_state  TEXT NOT NULL,
    new_state  TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    client_ip  TEXT
);
CREATE INDEX IF NOT EXISTS status_log_node ON status_log(node_id, id);

-- Small key/value store for site settings (e.g. the admin info shown in the header).
CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
