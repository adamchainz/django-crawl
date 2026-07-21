from __future__ import annotations

from django.http import HttpResponse, StreamingHttpResponse
from django.test import SimpleTestCase
from unittest_parametrize import ParametrizedTestCase, parametrize

from django_crawl.ext.html import (
    extract_links,
    is_html,
    parse_link_header,
    parse_refresh,
    parse_srcset,
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

    def test_media_elements(self):
        response = HttpResponse(
            '<video src="/v.mp4" poster="/v.jpg"><track src="/v.vtt"></video>'
            '<audio src="/a.mp3"><source src="/a.ogg"></audio>'
            '<object data="/o.pdf"></object>'
            '<embed src="/e.svg">'
            '<input type="image" src="/i.png">',
        )

        assert extract_links(response) == [
            "/a.ogg",
            "/v.mp4",
            "/v.jpg",
            "/a.mp3",
            "/v.vtt",
            "/o.pdf",
            "/e.svg",
            "/i.png",
        ]

    def test_srcset_urls(self):
        response = HttpResponse(
            '<img src="/a.png" srcset="/a-1x.png 1x, /a-2x.png 2x">'
            '<picture><source srcset="/b.webp 100w"><img src="/b.png"></picture>'
            '<img srcset="">',
        )

        assert extract_links(response) == [
            "/a.png",
            "/b.png",
            "/a-1x.png",
            "/a-2x.png",
            "/b.webp",
        ]

    def test_srcset_resolves_base_href(self):
        response = HttpResponse(
            '<base href="/sub/"><img srcset="image.png 1x">',
        )

        assert extract_links(response) == ["/sub/image.png"]

    def test_form_actions_respect_method(self):
        response = HttpResponse(
            '<form action="/default/"></form>'
            '<form action="/search/" method="get"></form>'
            '<form action="/upper/" method="GET"></form>'
            '<form action="/logout/" method="post"></form>'
            '<form action="" method="get"></form>',
        )

        assert extract_links(response) == ["/default/", "/search/", "/upper/"]

    def test_formaction_respects_method(self):
        response = HttpResponse(
            '<form action="/search/">'
            '<button formaction="/quick/">q</button>'
            '<input type="submit" formaction="/full/">'
            '<button formaction="/save/" formmethod="post">s</button>'
            '<button formaction="">empty</button>'
            "</form>"
            '<form action="/update/" method="post">'
            '<button formaction="/preview/">p</button>'
            '<button formaction="/export/" formmethod="GET">e</button>'
            "</form>",
        )

        assert extract_links(response) == [
            "/search/",
            "/quick/",
            "/full/",
            "/export/",
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

    def test_streaming_response_body_readable_after_extraction(self):
        response = StreamingHttpResponse(
            iter([b'<a href="/one/">one</a>']),
            content_type="text/html",
        )

        assert extract_links(response) == ["/one/"]
        assert response.getvalue() == b'<a href="/one/">one</a>'

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


class ParseSrcsetTests(ParametrizedTestCase, SimpleTestCase):
    @parametrize(
        ("value", "expected"),
        [
            ("", []),
            ("/a.png", ["/a.png"]),
            ("/a.png 1x, /b.png 2x", ["/a.png", "/b.png"]),
            ("/a.png 100w,", ["/a.png"]),
            (" , ", []),
            ("/a.png,/b.png 2x", ["/a.png,/b.png"]),
            ("/crop=10,20,300,200/img.jpg 1x", ["/crop=10,20,300,200/img.jpg"]),
            ("/a.png,, ,/b.png 2x", ["/a.png", "/b.png"]),
            ("/a.png 1x,/b.png 2x", ["/a.png", "/b.png"]),
            (
                "data:image/png;base64,iVBORw0KGgo 1x",
                ["data:image/png;base64,iVBORw0KGgo"],
            ),
        ],
    )
    def test_parse_srcset(self, value, expected):
        assert parse_srcset(value) == expected


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
