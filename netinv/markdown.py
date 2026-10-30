# SPDX-License-Identifier: AGPL-3.0-or-later
# NetInv — Copyright (C) 2026 Bill Farmer, Jr. See LICENSE.
"""A tiny, safe subset of inline Markdown for short admin-entered text.

Supports **bold**, *italic*, `code`, [text](url), <url>, and bare URLs and
e-mail addresses. Everything else is escaped. Links are limited to http(s)
and mailto: so nothing entered here can run script.
"""
import re
from urllib.parse import urlsplit

from markupsafe import Markup, escape

EMAIL = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
TOKEN = re.compile(
    r"`(?P<code>[^`]+)`"
    r"|\[(?P<ltext>[^\]]+)\]\((?P<lurl>[^)\s]+)\)"
    r"|<(?P<auto>https?://[^>\s]+|mailto:[^>\s]+|" + EMAIL + r")>"
    r"|\*\*(?P<b1>.+?)\*\*|(?<!\w)__(?P<b2>.+?)__(?!\w)"
    r"|(?<![\w*])\*(?P<i1>[^*\s](?:.*?[^*\s])?)\*(?![\w*])|(?<!\w)_(?P<i2>[^_\s](?:.*?[^_\s])?)_(?!\w)"
    r"|(?P<url>https?://[^\s<]*[^\s<.,;:!?)\]'\"])"
    r"|(?P<email>" + EMAIL + r")"
)


def safe_href(url):
    """The URL if it's an absolute http(s) or mailto: link, else None."""
    if any(c.isspace() for c in url):
        return None
    parts = urlsplit(url)
    if parts.scheme in ("http", "https") and parts.netloc:
        return url
    if parts.scheme == "mailto" and re.fullmatch(EMAIL, parts.path):
        return url
    return None


def _link(href, inner):
    href = safe_href(href)
    if href is None:
        return None
    attrs = ' target="_blank" rel="noopener noreferrer"' if not href.startswith("mailto:") else ""
    return f'<a href="{escape(href)}"{attrs}>{inner}</a>'


def render_inline(text):
    out, pos = [], 0
    for m in TOKEN.finditer(text):
        out.append(str(escape(text[pos:m.start()])))
        g = m.groupdict()
        html = None
        if g["code"] is not None:
            html = f"<code>{escape(g['code'])}</code>"
        elif g["ltext"] is not None:
            url = g["lurl"]
            if re.fullmatch(EMAIL, url):
                url = "mailto:" + url
            html = _link(url, render_inline(g["ltext"]))
        elif g["auto"] is not None:
            url = g["auto"]
            href = url if ":" in url else "mailto:" + url
            html = _link(href, escape(url[7:] if url.startswith("mailto:") else url))
        elif (g["b1"] or g["b2"]) is not None:
            html = f"<strong>{render_inline(g['b1'] or g['b2'])}</strong>"
        elif (g["i1"] or g["i2"]) is not None:
            html = f"<em>{render_inline(g['i1'] or g['i2'])}</em>"
        elif g["url"] is not None:
            html = _link(g["url"], escape(g["url"]))
        elif g["email"] is not None:
            html = _link("mailto:" + g["email"], escape(g["email"]))
        out.append(html if html is not None else str(escape(m.group(0))))
        pos = m.end()
    out.append(str(escape(text[pos:])))
    return Markup("".join(out))


def render_lines(text):
    """Render each line on its own; returns a list of Markup, blank lines dropped."""
    return [render_inline(line.strip()) for line in (text or "").splitlines() if line.strip()]
