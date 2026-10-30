# SPDX-License-Identifier: AGPL-3.0-or-later
# NetInv — Copyright (C) 2026 Bill Farmer, Jr. See LICENSE.
import csv
import io
import ipaddress
import json
import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    get_template_attribute,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from markupsafe import Markup, escape

from . import markdown

from .db import get_db

bp = Blueprint("main", __name__)

STATES = ("pending", "compliant", "na")
STATE_LABELS = {"pending": "Pending", "compliant": "Compliant", "na": "N/A"}
STATUS_FILTERS = {"incomplete": "Needs attention", "complete": "Complete", "none": "No checks"}

FQDN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))*$"
)
SEP = "\x1f"  # GROUP_CONCAT separator that can't appear in tag names


# ---------------------------------------------------------------- helpers

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean(value, limit=200):
    return " ".join((value or "").split())[:limit]


def wants_json():
    return request.is_json or request.accept_mimetypes.best == "application/json"


def parse_tags(raw):
    seen = {}
    for part in (raw or "").split(","):
        name = clean(part, 64)
        if name and name.lower() not in seen:
            seen[name.lower()] = name
    return list(seen.values())


def ensure_tag(db, name):
    row = db.execute("SELECT id FROM tag WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    return db.execute(
        "INSERT INTO tag (name, created_at) VALUES (?, ?)", (name, now_iso())
    ).lastrowid


def set_node_tags(db, node_id, names):
    ids = [ensure_tag(db, n) for n in names]
    db.execute("DELETE FROM node_tag WHERE node_id = ?", (node_id,))
    db.executemany(
        "INSERT OR IGNORE INTO node_tag (node_id, tag_id) VALUES (?, ?)",
        [(node_id, i) for i in ids],
    )


def set_node_role(db, node_id, role_name):
    """Set the node's role to one of its own tags (by name), or clear it."""
    row = None
    if role_name:
        row = db.execute(
            "SELECT t.id FROM tag t JOIN node_tag nt ON nt.tag_id = t.id WHERE nt.node_id = ? AND t.name = ?",
            (node_id, role_name),
        ).fetchone()
    db.execute("UPDATE node SET role_tag_id = ? WHERE id = ?", (row["id"] if row else None, node_id))


NODE_SQL = "SELECT n.*, r.name AS role FROM node n LEFT JOIN tag r ON r.id = n.role_tag_id"


def tags_by_node(db):
    out = {}
    for r in db.execute(
        "SELECT nt.node_id, t.id, t.name FROM node_tag nt JOIN tag t ON t.id = nt.tag_id "
        "ORDER BY t.name COLLATE NOCASE"
    ):
        out.setdefault(r["node_id"], []).append({"id": r["id"], "name": r["name"]})
    return out


def checks_by_node(db, node_id=None):
    """Checks that apply to each node: the union of checks over its tags."""
    where = "WHERE nt.node_id = ?" if node_id is not None else ""
    sql = f"""
        SELECT nt.node_id, c.id AS check_id, c.name, c.description,
               GROUP_CONCAT(t.name, '{SEP}') AS via_tags,
               COALESCE(s.state, 'pending') AS state, s.changed_at
        FROM node_tag nt
        JOIN tag t         ON t.id = nt.tag_id
        JOIN tag_check tc  ON tc.tag_id = nt.tag_id
        JOIN check_item c  ON c.id = tc.check_id
        LEFT JOIN check_status s ON s.node_id = nt.node_id AND s.check_id = c.id
        {where}
        GROUP BY nt.node_id, c.id
        ORDER BY c.name COLLATE NOCASE
    """
    out = {}
    for r in db.execute(sql, (node_id,) if node_id is not None else ()):
        d = dict(r)
        d["via_tags"] = sorted(d["via_tags"].split(SEP), key=str.lower)
        out.setdefault(d["node_id"], []).append(d)
    return out


def summarize(checks):
    total = len(checks)
    na = sum(c["state"] == "na" for c in checks)
    compliant = sum(c["state"] == "compliant" for c in checks)
    applicable = total - na
    pending = applicable - compliant
    if applicable:
        pct = round(100 * compliant / applicable)
    else:
        pct = 100 if total else None
    status = "none" if not total else ("complete" if not pending else "incomplete")
    return {
        "total": total, "compliant": compliant, "pending": pending, "na": na,
        "applicable": applicable, "pct": pct, "status": status,
    }


def donut(summary, size=28):
    """Ring split into one chunk per check, coloured by state."""
    n = summary["total"]
    # r chosen so the circumference is 100 and dash lengths are percentages.
    ring = '<circle cx="18" cy="18" r="15.9155" class="{cls}" stroke-dasharray="{dash}" stroke-dashoffset="{off}"/>'
    parts = []
    if not n:
        parts.append(ring.format(cls="d-empty", dash="100 0", off="0"))
    else:
        seg = 100 / n
        gap = min(2.5, seg * 0.3) if n > 1 else 0
        i = 0
        for state in ("compliant", "pending", "na"):
            for _ in range(summary[state]):
                parts.append(ring.format(
                    cls=f"d-{state}",
                    dash=f"{seg - gap:.3f} {100 - seg + gap:.3f}",
                    off=f"{-(i * seg + gap / 2):.3f}",
                ))
                i += 1
    label = f"{summary['compliant']} compliant, {summary['pending']} pending, {summary['na']} N/A"
    return Markup(
        f'<svg class="donut" viewBox="0 0 36 36" width="{int(size)}" height="{int(size)}" role="img" '
        f'aria-label="{label}"><g transform="rotate(-90 18 18)">{"".join(parts)}</g></svg>'
    )


