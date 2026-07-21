from __future__ import annotations

from django.http import HttpResponse, StreamingHttpResponse
from django.test import SimpleTestCase
from unittest_parametrize import ParametrizedTestCase, parametrize

from django_crawl.ext.xml import extract_links, is_xml


class IsXmlTests(ParametrizedTestCase, SimpleTestCase):
    @parametrize(
        ("content_type", "expected"),
        [
            ("application/xml", True),
            ("application/xml; charset=utf-8", True),
            ("text/xml", True),
            ("  Application/XML ; charset=utf-8", True),
            ("application/rss+xml", True),
            ("application/atom+xml", True),
            ("text/html", False),
            ("application/json", False),
            ("", False),
        ],
    )
    def test_is_xml(self, content_type, expected):
        response = HttpResponse(content_type=content_type)
        assert is_xml(response) is expected


class ExtractLinksTests(SimpleTestCase):
    def test_sitemap_urlset(self):
        response = HttpResponse(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://example.com/one/</loc></url>"
            "<url><loc> </loc></url>"
            "<url><loc/></url>"
            "<url><loc>https://example.com/two/</loc></url>"
            "</urlset>",
            content_type="application/xml",
        )

        assert extract_links(response) == [
            "https://example.com/one/",
            "https://example.com/two/",
        ]

    def test_sitemap_index(self):
        response = HttpResponse(
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<sitemap><loc>https://example.com/sitemap-a.xml</loc></sitemap>"
            "</sitemapindex>",
            content_type="application/xml",
        )

        assert extract_links(response) == ["https://example.com/sitemap-a.xml"]

    def test_sitemap_without_namespace(self):
        response = HttpResponse(
            "<urlset><url><loc>/one/</loc></url></urlset>",
            content_type="text/xml",
        )

        assert extract_links(response) == ["/one/"]

    def test_rss_feed(self):
        response = HttpResponse(
            '<?xml version="1.0" encoding="utf-8"?>'
            '<rss xmlns:atom="http://www.w3.org/2005/Atom" version="2.0">'
            "<channel>"
            "<title>Example</title>"
            "<link>https://example.com/blog/</link>"
            '<atom:link href="https://example.com/feed.rss" rel="self"/>'
            "<link> </link>"
            "<item><title>One</title><link>https://example.com/one/</link></item>"
            "</channel>"
            "</rss>",
            content_type="application/rss+xml; charset=utf-8",
        )

        assert extract_links(response) == [
            "https://example.com/blog/",
            "https://example.com/feed.rss",
            "https://example.com/one/",
        ]

    def test_atom_feed(self):
        response = HttpResponse(
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            '<link href="https://example.com/blog/" rel="alternate"/>'
            "<link/>"
            '<entry><link href="https://example.com/one/"/></entry>'
            "</feed>",
            content_type="application/atom+xml; charset=utf-8",
        )

        assert extract_links(response) == [
            "https://example.com/blog/",
            "https://example.com/one/",
        ]

    def test_sitemap_in_response_charset_without_declaration(self):
        response = HttpResponse(
            "<urlset><url><loc>/café/</loc></url></urlset>".encode("iso-8859-1"),
            content_type="application/xml; charset=iso-8859-1",
        )

        assert extract_links(response) == ["/café/"]

    def test_sitemap_with_matching_encoding_declaration(self):
        document = (
            '<?xml version="1.0" encoding="iso-8859-1"?>'
            "<urlset><url><loc>/café/</loc></url></urlset>"
        )
        response = HttpResponse(
            document.encode("iso-8859-1"),
            content_type="application/xml; charset=iso-8859-1",
        )

        assert extract_links(response) == ["/café/"]

    def test_invalid_xml(self):
        response = HttpResponse("<urlset", content_type="application/xml")

        assert extract_links(response) == []

    def test_invalid_xml_with_encoding_declaration(self):
        response = HttpResponse(
            '<?xml version="1.0" encoding="UTF-8"?><urlset',
            content_type="application/xml",
        )

        assert extract_links(response) == []

    def test_unknown_root_element(self):
        response = HttpResponse(
            "<data><loc>/one/</loc></data>",
            content_type="application/xml",
        )

        assert extract_links(response) == []

    def test_streaming_response_body_readable_after_extraction(self):
        content = b"<urlset><url><loc>/one/</loc></url></urlset>"
        response = StreamingHttpResponse(
            iter([content]),
            content_type="application/xml",
        )

        assert extract_links(response) == ["/one/"]
        assert response.getvalue() == content
