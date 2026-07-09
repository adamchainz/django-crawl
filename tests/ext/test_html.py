from __future__ import annotations

from django.http import HttpResponse, StreamingHttpResponse
from django.test import SimpleTestCase
from unittest_parametrize import ParametrizedTestCase, parametrize

from django_crawl.ext.html import (
    extract_links,
    is_html,
    parse_link_header,
    parse_refresh,
)


class IsHtmlTests(ParametrizedTestCase, SimpleTestCase):
    @parametrize(
        ("content_type", "expected"),
        [
            ("text/html", True),
            ("text/html; charset=utf-8", True),
            ("  Text/HTML ; charset=utf-8", True),
            ("text/html-fragment", False),
            ("application/xhtml+xml", False),
            ("text/plain", False),
            ("", False),
        ],
    )
    def test_is_html(self, content_type, expected):
        response = HttpResponse(content_type=content_type)
        assert is_html(response) is expected

    @parametrize(
        ("content_type", "expected"),
        [
            ("text/html", True),
            ("text/plain", False),
        ],
    )
    def test_is_html_streaming_response(self, content_type, expected):
        response = StreamingHttpResponse(iter([]), content_type=content_type)
        assert is_html(response) is expected


class ExtractLinksTests(SimpleTestCase):
    def test_returns_hrefs_and_skips_anchors_without_href(self):
        response = HttpResponse(
            '<a href="/one/">one</a><a>no href</a><a href="two/">two</a>',
        )

        assert extract_links(response) == ["/one/", "two/"]

    def test_link_header(self):
        response = HttpResponse("")
        response["Link"] = '</style.css>; rel=preload, </next>; rel="next"'

        assert extract_links(response) == ["/style.css", "/next"]

    def test_refresh_header(self):
        response = HttpResponse("")
        response["Refresh"] = "0; url=/next"

        assert extract_links(response) == ["/next"]

    def test_refresh_header_without_url_is_skipped(self):
        response = HttpResponse("")
        response["Refresh"] = "5"

        assert extract_links(response) == []

    def test_resolves_base_href(self):
        response = HttpResponse(
            '<base href="/sub/"><a href="page/">p</a><img src="/img.png">',
        )

        assert extract_links(response) == ["/sub/page/", "/img.png"]

    def test_all_tier1_elements(self):
        response = HttpResponse(
            '<area href="/area">'
            '<link href="/style.css" rel="stylesheet">'
            '<script src="/s.js"></script>'
            '<iframe src="/frame"></iframe>'
            '<img src="/i.png">'
            '<form action="/submit"></form>',
        )

        assert extract_links(response) == [
            "/area",
            "/style.css",
            "/frame",
            "/s.js",
            "/i.png",
            "/submit",
        ]

    def test_skips_empty_attribute_values(self):
        response = HttpResponse('<a href="">empty</a><a href="/ok">ok</a>')

        assert extract_links(response) == ["/ok"]

    def test_streaming_response_links_are_extracted(self):
        response = StreamingHttpResponse(
            iter([b'<a href="/one/">one</a>', b'<a href="/two/">two</a>']),
            content_type="text/html",
        )

        assert extract_links(response) == ["/one/", "/two/"]

    def test_streaming_response_with_link_header(self):
        response = StreamingHttpResponse(iter([b""]), content_type="text/html")
        response["Link"] = "</style.css>; rel=preload"

        assert extract_links(response) == ["/style.css"]

    def test_streaming_response_chunks_are_concatenated(self):
        response = StreamingHttpResponse(
            iter([b"<a hr", b'ef="/page/">p</a>']),
            content_type="text/html",
        )

        assert extract_links(response) == ["/page/"]

    def test_meta_refresh(self):
        response = HttpResponse(
            '<meta http-equiv="refresh" content="0; url=/next">'
            '<meta http-equiv="refresh" content="5; url=&#39;/quoted&#39;">'
            '<meta http-equiv="content-type" content="text/html">'
            '<meta http-equiv="refresh" content="3">',
        )

        assert extract_links(response) == ["/next", "/quoted"]


class ParseLinkHeaderTests(ParametrizedTestCase, SimpleTestCase):
    @parametrize(
        ("header", "expected"),
        [
            ("", []),
            ("</a>; rel=next", ["/a"]),
            ('</a>; rel="next", </b>; rel="prev"', ["/a", "/b"]),
        ],
    )
    def test_parse_link_header(self, header, expected):
        assert parse_link_header(header) == expected


class ParseRefreshTests(ParametrizedTestCase, SimpleTestCase):
    @parametrize(
        ("content", "expected"),
        [
            ("5", None),
            ("0; url=/x", "/x"),
            ("0;URL='/x'", "/x"),
            ('0; url="/x"', "/x"),
            ("0; /x", "/x"),
            ("0;", None),
        ],
    )
    def test_parse_refresh(self, content, expected):
        assert parse_refresh(content) == expected