def node_items(db, q="", tag="", status=""):
    nodes = db.execute(NODE_SQL + " ORDER BY n.name COLLATE NOCASE").fetchall()
    tags = tags_by_node(db)
    checks = checks_by_node(db)
    items = []
    for n in nodes:
        ntags = tags.get(n["id"], [])
        nchecks = checks.get(n["id"], [])
        summary = summarize(nchecks)
        tag_names = [t["name"].lower() for t in ntags]
        if q:
            hay = " ".join([n["name"], n["ip"] or "", n["fqdn"] or "", n["notes"] or "", *tag_names])
            if q.lower() not in hay.lower():
                continue
        if tag and tag.lower() not in tag_names:
            continue
        if status and summary["status"] != status:
            continue
        items.append({"node": n, "tags": ntags, "checks": nchecks, "summary": summary})
    return items


def totals(items):
    t = {
        "nodes": len(items),
        "complete": sum(i["summary"]["status"] == "complete" for i in items),
        "incomplete": sum(i["summary"]["status"] == "incomplete" for i in items),
        "none": sum(i["summary"]["status"] == "none" for i in items),
    }
    for k in ("compliant", "pending", "na", "applicable", "total"):
        t[k] = sum(i["summary"][k] for i in items)
    t["pct"] = round(100 * t["compliant"] / t["applicable"]) if t["applicable"] else None
    return t


def get_node(db, node_id):
    node = db.execute(NODE_SQL + " WHERE n.id = ?", (node_id,)).fetchone()
    if node is None:
        abort(404)
    return node


def all_tags(db):
    return db.execute("SELECT id, name FROM tag ORDER BY name COLLATE NOCASE").fetchall()


def all_checks(db):
    return db.execute("SELECT id, name FROM check_item ORDER BY name COLLATE NOCASE").fetchall()


def list_filters():
    status = request.args.get("status", "")
    return {
        "q": request.args.get("q", "").strip(),
        "tag": request.args.get("tag", "").strip(),
        "status": status if status in STATUS_FILTERS else "",
    }


# ---------------------------------------------------------------- nodes

@bp.get("/")
def nodes():
    db = get_db()
    f = list_filters()
    return render_template(
        "nodes.html",
        items=node_items(db, **f),
        counts=totals(node_items(db)),
        all_tags=all_tags(db),
        status_filters=STATUS_FILTERS,
        **f,
    )


# ---------------------------------------------------------------- summary

SUMMARY_VIEWS = (("rings", "Rings"), ("stacked", "Stacked bars"), ("bars", "Side-by-side"), ("text", "Text"))


def role_groups(items):
    """Totals per role, roles alphabetically, nodes without a role last."""
    groups = {}
    for i in items:
        groups.setdefault(i["node"]["role"], []).append(i)
    out = [{"role": role, "label": role or "No role", "totals": totals(members)} for role, members in groups.items()]
    return sorted(out, key=lambda g: (g["role"] is None, (g["role"] or "").lower()))


def ring(t, size=96):
    """Proportional ring (one arc per state) with the percentage in the middle."""
    arc = '<circle cx="18" cy="18" r="15.9155" class="{cls}" stroke-dasharray="{dash}" stroke-dashoffset="{off}"/>'
    parts = [arc.format(cls="d-empty", dash="100 0", off="0")]
    if t["total"]:
        shares = [(s, 100 * t[s] / t["total"]) for s in ("compliant", "pending", "na") if t[s]]
        gap = 1.2 if len(shares) > 1 else 0
        start = 0
        for state, share in shares:
            parts.append(arc.format(
                cls=f"d-{state}", dash=f"{max(share - gap, 0.4):.3f} {100 - max(share - gap, 0.4):.3f}",
                off=f"{-(start + gap / 2):.3f}",
            ))
            start += share
    pct = "—" if t["pct"] is None else f"{t['pct']}%"
    label = f"{pct} compliant: {t['compliant']} compliant, {t['pending']} pending, {t['na']} N/A"
    return Markup(
        f'<svg class="donut ring" viewBox="0 0 36 36" width="{int(size)}" height="{int(size)}" role="img" '
        f'aria-label="{escape(label)}"><g transform="rotate(-90 18 18)">{"".join(parts)}</g>'
        f'<text x="18" y="18" class="ring-pct">{pct}</text></svg>'
    )


@bp.get("/summary")
def summary():
    items = node_items(get_db())
    groups = role_groups(items)
    peak = max([max(g["totals"]["compliant"], g["totals"]["pending"], g["totals"]["na"]) for g in groups] or [0])
    return render_template(
        "summary.html", overall=totals(items), groups=groups, peak=peak, views=SUMMARY_VIEWS, ring=ring,
    )


def node_form_data():
    form = request.form
    data = {
        "name": clean(form.get("name"), 100),
        "ip": form.get("ip", "").strip(),
        "fqdn": form.get("fqdn", "").strip().rstrip(".").lower(),
        "url": form.get("url", "").strip()[:2000],
        "notes": form.get("notes", "").strip()[:4000],
    }
    tags = parse_tags(form.get("tags"))
    role = clean(form.get("role"), 64)
    data["role"] = next((t for t in tags if t.lower() == role.lower()), None)
    errors = {}
    if not data["name"]:
        errors["name"] = "Name is required."
    if not data["ip"]:
        errors["ip"] = "IP address is required."
    else:
        try:
            data["ip"] = str(ipaddress.ip_address(data["ip"]))
        except ValueError:
            errors["ip"] = "Not a valid IPv4 or IPv6 address."
    if not data["fqdn"]:
        errors["fqdn"] = "FQDN is required."
    elif not FQDN_RE.match(data["fqdn"]):
        errors["fqdn"] = "Not a valid hostname (letters, digits, hyphens, dot-separated)."
    if data["url"] and not valid_url(data["url"]):
        errors["url"] = "Enter a full http:// or https:// URL."
    return data, tags, errors


