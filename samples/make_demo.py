# SPDX-License-Identifier: AGPL-3.0-or-later
# NetInv — Copyright (C) 2026 Bill Farmer, Jr. See LICENSE.
"""Regenerate samples/netinv-demo.json, a fictional network for trying NetInv.

    python3 samples/make_demo.py

Uses only documentation addresses (RFC 5737, RFC 3849) and example.net names.
Seeded, so the output is the same every run.
"""
import json
import os
import random
from datetime import datetime, timedelta, timezone

rng = random.Random(1337)
START = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
END = datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)
ADMINS = ["198.51.100.10", "198.51.100.11", "2001:db8:100::25"]

CHECKS = {
    "SSH key-only login": "PasswordAuthentication no; root cannot log in with a password.",
    "Automatic security updates": "unattended-upgrades or equivalent enabled for security fixes.",
    "Time synced (NTP)": "Clock synced to the internal NTP servers.",
    "Logs forwarded to SIEM": "System and auth logs are shipped to the central log host.",
    "Monitoring agent installed": "Node appears in monitoring with CPU, disk and service checks.",
    "Backups scheduled": "Nightly backup job exists and last run succeeded.",
    "Restore tested": "A restore was tested within the last 6 months.",
    "Default credentials changed": "No vendor default accounts or passwords remain.",
    "Firmware current": "Running the vendor's current recommended firmware.",
    "Config backed up": "Running config is exported to the config archive.",
    "Management on OOB VLAN": "Management interface only reachable from the out-of-band network.",
    "Default-deny policy": "Inbound and inter-zone rules end in an explicit deny.",
    "TLS certificate valid": "Public certificate valid for 30+ days and auto-renewing.",
    "HSTS enabled": "Strict-Transport-Security header sent on all HTTPS responses.",
    "DB client TLS required": "Database refuses unencrypted client connections.",
    "Least-privilege DB accounts": "Applications use per-app accounts without superuser rights.",
    "Disk encryption": "Data volumes encrypted at rest.",
    "Isolated IoT VLAN": "Device sits on the IoT VLAN with no route to internal networks.",
    "HA cluster quorum": "Node is a healthy member of the cluster with quorum.",
    "UPS-protected power": "Device is on a monitored UPS circuit.",
}

TAGS = {
    "linux": ("Linux servers and VMs.", ["SSH key-only login", "Automatic security updates", "Time synced (NTP)",
                                          "Logs forwarded to SIEM", "Monitoring agent installed"]),
    "network": ("Switches, routers and access points.", ["Default credentials changed", "Firmware current",
                                                         "Config backed up", "Management on OOB VLAN", "Time synced (NTP)"]),
    "firewall": ("Perimeter and internal firewalls.", ["Default-deny policy", "Config backed up",
                                                        "Logs forwarded to SIEM", "Firmware current"]),
    "hypervisor": ("Virtualization hosts.", ["HA cluster quorum", "UPS-protected power", "Management on OOB VLAN"]),
    "web": ("Public or internal web servers.", ["TLS certificate valid", "HSTS enabled"]),
    "database": ("Database servers.", ["DB client TLS required", "Least-privilege DB accounts", "Disk encryption"]),
    "backup": ("Holds data that must be backed up.", ["Backups scheduled", "Restore tested"]),
    "storage": ("NAS and backup targets.", ["Disk encryption", "UPS-protected power", "Monitoring agent installed"]),
    "iot": ("Cameras, sensors and other embedded devices.", ["Default credentials changed", "Firmware current",
                                                             "Isolated IoT VLAN"]),
    "dmz": ("Reachable from the internet.", ["Default-deny policy", "Logs forwarded to SIEM"]),
    "lab": ("Test systems; no checks of their own.", []),
}

