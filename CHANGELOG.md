# Changelog

The version lives in `netinv/__init__.py` (`__version__`) and is shown in the
page footer. Bump it with every change: patch for fixes, minor for features.

## 1.4.0 — 2026-10-30

- Listen address split into `NETINV_HOST` and `NETINV_PORT` (IPv6 hosts are
  bracketed automatically). `NETINV_BIND` still works and overrides both.
- `netinv.conf` is no longer tracked; copy `netinv.conf.example` instead.
- Demo data in `samples/netinv-demo.json` (and its generator) that can be
  loaded with Import.
- README rewritten with installation, configuration, proxy, firewall,
  backup and upgrade instructions, and a clear note that NetInv has no
  access control of its own.
- The About page states that NetInv is for internal use behind a proxy.
- The example systemd unit now uses a dedicated `netinv` user in `/opt/netinv`.

## 1.3.1 — 2026-10-30

- Admin info preview updates as you type, before saving, and flags input
  that's too long (more than two lines or 200 characters per line). The
  server renders it, so the preview matches the header exactly.

## 1.3.0 — 2026-10-30

- **Summary** page (between Nodes and Configuration): overall compliance at
  the top, then one chart per role, with four chart styles to switch between
  (rings, stacked bars, side-by-side bars, text). The browser remembers the
  last style.
- **Hosts file**: Configuration → Import / Export builds an `/etc/hosts`
  fragment (`IP  FQDN  friendly-name`, FQDN first for reverse lookups), with
  view, download, and a copyable `curl` one-liner. Served at `/config/hosts.txt`.
- **Admin info**: a new Configuration tab for up to two lines of inline
  Markdown (bold, italic, code, links, e-mail), shown in the page header.
  Included in configuration export/import; Clear data keeps it.
- Tag input no longer offers tags the node already has.
- IP field hint shows IPv4 and IPv6 examples (both were already accepted
  and validated).
- Footer is centered.
- New `setting` table, created automatically on startup.

## 1.2.0 — 2026-10-30

- Licensed under the GNU AGPL v3.0 or later (`LICENSE`, SPDX headers).
- New logo and favicon: a chunked compliance ring around a node.
- Optional node **URL** (http/https only). Nodes with one get an
  open-in-new-tab icon in the node list and on the node page; URL is
  included in reports and configuration export/import.
- **About** page in the main navigation: version, running environment,
  every dependency with minimum and installed versions, license, source
  download (AGPL section 13), and a note that Claude Code was used.
- Clear data moved to its own Configuration tab.
- `requirements.txt` now lists minimum versions; `requirements.lock` pins
  the tested set.
- Database migration adds `node.url` to existing databases on startup.
- Fix: gunicorn workers no longer race to migrate the database at startup
  (a worker could fail with "duplicate column" and stop the server until
  systemd restarted it). Schema setup now runs under a SQLite write lock.

## 1.1.0 — 2026-10-30

- Node **role**: choose one of a node's tags as its primary tag. The node list
  shows the role instead of tags, filtering still works on any tag, and role is
  included in reports and configuration export/import.
- Light/dark theme follows the system, with a toggle in the top bar.
- Page footer with version, page load time, render time and gunicorn worker summary.
- Static assets are versioned so browsers pick up changes after an upgrade.
- Database migration adds `node.role_tag_id` to existing databases on startup.

## 1.0.0 — 2026-10-30

- Initial release: nodes with freeform tags, checks per tag with
  Pending/Compliant/N/A states and audit history, configuration pane
  (checks, tags, matrices, bulk delete, JSON import/export, clear all),
  HTML/CSV/JSON reports, gunicorn behind a reverse proxy, systemd unit.