def valid_url(url):
    """Only absolute http(s) URLs, so links can never run script."""
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.netloc) and not any(c.isspace() for c in url)


def name_taken(db, name, exclude_id=None):
    row = db.execute("SELECT id FROM node WHERE name = ?", (name,)).fetchone()
    return row is not None and row["id"] != exclude_id


@bp.route("/nodes/new", methods=["GET", "POST"])
def node_new():
    db = get_db()
    data, tags, errors = {}, [], {}
    if request.method == "POST":
        data, tags, errors = node_form_data()
        if not errors and name_taken(db, data["name"]):
            errors["name"] = "A node with this name already exists."
        if not errors:
            ts = now_iso()
            node_id = db.execute(
                "INSERT INTO node (name, ip, fqdn, url, notes, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (data["name"], data["ip"], data["fqdn"] or None, data["url"] or None, data["notes"] or None, ts, ts),
            ).lastrowid
            set_node_tags(db, node_id, tags)
            set_node_role(db, node_id, data["role"])
            db.commit()
            flash(f"Added {data['name']}.", "ok")
            return redirect(url_for(".node_detail", node_id=node_id))
    return render_template(
        "node_form.html", node=data, tags=", ".join(tags), errors=errors,
        all_tags=all_tags(db), is_new=True,
    ), 400 if errors else 200


@bp.get("/nodes/<int:node_id>")
def node_detail(node_id):
    db = get_db()
    node = get_node(db, node_id)
    checks = checks_by_node(db, node_id).get(node_id, [])
    history = db.execute(
        "SELECT * FROM status_log WHERE node_id = ? ORDER BY id DESC LIMIT 15", (node_id,)
    ).fetchall()
    return render_template(
        "node_detail.html",
        node=node,
        tags=tags_by_node(db).get(node_id, []),
        checks=checks,
        summary=summarize(checks),
        history=history,
    )


@bp.route("/nodes/<int:node_id>/edit", methods=["GET", "POST"])
def node_edit(node_id):
    db = get_db()
    node = get_node(db, node_id)
    errors = {}
    if request.method == "POST":
        data, tags, errors = node_form_data()
        if not errors and name_taken(db, data["name"], node_id):
            errors["name"] = "A node with this name already exists."
        if not errors:
            db.execute(
                "UPDATE node SET name = ?, ip = ?, fqdn = ?, url = ?, notes = ?, updated_at = ? WHERE id = ?",
                (data["name"], data["ip"], data["fqdn"] or None, data["url"] or None, data["notes"] or None, now_iso(), node_id),
            )
            set_node_tags(db, node_id, tags)
            set_node_role(db, node_id, data["role"])
            db.commit()
            flash("Saved changes.", "ok")
            return redirect(url_for(".node_detail", node_id=node_id))
        data["id"] = node_id
    else:
        data = dict(node)
        tags = [t["name"] for t in tags_by_node(db).get(node_id, [])]
    return render_template(
        "node_form.html", node=data, tags=", ".join(tags), errors=errors,
        all_tags=all_tags(db), is_new=False,
    ), 400 if errors else 200


@bp.post("/nodes/<int:node_id>/role")
def node_role(node_id):
    db = get_db()
    get_node(db, node_id)
    set_node_role(db, node_id, clean(request.form.get("role"), 64))
    db.execute("UPDATE node SET updated_at = ? WHERE id = ?", (now_iso(), node_id))
    db.commit()
    flash("Role updated.", "ok")
    return redirect(url_for(".node_detail", node_id=node_id))


@bp.post("/nodes/<int:node_id>/delete")
def node_delete(node_id):
    db = get_db()
    node = get_node(db, node_id)
    db.execute("DELETE FROM node WHERE id = ?", (node_id,))
    db.commit()
    flash(f"Deleted {node['name']}.", "ok")
    return redirect(url_for(".nodes"))


@bp.post("/nodes/<int:node_id>/checks/<int:check_id>")
def set_check_state(node_id, check_id):
    db = get_db()
    node = get_node(db, node_id)
    payload = request.get_json(silent=True) or request.form
    state = payload.get("state")
    if state not in STATES:
        abort(400)
    check = next((c for c in checks_by_node(db, node_id).get(node_id, []) if c["check_id"] == check_id), None)
    if check is None:
        abort(404)
    if check["state"] != state:
        ts = now_iso()
        db.execute(
            "INSERT INTO check_status (node_id, check_id, state, changed_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (node_id, check_id) DO UPDATE SET state = excluded.state, changed_at = excluded.changed_at",
            (node_id, check_id, state, ts),
        )
        db.execute(
            "INSERT INTO status_log (node_id, check_id, node_name, check_name, old_state, new_state, changed_at, client_ip) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (node_id, check_id, node["name"], check["name"], check["state"], state, ts, request.remote_addr),
        )
        db.commit()
    if wants_json():
        checks = checks_by_node(db, node_id).get(node_id, [])
        check = next(c for c in checks if c["check_id"] == check_id)
        summary = summarize(checks)
        progress = get_template_attribute("_macros.html", "progress")
        return jsonify(
            state=check["state"], changed_at=check["changed_at"],
            summary=summary, progress_html=str(progress(summary, 40)),
        )
    return redirect(url_for(".node_detail", node_id=node_id, _anchor=f"check-{check_id}"))


