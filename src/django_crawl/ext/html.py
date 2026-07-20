from __future__ import annotations

import re
from urllib.parse import urljoin

from django.http import HttpResponseBase
from justhtml import JustHTML


def is_html(response: HttpResponseBase) -> bool:
    content_type = response.headers.get("Content-Type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type == "text/html"


def extract_links(response: HttpResponseBase) -> list[str]:
    links: list[str] = []

    link_header = response.headers.get("Link")
    if link_header:
        links.extend(parse_link_header(link_header))

    refresh_header = response.headers.get("Refresh")
    if refresh_header:
        refresh_url = parse_refresh(refresh_header)
        if refresh_url:
            links.append(refresh_url)

    content = response.getvalue().decode(response.charset or "utf-8", errors="replace")
    document = JustHTML(content, sanitize=False)

    base_href = ""
    for base in document.query("base[href]"):
        base_href = base.attrs["href"].strip()
        break

    def resolve(href: str) -> str:
        href = href.strip()
        return urljoin(base_href, href) if base_href else href

    for selector, attr in (
        ("a[href]", "href"),
        ("area[href]", "href"),
        ("link[href]", "href"),
        ("iframe[src]", "src"),
        ("script[src]", "src"),
        ("img[src]", "src"),
    ):
        for el in document.query(selector):
            value = el.attrs.get(attr)
            if value:
                links.append(resolve(value))

    for form in document.query("form[action]"):
        # Non-GET forms would be requested with the wrong method, and GETting
        # their actions may trigger side effects, e.g. the admin logout form.
        method = form.attrs.get("method", "").strip().lower()
        if method and method != "get":
            continue
        action = form.attrs.get("action")
        if action:
            links.append(resolve(action))

    for meta in document.query("meta[http-equiv]"):
        if meta.attrs.get("http-equiv", "").lower() != "refresh":
            continue
        url = parse_refresh(meta.attrs.get("content", ""))
        if url:
            links.append(resolve(url))

    return links


_LINK_HEADER_URL_RE = re.compile(r"<([^>]*)>")


def parse_link_header(header: str) -> list[str]:
    """Extract URLs from an RFC 8288 Link header value."""
    return _LINK_HEADER_URL_RE.findall(header)


_REFRESH_RE = re.compile(
    r"""[;,]\s*(?:url\s*=\s*)?(?:"([^"]*)"|'([^']*)'|(\S*))""",
    re.IGNORECASE,
)


def parse_refresh(content: str) -> str | None:
    """Extract the URL from a `Refresh` header or `<meta http-equiv="refresh">` value."""
    match = _REFRESH_RE.search(content)
    if match is None:
        return None
    url = next((g for g in match.groups() if g), "")
    return url or None