# name, ip, fqdn, url, role, tags, notes, completeness (share of checks done)
NODES = [
    ("edge-fw-01", "192.0.2.1", "edge-fw-01.example.net", "https://edge-fw-01.example.net/", "firewall",
     ["firewall", "network", "dmz"], "Primary perimeter firewall. HA pair with edge-fw-02.", 1.0),
    ("edge-fw-02", "192.0.2.2", "edge-fw-02.example.net", "https://edge-fw-02.example.net/", "firewall",
     ["firewall", "network", "dmz"], "Standby member of the HA pair.", 0.75),
    ("core-sw-01", "192.0.2.10", "core-sw-01.example.net", None, "network",
     ["network"], "48-port core switch, rack A.", 1.0),
    ("access-sw-02", "192.0.2.11", "access-sw-02.example.net", None, "network",
     ["network"], "Office floor 2.", 0.4),
    ("wifi-ap-lobby", "192.0.2.20", "wifi-ap-lobby.example.net", "https://wifi-ap-lobby.example.net/", "network",
     ["network", "iot"], "", 0.2),
    ("pve-01", "198.51.100.21", "pve-01.example.net", "https://pve-01.example.net:8006/", "hypervisor",
     ["hypervisor", "linux"], "Cluster node 1 of 3.", 1.0),
    ("pve-02", "198.51.100.22", "pve-02.example.net", "https://pve-02.example.net:8006/", "hypervisor",
     ["hypervisor", "linux"], "Cluster node 2 of 3.", 0.85),
    ("pve-03", "2001:db8:10::23", "pve-03.example.net", "https://pve-03.example.net:8006/", "hypervisor",
     ["hypervisor", "linux"], "Cluster node 3 of 3. IPv6-only management.", 0.5),
    ("www-01", "203.0.113.80", "www.example.net", "https://www.example.net/", "web",
     ["web", "linux", "dmz", "backup"], "Public website.", 0.9),
    ("app-02", "2001:db8:20::80", "app-02.example.net", "https://app-02.example.net/", "web",
     ["web", "linux", "backup"], "Internal ticketing app.", 0.55),
    ("db-01", "198.51.100.50", "db-01.example.net", None, "database",
     ["database", "linux", "backup"], "PostgreSQL primary.", 0.8),
    ("db-02", "198.51.100.51", "db-02.example.net", None, "database",
     ["database", "linux", "backup"], "PostgreSQL replica.", 0.3),
    ("nas-01", "198.51.100.60", "nas-01.example.net", "https://nas-01.example.net:5001/", "storage",
     ["storage", "backup", "network"], "Backup target for all VMs.", 0.7),
    ("cam-front-door", "192.0.2.150", "cam-front-door.example.net", None, "iot",
     ["iot"], "PoE camera.", 0.0),
    ("env-sensor-rack", "192.0.2.151", "env-sensor-rack.example.net", None, "iot",
     ["iot", "network"], "Temperature and humidity in the server rack.", 0.34),
    ("lab-box", "2001:db8:99::5", "lab-box.example.net", None, None,
     ["lab", "linux"], "Scratch VM, rebuilt often. No role set on purpose.", 0.0),
    ("printer-3f", "192.0.2.200", "printer-3f.example.net", "http://printer-3f.example.net/", None,
     [], "Not tagged yet, so no checks apply.", 0.0),
]

# Checks that don't make sense for a node are marked N/A.
NA = {
    ("wifi-ap-lobby", "Isolated IoT VLAN"),  # guest AP lives on the guest VLAN instead
    ("pve-03", "UPS-protected power"),
    ("app-02", "HSTS enabled"),
    ("env-sensor-rack", "Config backed up"),
    ("env-sensor-rack", "Management on OOB VLAN"),
    ("db-02", "Restore tested"),
}


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def when(lo, hi):
    return lo + timedelta(seconds=rng.randint(0, int((hi - lo).total_seconds())))


def main():
    checks_of = {t: set(cs) for t, (_, cs) in TAGS.items()}
    nodes, history = [], []
    for name, ip, fqdn, url, role, tags, notes, done in NODES:
        applicable = sorted({c for t in tags for c in checks_of[t]}, key=str.lower)
        created = when(START, START + timedelta(days=10))
        rng.shuffle(applicable)
        n_done = round(done * len(applicable))
        states, last = [], created
        for i, check in enumerate(applicable):
            final = "na" if (name, check) in NA else ("compliant" if i < n_done else "pending")
            events = []
            t = when(created + timedelta(days=1), END - timedelta(days=2))
            if final == "compliant" and rng.random() < 0.25:
                # Was fixed, regressed, then fixed again: shows up in history.
                t2 = when(t, END - timedelta(days=1))
                t3 = when(t2, END)
                events = [("pending", "compliant", t), ("compliant", "pending", t2), ("pending", "compliant", t3)]
            elif final == "compliant":
                events = [("pending", "compliant", t)]
            elif final == "na":
                events = [("pending", "na", t)]
            elif rng.random() < 0.3:
                # Marked compliant once, later found broken again.
                t2 = when(t, END)
                events = [("pending", "compliant", t), ("compliant", "pending", t2)]
            for old, new, at in events:
                history.append({"node": name, "check": check, "from": old, "to": new,
                                "changed_at": iso(at), "client_ip": rng.choice(ADMINS)})
            if events:
                states.append({"check": check, "state": final, "changed_at": iso(events[-1][2])})
                last = max(last, events[-1][2])
        nodes.append({
            "name": name, "ip": ip, "fqdn": fqdn, "url": url, "notes": notes or None,
            "created_at": iso(created), "updated_at": iso(last), "role": role, "tags": sorted(tags, key=str.lower),
            "states": sorted(states, key=lambda s: s["check"].lower()),
        })
    history.sort(key=lambda h: h["changed_at"])
    data = {
        "format": "netinv-config",
        "version": 1,
        "exported_at": iso(END),
        "admin_info": "**Demo Network Team** · netops@example.net\n"
                      "[Runbook](https://wiki.example.net/netops) · on-call `x4242`",
        "checks": [{"name": n, "description": d} for n, d in sorted(CHECKS.items(), key=lambda kv: kv[0].lower())],
        "tags": [{"name": t, "description": d, "checks": sorted(cs, key=str.lower)}
                 for t, (d, cs) in sorted(TAGS.items())],
        "nodes": sorted(nodes, key=lambda n: n["name"].lower()),
        "history": history,
    }
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "netinv-demo.json")
    with open(out, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"wrote {out}: {len(nodes)} nodes, {len(CHECKS)} checks, {len(TAGS)} tags, {len(history)} history entries")


if __name__ == "__main__":
    main()