# ---------------------------------------------------------------- configuration

def _save_links(db, table, fixed_col, fixed_id, other_col, other_ids):
    db.execute(f"DELETE FROM {table} WHERE {fixed_col} = ?", (fixed_id,))
    db.executemany(
        f"INSERT OR IGNORE INTO {table} ({fixed_col}, {other_col}) VALUES (?, ?)",
        [(fixed_id, o) for o in other_ids],
    )


@bp.get("/config")
def config():
    return redirect(url_for(".config_checks"))


@bp.route("/config/checks", methods=["GET", "POST"])
def config_checks():
    db = get_db()
    if request.method == "POST":
        name = clean(request.form.get("name"), 120)
        desc = request.form.get("description", "").strip()[:1000]
        if not name:
            flash("Check name is required.", "error")
        else:
            try:
                cid = db.execute(
                    "INSERT INTO check_item (name, description, created_at) VALUES (?, ?, ?)",
                    (name, desc or None, now_iso()),
                ).lastrowid
                _save_links(db, "tag_check", "check_id", cid, "tag_id", request.form.getlist("tag_ids", type=int))
                db.commit()
                flash(f"Added check “{name}”.", "ok")
            except sqlite3.IntegrityError:
                flash(f"A check named “{name}” already exists.", "error")
        return redirect(url_for(".config_checks"))

    checks = db.execute(
        """SELECT c.*,
                  (SELECT COUNT(DISTINCT nt.node_id) FROM tag_check tc
                   JOIN node_tag nt ON nt.tag_id = tc.tag_id WHERE tc.check_id = c.id) AS node_count
           FROM check_item c ORDER BY c.name COLLATE NOCASE"""
    ).fetchall()
    links = {}
    for r in db.execute(
        "SELECT tc.check_id, t.id, t.name FROM tag_check tc JOIN tag t ON t.id = tc.tag_id "
        "ORDER BY t.name COLLATE NOCASE"
    ):
        links.setdefault(r["check_id"], []).append(r)
    return render_template("config/checks.html", checks=checks, links=links, tags=all_tags(db))


@bp.post("/config/checks/<int:check_id>")
def config_check_update(check_id):
    db = get_db()
    name = clean(request.form.get("name"), 120)
    desc = request.form.get("description", "").strip()[:1000]
    if not name:
        flash("Check name is required.", "error")
        return redirect(url_for(".config_checks"))
    try:
        db.execute(
            "UPDATE check_item SET name = ?, description = ? WHERE id = ?", (name, desc or None, check_id)
        )
        _save_links(db, "tag_check", "check_id", check_id, "tag_id", request.form.getlist("tag_ids", type=int))
        db.commit()
        flash(f"Saved check “{name}”.", "ok")
    except sqlite3.IntegrityError:
        flash(f"A check named “{name}” already exists.", "error")
    return redirect(url_for(".config_checks", _anchor=f"check-{check_id}"))


@bp.post("/config/checks/<int:check_id>/delete")
def config_check_delete(check_id):
    db = get_db()
    db.execute("DELETE FROM check_item WHERE id = ?", (check_id,))
    db.commit()
    flash("Deleted check.", "ok")
    return redirect(url_for(".config_checks"))


@bp.route("/config/tags", methods=["GET", "POST"])
def config_tags():
    db = get_db()
    if request.method == "POST":
        name = clean(request.form.get("name"), 64).replace(",", "")
        desc = request.form.get("description", "").strip()[:1000]
        if not name:
            flash("Tag name is required.", "error")
        else:
            try:
                tid = db.execute(
                    "INSERT INTO tag (name, description, created_at) VALUES (?, ?, ?)",
                    (name, desc or None, now_iso()),
                ).lastrowid
                _save_links(db, "tag_check", "tag_id", tid, "check_id", request.form.getlist("check_ids", type=int))
                db.commit()
                flash(f"Added tag “{name}”.", "ok")
            except sqlite3.IntegrityError:
                flash(f"A tag named “{name}” already exists.", "error")
        return redirect(url_for(".config_tags"))

    tags = db.execute(
        """SELECT t.*, (SELECT COUNT(*) FROM node_tag nt WHERE nt.tag_id = t.id) AS node_count
           FROM tag t ORDER BY t.name COLLATE NOCASE"""
    ).fetchall()
    links = {}
    for r in db.execute(
        "SELECT tc.tag_id, c.id, c.name FROM tag_check tc JOIN check_item c ON c.id = tc.check_id "
        "ORDER BY c.name COLLATE NOCASE"
    ):
        links.setdefault(r["tag_id"], []).append(r)
    return render_template("config/tags.html", tags=tags, links=links, checks=all_checks(db))


