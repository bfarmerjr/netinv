# SPDX-License-Identifier: AGPL-3.0-or-later
# NetInv — Copyright (C) 2026 Bill Farmer, Jr. See LICENSE.
import os
import sqlite3

from flask import current_app, g


def connect(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _migrate(conn):
    """Bring databases created by older versions up to the current schema."""
    node_cols = {r["name"] for r in conn.execute("PRAGMA table_info(node)")}
    if "role_tag_id" not in node_cols:  # added in 1.1.0
        conn.execute("ALTER TABLE node ADD COLUMN role_tag_id INTEGER REFERENCES tag(id) ON DELETE SET NULL")
    if "url" not in node_cols:  # added in 1.2.0
        conn.execute("ALTER TABLE node ADD COLUMN url TEXT")


def init_app(app):
    app.teardown_appcontext(close_db)
    conn = connect(app.config["DATABASE"])
    conn.isolation_level = None  # manage the transaction explicitly below
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        # Every gunicorn worker runs this at boot. Take the write lock first so
        # only one process creates or migrates the schema at a time; the others
        # wait (up to the connect timeout) and then find nothing left to do.
        conn.execute("BEGIN IMMEDIATE")
        # executescript() would commit first, so run statements one at a time.
        statement = ""
        with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
            for line in f:
                statement += line
                if sqlite3.complete_statement(statement):
                    conn.execute(statement)
                    statement = ""
        _migrate(conn)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
