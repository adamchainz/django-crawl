from __future__ import annotations

import re
from urllib.parse import urljoin

from django.http import HttpResponseBase

from django_crawl._extract import extract_links as _extract_links
from django_crawl._extract import parse_srcset as parse_srcset


def is_html(response: HttpResponseBase) -> bool:
    content_type = response.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type == "text/html"


def extract_links(response: HttpResponseBase) -> list[str]:
    links: list[str] = []

    link_header = response.headers.get("link")
    if link_header:
        links.extend(parse_link_header(link_header))

    refresh_header = response.headers.get("refresh")
    if refresh_header:
        refresh_url = parse_refresh(refresh_header)
        if refresh_url:
            links.append(refresh_url)

    raw = response.getvalue()
    if getattr(response, "streaming", False):
        # Reading consumed the streaming iterator; restore the content so
        # later readers still see the body.
        response.streaming_content = [raw]  # type: ignore[attr-defined]
    content = raw.decode(response.charset or "utf-8", errors="replace")

    base_href, hrefs = _extract_links(content)
    if base_href:
        links.extend(urljoin(base_href, href) for href in hrefs)
    else:
        links.extend(hrefs)

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