@bp.post("/config/tags/<int:tag_id>")
def config_tag_update(tag_id):
    db = get_db()
    name = clean(request.form.get("name"), 64).replace(",", "")
    desc = request.form.get("description", "").strip()[:1000]
    if not name:
        flash("Tag name is required.", "error")
        return redirect(url_for(".config_tags"))
    try:
        db.execute("UPDATE tag SET name = ?, description = ? WHERE id = ?", (name, desc or None, tag_id))
        _save_links(db, "tag_check", "tag_id", tag_id, "check_id", request.form.getlist("check_ids", type=int))
        db.commit()
        flash(f"Saved tag “{name}”.", "ok")
    except sqlite3.IntegrityError:
        flash(f"A tag named “{name}” already exists.", "error")
    return redirect(url_for(".config_tags", _anchor=f"tag-{tag_id}"))


@bp.post("/config/tags/<int:tag_id>/delete")
def config_tag_delete(tag_id):
    db = get_db()
    db.execute("DELETE FROM tag WHERE id = ?", (tag_id,))
    db.commit()
    flash("Deleted tag.", "ok")
    return redirect(url_for(".config_tags"))


MATRICES = {
    # kind: (title, row source, row label, link table, row column, col column, hint)
    "tag-checks": {
        "title": "Tags → Checks",
        "rows": "SELECT id, name FROM check_item ORDER BY name COLLATE NOCASE",
        "row_label": "Check",
        "table": "tag_check", "row_col": "check_id", "col_col": "tag_id",
        "hint": "Tick a box to require that check on every node carrying the tag.",
        "empty": "Add some checks and tags first.",
    },
    "node-tags": {
        "title": "Nodes → Tags",
        "rows": "SELECT id, name FROM node ORDER BY name COLLATE NOCASE",
        "row_label": "Node",
        "table": "node_tag", "row_col": "node_id", "col_col": "tag_id",
        "hint": "Tick a box to apply the tag (and its checks) to the node.",
        "empty": "Add some nodes and tags first.",
    },
}


@bp.route("/config/<any('tag-checks', 'node-tags'):kind>", methods=["GET", "POST"])
def config_matrix(kind):
    m = MATRICES[kind]
    db = get_db()
    if request.method == "POST":
        p = request.get_json(silent=True) or {}
        try:
            row, col, on = int(p["row"]), int(p["col"]), bool(p["on"])
        except (KeyError, TypeError, ValueError):
            abort(400)
        if on:
            try:
                db.execute(
                    f"INSERT OR IGNORE INTO {m['table']} ({m['row_col']}, {m['col_col']}) VALUES (?, ?)",
                    (row, col),
                )
            except sqlite3.IntegrityError:
                abort(404)
        else:
            db.execute(
                f"DELETE FROM {m['table']} WHERE {m['row_col']} = ? AND {m['col_col']} = ?", (row, col)
            )
            if kind == "node-tags":  # a node's role must stay one of its tags
                db.execute("UPDATE node SET role_tag_id = NULL WHERE id = ? AND role_tag_id = ?", (row, col))
        db.commit()
        return jsonify(ok=True)

    links = {(r[0], r[1]) for r in db.execute(f"SELECT {m['row_col']}, {m['col_col']} FROM {m['table']}")}
    return render_template(
        "config/matrix.html", kind=kind, m=m,
        rows=db.execute(m["rows"]).fetchall(), cols=all_tags(db), links=links,
    )


# ---------------------------------------------------------------- history

@bp.get("/history")
def history():
    db = get_db()
    node_id = request.args.get("node", type=int)
    sql = "SELECT * FROM status_log"
    params = ()
    if node_id:
        sql += " WHERE node_id = ?"
        params = (node_id,)
    rows = db.execute(sql + " ORDER BY id DESC LIMIT 500", params).fetchall()
    nodes = db.execute("SELECT id, name FROM node ORDER BY name COLLATE NOCASE").fetchall()
    return render_template("history.html", rows=rows, nodes=nodes, node_id=node_id)


# ---------------------------------------------------------------- reports

def build_report():
    db = get_db()
    f = list_filters()
    include_history = request.args.get("history") == "1"
    items = node_items(db, **f)
    if include_history and items:
        ids = [i["node"]["id"] for i in items]
        by_node = {}
        for r in db.execute(
            f"SELECT * FROM status_log WHERE node_id IN ({','.join('?' * len(ids))}) ORDER BY id DESC", ids
        ):
            by_node.setdefault(r["node_id"], []).append(r)
        for i in items:
            i["history"] = by_node.get(i["node"]["id"], [])
    return {
        "items": items, "totals": totals(items), "filters": f,
        "include_history": include_history, "generated_at": now_iso(),
    }


@bp.get("/report")
def report():
    return render_template(
        "report.html", all_tags=all_tags(get_db()), status_filters=STATUS_FILTERS, **build_report()
    )


def _download_name(ext):
    return f"netinv-report-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.{ext}"


@bp.get("/report.csv")
def report_csv():
    rep = build_report()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["node", "ip", "fqdn", "url", "role", "tags", "notes", "check", "required_by", "status", "changed_at_utc"])
    for i in rep["items"]:
        n = i["node"]
        base = [n["name"], n["ip"], n["fqdn"] or "", n["url"] or "", n["role"] or "", "; ".join(t["name"] for t in i["tags"]), n["notes"] or ""]
        if not i["checks"]:
            w.writerow(base + ["", "", "", ""])
        for c in i["checks"]:
            w.writerow(base + [c["name"], "; ".join(c["via_tags"]), STATE_LABELS[c["state"]], c["changed_at"] or ""])
    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{_download_name("csv")}"'},
    )


