# NetInv

A small, self-hosted web app for keeping an inventory of network nodes and
manually tracking whether each one meets the checks you care about.

> [!IMPORTANT]
> **NetInv is built for internal use behind a reverse proxy.** It has **no
> authentication, no user accounts and no access control**: anyone who can
> reach it can view, change, export and delete everything. Authentication,
> TLS, IP allow-lists and any other access control must be handled by the
> upstream proxy (and a firewall in front of NetInv's port). Never expose
> NetInv's port directly to an untrusted network.

## Features

- **Nodes**: friendly name, IPv4 or IPv6 address, FQDN, optional URL (with an
  open-in-new-tab link), notes, freeform tags, and a role (the node's primary tag).
- **Checks**: requirements attached to tags. A node must meet every check of
  every tag it has.
- **States**: each check on a node is *Pending*, *Compliant* or *N/A*, set with
  one click or tap. Every change is timestamped and written to an audit log.
- **Summary**: overall and per-role compliance as rings, stacked bars,
  side-by-side bars or text.
- **Reports**: printable HTML, CSV and JSON, filtered by search, tag or status.
- **Hosts file**: every node as `IP  FQDN  friendly-name`, ready to append to `/etc/hosts`.
- **Configuration**: link checks to tags and tags to nodes in a grid, bulk
  delete, export/import everything (optionally with history), clear all data,
  and a two-line Markdown "admin info" shown in the page header.
- Light and dark themes that follow the system, with a toggle.

## Requirements

- Linux (developed on Debian 13; any recent distribution should work)
- Python 3.11 or newer, with `venv`
- SQLite 3.24 or newer (bundled with Python's `sqlite3` module)
- A reverse proxy for anything beyond a quick local trial (nginx, HAProxy, Caddy, …)

Python dependencies are Flask and gunicorn. `requirements.txt` lists minimum
versions and `requirements.lock` pins the versions NetInv was tested with.

## Quick start (local trial)

```sh
git clone https://github.com/bfarmerjr/netinv.git
cd netinv
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
./run.sh
```

Open <http://127.0.0.1:8000>. To look around with realistic data, load the
[demo data](#demo-data).

## Installation (production)

These steps install NetInv to `/opt/netinv`, running as its own unprivileged
user under systemd, listening on localhost for a reverse proxy on the same host.

1. Install the prerequisites and create a service user:

   ```sh
   sudo apt install python3-venv git
   sudo useradd --system --home-dir /opt/netinv --shell /usr/sbin/nologin netinv
   ```

2. Get the code and install the dependencies:

   ```sh
   sudo git clone https://github.com/bfarmerjr/netinv.git /opt/netinv
   sudo chown -R netinv:netinv /opt/netinv
   cd /opt/netinv
   sudo -u netinv python3 -m venv .venv
   sudo -u netinv .venv/bin/pip install -r requirements.lock
   ```

3. Configure. Copy the example and set the listen address (see
   [Configuration](#configuration)):

   ```sh
   sudo -u netinv cp netinv.conf.example netinv.conf
   sudoedit -u netinv netinv.conf
   ```

4. Install and start the systemd service. `deploy/netinv.service` assumes
   `/opt/netinv` and the `netinv` user; edit it first if yours differ.

   ```sh
   sudo cp deploy/netinv.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now netinv
   systemctl status netinv
   ```

5. Put it behind your [reverse proxy](#reverse-proxy) and add authentication there.

6. If the proxy runs on a different host, NetInv must listen on an address
   the proxy can reach. [Firewall that port](#firewall) so only the proxy can
   connect to it.

The database (`instance/netinv.db`) and a generated session secret
(`instance/secret_key`) are created on first start.

## Configuration

`run.sh` reads `netinv.conf` (shell `KEY=value` syntax) from its own
directory. Environment variables override values in the file.

| Variable            | Default          | Meaning |
|---------------------|------------------|---------|
| `NETINV_HOST`       | `127.0.0.1`      | IP address to listen on. IPv6 works (`::1`, or `::` for all). |
| `NETINV_PORT`       | `8000`           | TCP port to listen on. |
| `NETINV_BIND`       | *(unset)*        | Full gunicorn bind string, e.g. `unix:/run/netinv/netinv.sock`. Overrides `NETINV_HOST` and `NETINV_PORT`. |
| `NETINV_PROXY_HOPS` | `1`              | Number of proxies in front whose `X-Forwarded-For/Proto/Host/Prefix` headers are trusted. Use `0` if nothing is in front, or clients could fake their address. |
| `NETINV_WORKERS`    | `2`              | gunicorn worker processes. |
| `NETINV_THREADS`    | `8`              | Threads per worker. |
| `NETINV_DATA_DIR`   | `./instance`     | Where the database and session secret are kept. |

Restart after changing settings: `sudo systemctl restart netinv`.

## Reverse proxy

The proxy is where access control belongs: authentication (basic auth, SSO,
client certificates…), TLS and IP allow-lists. NetInv only records the client
address it gets from `X-Forwarded-For` in its audit log.

### nginx

At the root of a host:

```nginx
location / {
    # Add authentication here, e.g. auth_basic / auth_request.
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Under a sub-path, for example `/netinv/`:

```nginx
location /netinv/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Prefix /netinv;
}
```

### HAProxy

```haproxy
backend netinv
    option forwardfor
    http-request set-header X-Forwarded-Proto https if { ssl_fc }
    server netinv1 192.0.2.10:8000 check
```

### Firewall

When NetInv listens on a non-loopback address, allow only the proxy to reach
it. For example with nftables, in the `input` chain (proxy at 192.0.2.5):

```nft
tcp dport 8000 iifname "lo" accept
tcp dport 8000 ip saddr 192.0.2.5 accept
tcp dport 8000 drop
```

## Demo data

[`samples/netinv-demo.json`](samples/netinv-demo.json) is a fictional network
of 17 nodes, using only documentation addresses and `example.net` names. It
includes:
- IPv4 and IPv6 addresses
- 20 checks across 11 tags
- roles, URLs and notes
- compliant, pending and N/A states
- nodes with no checks
- an admin info header
- 136 history entries, including regressions

To load it, go to **Configuration → Import / Export → Import**, choose the
file, and pick a mode:
- **Replace everything** shows exactly the demo. It **deletes all current
  data** first, so export a backup if you have real data.
- **Merge** adds the demo to what's already there.

`python3 samples/make_demo.py` regenerates the file.

## Hosts file

**Configuration → Import / Export → Hosts file** shows the generated file,
with a download button and a copyable command. From another machine:

```sh
curl -fsSL https://netinv.example.net/config/hosts.txt -o netinv-hosts
```

The file contains only NetInv's nodes. Append it to `/etc/hosts` (or merge it
in your configuration management) rather than replacing that file. If the
proxy requires authentication, pass credentials to `curl` (e.g. `-u user`).

## Backups and upgrades

All data lives in `instance/netinv.db` (SQLite, WAL mode). To back it up,
either use **Export** with history included, or copy the database safely
while NetInv runs:

```sh
sqlite3 /opt/netinv/instance/netinv.db ".backup '/var/backups/netinv.db'"
```

To upgrade, back up first, then:

```sh
cd /opt/netinv
sudo -u netinv git pull
sudo -u netinv .venv/bin/pip install -r requirements.lock
sudo systemctl restart netinv
```

Database schema changes are applied automatically at startup. See
[CHANGELOG.md](CHANGELOG.md) for what changed in each version.

## License

Copyright (C) 2026 Bill Farmer, Jr.

NetInv is free software, licensed under the GNU Affero General Public License
v3.0 or later. See [LICENSE](LICENSE). Because the AGPL covers use over a
network, the running app's About page links to the full license text and
offers its source code for download.

NetInv was developed with the help of [Claude Code](https://claude.com/claude-code).
