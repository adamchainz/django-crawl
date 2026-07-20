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

    def test_invalid_xml(self):
        response = HttpResponse("<urlset", content_type="application/xml")

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
