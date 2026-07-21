from __future__ import annotations

from xml.etree import ElementTree

from django.http import HttpResponseBase

XML_MEDIA_TYPES = frozenset(
    {
        "application/xml",
        "text/xml",
        "application/rss+xml",
        "application/atom+xml",
    }
)


def is_xml(response: HttpResponseBase) -> bool:
    content_type = response.headers.get("Content-Type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type in XML_MEDIA_TYPES


def extract_links(response: HttpResponseBase) -> list[str]:
    raw = response.getvalue()
    if getattr(response, "streaming", False):
        # Reading consumed the streaming iterator; restore the content so
        # later readers still see the body.
        response.streaming_content = [raw]  # type: ignore[attr-defined]
    # Decode with the response's charset, since ElementTree assumes UTF-8 for
    # bytes. Parsing the decoded string makes the HTTP charset take precedence
    # over any in-document encoding declaration, which ElementTree ignores for
    # strings.
    text = raw.decode(response.charset or "utf-8", errors="replace")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return []

    root_name = local_name(root.tag)
    if root_name in ("urlset", "sitemapindex"):
        return extract_text_links(root, "loc")
    if root_name in ("rss", "feed"):
        return extract_feed_links(root)
    return []


def local_name(tag: str) -> str:
    return tag.rpartition("}")[2]


def extract_feed_links(root: ElementTree.Element) -> list[str]:
    # RSS link elements hold their URL as text; Atom link elements use an
    # href attribute. Feeds may contain both, e.g. atom:link in RSS.
    links = []
    for el in root.iter():
        if local_name(el.tag) != "link":
            continue
        if el.text:
            text = el.text.strip()
            if text:
                links.append(text)
        href = el.attrib.get("href")
        if href:
            links.append(href)
    return links


def extract_text_links(root: ElementTree.Element, name: str) -> list[str]:
    links = []
    for el in root.iter():
        if local_name(el.tag) != name or not el.text:
            continue
        text = el.text.strip()
        if text:
            links.append(text)
    return links