@bp.get("/report.json")
def report_json():
    rep = build_report()
    nodes = []
    for i in rep["items"]:
        n = i["node"]
        entry = {
            "name": n["name"], "ip": n["ip"], "fqdn": n["fqdn"], "url": n["url"], "role": n["role"], "notes": n["notes"],
            "created_at": n["created_at"], "updated_at": n["updated_at"],
            "tags": [t["name"] for t in i["tags"]],
            "summary": i["summary"],
            "checks": [
                {"name": c["name"], "description": c["description"], "required_by": c["via_tags"],
                 "status": c["state"], "changed_at": c["changed_at"]}
                for c in i["checks"]
            ],
        }
        if rep["include_history"]:
            entry["history"] = [
                {"check": h["check_name"], "from": h["old_state"], "to": h["new_state"],
                 "changed_at": h["changed_at"], "client_ip": h["client_ip"]}
                for h in i["history"]
            ]
        nodes.append(entry)
    body = {"generated_at": rep["generated_at"], "filters": rep["filters"], "totals": rep["totals"], "nodes": nodes}
    return Response(
        json.dumps(body, indent=2), mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{_download_name("json")}"'},
    )


# ---------------------------------------------------------------- bulk delete

@bp.post("/config/<any('checks', 'tags'):kind>/bulk-delete")
def config_bulk_delete(kind):
    table = {"checks": "check_item", "tags": "tag"}[kind]
    ids = request.form.getlist("ids", type=int)
    if ids:
        db = get_db()
        db.execute(f"DELETE FROM {table} WHERE id IN ({','.join('?' * len(ids))})", ids)
        db.commit()
        flash(f"Deleted {len(ids)} {kind[:-1]}{'s' if len(ids) != 1 else ''}.", "ok")
    else:
        flash("Nothing selected.", "error")
    return redirect(url_for(f".config_{kind}"))


# ---------------------------------------------------------------- export / import / clear

EXPORT_FORMAT = "netinv-config"
EXPORT_VERSION = 1


class ConfigImportError(ValueError):
    pass


def clear_all(db):
    for table in ("status_log", "check_status", "node_tag", "tag_check", "node", "tag", "check_item"):
        db.execute(f"DELETE FROM {table}")


def export_config(db, include_history):
    tag_checks = {}
    for r in db.execute(
        "SELECT tc.tag_id, c.name FROM tag_check tc JOIN check_item c ON c.id = tc.check_id "
        "ORDER BY c.name COLLATE NOCASE"
    ):
        tag_checks.setdefault(r["tag_id"], []).append(r["name"])
    states = {}
    for r in db.execute(
        "SELECT s.node_id, c.name, s.state, s.changed_at FROM check_status s "
        "JOIN check_item c ON c.id = s.check_id ORDER BY c.name COLLATE NOCASE"
    ):
        states.setdefault(r["node_id"], []).append(
            {"check": r["name"], "state": r["state"], "changed_at": r["changed_at"]}
        )
    tags = tags_by_node(db)
    out = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": now_iso(),
        "admin_info": get_setting(db, "admin_info"),
        "checks": [
            {"name": r["name"], "description": r["description"]}
            for r in db.execute("SELECT * FROM check_item ORDER BY name COLLATE NOCASE")
        ],
        "tags": [
            {"name": r["name"], "description": r["description"], "checks": tag_checks.get(r["id"], [])}
            for r in db.execute("SELECT * FROM tag ORDER BY name COLLATE NOCASE")
        ],
        "nodes": [
            {
                "name": r["name"], "ip": r["ip"], "fqdn": r["fqdn"], "url": r["url"], "notes": r["notes"],
                "created_at": r["created_at"], "updated_at": r["updated_at"],
                "role": r["role"],
                "tags": [t["name"] for t in tags.get(r["id"], [])],
                "states": states.get(r["id"], []),
            }
            for r in db.execute(NODE_SQL + " ORDER BY n.name COLLATE NOCASE")
        ],
    }
    if include_history:
        out["history"] = [
            {"node": r["node_name"], "check": r["check_name"], "from": r["old_state"],
             "to": r["new_state"], "changed_at": r["changed_at"], "client_ip": r["client_ip"]}
            for r in db.execute("SELECT * FROM status_log ORDER BY id")
        ]
    return out


def _items(data, key):
    value = data.get(key) or []
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise ConfigImportError(f"“{key}” must be a list of objects.")
    return value


def _text(value, what, required=False, limit=1000):
    if value is None or value == "":
        if required:
            raise ConfigImportError(f"Missing {what}.")
        return None
    if not isinstance(value, str):
        raise ConfigImportError(f"{what} must be text.")
    return value.strip()[:limit] or None


def _names(value, what):
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigImportError(f"{what} must be a list of names.")
    return [clean(v, 120) for v in value if clean(v, 120)]


def _upsert(db, table, name, fields):
    row = db.execute(f"SELECT id FROM {table} WHERE name = ?", (name,)).fetchone()
    if row:
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            db.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*fields.values(), row["id"]))
        return row["id"]
    cols = ["name", *fields]
    if "created_at" not in fields:
        cols.append("created_at")
        fields = {**fields, "created_at": now_iso()}
    return db.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        (name, *fields.values()),
    ).lastrowid


