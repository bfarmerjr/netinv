# SPDX-License-Identifier: AGPL-3.0-or-later
# NetInv — Copyright (C) 2026 Bill Farmer, Jr. See LICENSE.
import os
import secrets

from flask import Flask
from markupsafe import Markup
from werkzeug.middleware.proxy_fix import ProxyFix

from . import db, runtime

# Bump on every change: MAJOR.MINOR.PATCH (see CHANGELOG.md).
__version__ = "1.4.0"


def _secret_key(instance_path):
    path = os.path.join(instance_path, "secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
        os.chmod(path, 0o600)
    with open(path) as f:
        return f.read().strip()


def create_app():
    data_dir = os.environ.get("NETINV_DATA_DIR")
    app = Flask(__name__, instance_path=os.path.abspath(data_dir) if data_dir else None)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config["DATABASE"] = os.path.join(app.instance_path, "netinv.db")
    app.config["SECRET_KEY"] = _secret_key(app.instance_path)

    # Trust X-Forwarded-For/Proto/Host/Prefix from this many proxies in front.
    hops = int(os.environ.get("NETINV_PROXY_HOPS", "1"))
    if hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops, x_prefix=hops)

    db.init_app(app)

    from .views import STATE_LABELS, STATES, admin_info_html, bp, donut, now_iso

    app.register_blueprint(bp)
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # config imports
    app.before_request(runtime.start_request)

    @app.template_filter("ts")
    def ts_filter(value, seconds=False):
        """Render a UTC ISO timestamp; app.js rewrites it to local time."""
        if not value:
            return Markup('<span class="muted">—</span>')
        shown = value[:19 if seconds else 16].replace("T", " ") + " UTC"
        return Markup('<time class="ts{2}" datetime="{0}">{1}</time>').format(value, shown, " secs" if seconds else "")

    app.jinja_env.globals.update(
        STATES=STATES, STATE_LABELS=STATE_LABELS, donut=donut, version=__version__, now_iso=now_iso,
        render_ms=runtime.render_ms, worker_summary=runtime.worker_summary, admin_info=admin_info_html,
    )

    return app
