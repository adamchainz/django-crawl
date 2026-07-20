from __future__ import annotations

from xml.etree import ElementTree

from django.http import HttpResponseBase

XML_MEDIA_TYPES = frozenset({"application/xml", "text/xml"})


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
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return []

    if local_name(root.tag) in ("urlset", "sitemapindex"):
        return extract_text_links(root, "loc")
    return []


def local_name(tag: str) -> str:
    return tag.rpartition("}")[2]


def extract_text_links(root: ElementTree.Element, name: str) -> list[str]:
    links = []
    for el in root.iter():
        if local_name(el.tag) != name or not el.text:
            continue
        text = el.text.strip()
        if text:
            links.append(text)
    return links