def _check_id(db, name, context):
    row = db.execute("SELECT id FROM check_item WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise ConfigImportError(f"{context} refers to unknown check “{name}”.")
    return row["id"]


def import_config(db, data, mode):
    """Load an export. 'merge' upserts by name; 'replace' clears everything first."""
    if not isinstance(data, dict) or data.get("format") != EXPORT_FORMAT:
        raise ConfigImportError("This file is not a NetInv configuration export.")
    if mode == "replace":
        clear_all(db)
    counts = dict(checks=0, tags=0, nodes=0, states=0, history=0)

    if data.get("admin_info") is not None:
        if not isinstance(data["admin_info"], str):
            raise ConfigImportError("Admin info must be text.")
        text, error = clean_admin_info(data["admin_info"])
        if error:
            raise ConfigImportError(f"Admin info: {error}")
        set_setting(db, "admin_info", text)

    for c in _items(data, "checks"):
        name = clean(_text(c.get("name"), "check name", True), 120)
        _upsert(db, "check_item", name, {"description": _text(c.get("description"), f"description of check “{name}”")})
        counts["checks"] += 1

    for t in _items(data, "tags"):
        name = clean(_text(t.get("name"), "tag name", True), 64).replace(",", "")
        tid = _upsert(db, "tag", name, {"description": _text(t.get("description"), f"description of tag “{name}”")})
        ids = [_check_id(db, c, f"Tag “{name}”") for c in _names(t.get("checks"), f"Checks of tag “{name}”")]
        _save_links(db, "tag_check", "tag_id", tid, "check_id", ids)
        counts["tags"] += 1

    for n in _items(data, "nodes"):
        name = clean(_text(n.get("name"), "node name", True), 100)
        ip = _text(n.get("ip"), f"IP of node “{name}”", True)
        try:
            ip = str(ipaddress.ip_address(ip))
        except ValueError:
            raise ConfigImportError(f"Node “{name}” has an invalid IP address “{ip}”.") from None
        fqdn = (_text(n.get("fqdn"), f"FQDN of node “{name}”") or "").rstrip(".").lower() or None
        if fqdn and not FQDN_RE.match(fqdn):
            raise ConfigImportError(f"Node “{name}” has an invalid FQDN “{fqdn}”.")
        ts = now_iso()
        url = _text(n.get("url"), f"URL of node “{name}”", limit=2000)
        if url and not valid_url(url):
            raise ConfigImportError(f"Node “{name}” has an invalid URL “{url}”.")
        fields = {
            "ip": ip, "fqdn": fqdn, "url": url, "notes": _text(n.get("notes"), f"notes of node “{name}”", limit=4000),
            "updated_at": _text(n.get("updated_at"), "updated_at") or ts,
        }
        exists = db.execute("SELECT 1 FROM node WHERE name = ?", (name,)).fetchone()
        if not exists:
            fields["created_at"] = _text(n.get("created_at"), "created_at") or ts
        nid = _upsert(db, "node", name, fields)
        set_node_tags(db, nid, [clean(t, 64).replace(",", "") for t in _names(n.get("tags"), f"Tags of node “{name}”")])
        set_node_role(db, nid, clean(_text(n.get("role"), f"role of node “{name}”") or "", 64))
        for s in n.get("states") or []:
            if not isinstance(s, dict) or s.get("state") not in STATES:
                raise ConfigImportError(f"Node “{name}” has an invalid check state entry.")
            cid = _check_id(db, clean(_text(s.get("check"), "check name", True), 120), f"Node “{name}”")
            db.execute(
                "INSERT INTO check_status (node_id, check_id, state, changed_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (node_id, check_id) DO UPDATE SET state = excluded.state, changed_at = excluded.changed_at",
                (nid, cid, s["state"], _text(s.get("changed_at"), "changed_at") or ts),
            )
            counts["states"] += 1
        counts["nodes"] += 1

    for h in _items(data, "history"):
        node = _text(h.get("node"), "history node", True)
        check = _text(h.get("check"), "history check", True)
        old, new, when = h.get("from"), h.get("to"), _text(h.get("changed_at"), "history changed_at", True)
        if old not in STATES or new not in STATES:
            raise ConfigImportError("History contains an invalid state.")
        if db.execute(
            "SELECT 1 FROM status_log WHERE node_name = ? AND check_name = ? AND new_state = ? AND changed_at = ?",
            (node, check, new, when),
        ).fetchone():
            continue
        nrow = db.execute("SELECT id FROM node WHERE name = ?", (node,)).fetchone()
        crow = db.execute("SELECT id FROM check_item WHERE name = ?", (check,)).fetchone()
        db.execute(
            "INSERT INTO status_log (node_id, check_id, node_name, check_name, old_state, new_state, changed_at, client_ip) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (nrow and nrow["id"], crow and crow["id"], node, check, old, new, when, _text(h.get("client_ip"), "client_ip")),
        )
        counts["history"] += 1
    return counts


def data_stats(db):
    return {
        k: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for k, t in (("nodes", "node"), ("checks", "check_item"), ("tags", "tag"), ("history", "status_log"))
    }


@bp.get("/config/data")
def config_data():
    hosts, host_count = hosts_file(get_db())
    return render_template("config/data.html", stats=data_stats(get_db()), hosts=hosts, host_count=host_count)


@bp.get("/config/export.json")
def config_export():
    body = export_config(get_db(), request.args.get("history") == "1")
    name = f"netinv-config-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.json"
    return Response(
        json.dumps(body, indent=2), mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@bp.post("/config/import")
def config_import():
    db = get_db()
    upload = request.files.get("file")
    mode = request.form.get("mode")
    if mode not in ("merge", "replace"):
        abort(400)
    if not upload or not upload.filename:
        flash("Choose an export file to import.", "error")
        return redirect(url_for(".config_data"))
    try:
        data = json.load(upload.stream)
    except (ValueError, UnicodeDecodeError):
        flash("That file isn't valid JSON.", "error")
        return redirect(url_for(".config_data"))
    try:
        counts = import_config(db, data, mode)
        db.commit()
    except ConfigImportError as e:
        db.rollback()
        flash(f"Import failed, nothing was changed: {e}", "error")
        return redirect(url_for(".config_data"))
    flash(
        f"Imported ({'replaced all data' if mode == 'replace' else 'merged'}): {counts['nodes']} nodes, "
        f"{counts['checks']} checks, {counts['tags']} tags, {counts['states']} check states, "
        f"{counts['history']} history entries.",
        "ok",
    )
    return redirect(url_for(".config_data"))


@bp.route("/config/clear", methods=["GET", "POST"])
def config_clear():
    db = get_db()
    if request.method == "POST":
        if request.form.get("confirm") != "DELETE":
            flash("Type DELETE to confirm clearing all data.", "error")
        else:
            clear_all(db)
            db.commit()
            flash("All data cleared.", "ok")
        return redirect(url_for(".config_clear"))
    return render_template("config/clear.html", stats=data_stats(db))


# ---------------------------------------------------------------- hosts file

def _host_alias(name):
    """Friendly name as a hosts-file alias: no whitespace or odd characters."""
    return re.sub(r"[^A-Za-z0-9._-]", "", re.sub(r"\s+", "-", name.strip())).strip(".-")


def hosts_file(db):
    from . import __version__

    rows = db.execute("SELECT name, ip, fqdn FROM node").fetchall()
    rows = sorted(rows, key=lambda r: (ipaddress.ip_address(r["ip"]).version, ipaddress.ip_address(r["ip"])))
    lines = [
        f"# Generated by NetInv v{__version__} at {now_iso()}",
        "# Format: IP  FQDN  friendly-name. The FQDN comes first so reverse lookups return it.",
        "# Contains only NetInv nodes: append it to /etc/hosts rather than replacing that file.",
        "",
    ]
    entries = []
    for r in rows:
        names = [n for n in (r["fqdn"], _host_alias(r["name"])) if n]
        names = [n for i, n in enumerate(names) if n.lower() not in (m.lower() for m in names[:i])]
        if names:
            entries.append((r["ip"], names))
    width = max([len(ip) for ip, _ in entries] or [0])
    lines += [f"{ip.ljust(width)}  {' '.join(names)}" for ip, names in entries]
    return "\n".join(lines) + "\n", len(entries)


@bp.get("/config/hosts.txt")
def config_hosts():
    body, _ = hosts_file(get_db())
    headers = {"Content-Disposition": 'attachment; filename="netinv-hosts"'} if request.args.get("download") else {}
    return Response(body, mimetype="text/plain; charset=utf-8", headers=headers)


# ---------------------------------------------------------------- admin info

ADMIN_INFO_LINES = 2
ADMIN_INFO_LINE_LIMIT = 200


def get_setting(db, key, default=None):
    row = db.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(db, key, value):
    if value:
        db.execute(
            "INSERT INTO setting (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    else:
        db.execute("DELETE FROM setting WHERE key = ?", (key,))


def clean_admin_info(raw):
    """Normalise admin info to at most two non-blank lines; returns (text, error)."""
    lines = [line.strip() for line in (raw or "").splitlines() if line.strip()]
    if len(lines) > ADMIN_INFO_LINES:
        return None, f"Use at most {ADMIN_INFO_LINES} lines."
    if any(len(line) > ADMIN_INFO_LINE_LIMIT for line in lines):
        return None, f"Keep each line under {ADMIN_INFO_LINE_LIMIT} characters."
    return "\n".join(lines), None


def admin_info_html():
    """Rendered admin info lines for the header (empty list when not set)."""
    return markdown.render_lines(get_setting(get_db(), "admin_info", ""))


@bp.route("/config/admin", methods=["GET", "POST"])
def config_admin():
    db = get_db()
    text = get_setting(db, "admin_info", "")
    error = None
    if request.method == "POST":
        text, error = clean_admin_info(request.form.get("admin_info"))
        if error:
            text = request.form.get("admin_info", "")
        else:
            set_setting(db, "admin_info", text)
            db.commit()
            flash("Admin info saved." if text else "Admin info cleared.", "ok")
            return redirect(url_for(".config_admin"))
    return render_template("config/admin.html", text=text, error=error, preview=markdown.render_lines(text))


@bp.post("/config/admin/preview")
def config_admin_preview():
    """Render unsaved admin info with the same code the header uses."""
    raw = (request.get_json(silent=True) or {}).get("text", "")
    if not isinstance(raw, str):
        abort(400)
    _, error = clean_admin_info(raw)
    lines = markdown.render_lines(raw[:2000])
    html = render_template("config/_admin_preview.html", preview=lines)
    return jsonify(html=html, error=error)


# ---------------------------------------------------------------- about

@bp.get("/about")
def about():
    from flask import current_app

    from . import about as info

    return render_template(
        "about.html",
        environment=info.environment(current_app),
        deps=info.dependencies(),
    )


@bp.get("/about/license")
def about_license():
    from .about import PROJECT_ROOT

    with open(f"{PROJECT_ROOT}/LICENSE", encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/plain; charset=utf-8")


@bp.get("/about/source.tar.gz")
def about_source():
    from . import __version__
    from .about import source_tarball

    return Response(
        source_tarball(__version__), mimetype="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="netinv-{__version__}-source.tar.gz"'},
    )
