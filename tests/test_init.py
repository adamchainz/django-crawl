from __future__ import annotations

import re
import sys

import pytest
from django.test import Client, TestCase

import django_crawl
from django_crawl import CrawlResult, ResponseError, StopReason

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup


class CrawlTests(TestCase):
    def test_returns_result(self):
        result = django_crawl.crawl("/ok/")

        assert isinstance(result, CrawlResult)
        assert result.count == 2
        assert result.errors == []
        assert result.stop_reason == StopReason.NO_MORE_LINKS

    def test_defaults_to_root_start_url(self):
        result = django_crawl.crawl(check=False)

        assert result.count == 6
        assert [error.url for error in result.errors] == [
            "/bad/",
            "/not-found/",
            "/server-error/",
        ]

    def test_check_raises_exception_group(self):
        with pytest.raises(ExceptionGroup) as excinfo:
            django_crawl.crawl("/")

        assert str(excinfo.value) == "Crawling found 3 errors. (3 sub-exceptions)"
        bad, not_found, server_error = excinfo.value.exceptions
        assert isinstance(bad, ResponseError)
        assert str(bad) == "HTTP 400 Bad Request: /bad/"
        assert isinstance(not_found, ResponseError)
        assert str(not_found) == "HTTP 404 Not Found: /not-found/"
        if sys.version_info >= (3, 11):
            assert isinstance(server_error, ValueError)
            assert str(server_error) == "broken"
            assert server_error.__notes__ == ["URL: /server-error/"]
        else:
            assert isinstance(server_error, ResponseError)
            assert str(server_error) == "HTTP 500 Internal Server Error: /server-error/"
            assert isinstance(server_error.__cause__, ValueError)

    def test_check_single_error(self):
        with pytest.raises(ExceptionGroup) as excinfo:
            django_crawl.crawl("/not-found/")

        assert str(excinfo.value) == "Crawling found 1 error. (1 sub-exception)"

    def test_check_false_returns_errors(self):
        result = django_crawl.crawl("/bad/", check=False)

        assert result.count == 1
        assert len(result.errors) == 1
        assert result.errors[0].url == "/bad/"
        assert result.errors[0].message == "HTTP 400 Bad Request"

    def test_client_argument(self):
        client = Client(headers={"x-setup": "1"})

        result = django_crawl.crawl("/needs-setup/", client=client)

        assert result.count == 1
        assert result.errors == []

    def test_depth(self):
        result = django_crawl.crawl("/ok/", depth=0)

        assert result.count == 1

    def test_max_urls(self):
        result = django_crawl.crawl("/ok/", max_urls=1)

        assert result.count == 1
        assert result.stop_reason == StopReason.MAX_URLS

    def test_max_query_variants(self):
        result = django_crawl.crawl("/query-variants/", max_query_variants=1)

        assert result.count == 1

    def test_exclude_strings_and_patterns(self):
        result = django_crawl.crawl(
            "/",
            exclude=[
                "^/bad/",
                re.compile("^/not-found/"),
                "^/server-error/",
            ],
        )

        assert result.count == 3
        assert result.errors == []

    def test_serves_static_files(self):
        result = django_crawl.crawl("/assets/", check=False)

        assert result.count == 4
        assert [error.url for error in result.errors] == ["/static/missing.js"]

    def test_on_response_called_for_every_response(self):
        paths = []

        django_crawl.crawl(
            "/ok/",
            on_response=lambda response: paths.append(response.wsgi_request.path),
        )

        assert paths == ["/ok/", "/deep/"]

    def test_on_response_exception_recorded(self):
        def check_response(response):
            assert response.wsgi_request.path != "/deep/", "found the deep page"

        result = django_crawl.crawl("/ok/", on_response=check_response, check=False)

        assert result.count == 2
        assert len(result.errors) == 1
        assert result.errors[0].url == "/deep/"
        assert result.errors[0].message == "Response check raised an exception."

    def test_on_response_exception_raised_with_check(self):
        def check_response(response):
            raise ValueError("check failed")

        with pytest.raises(ExceptionGroup) as excinfo:
            django_crawl.crawl("/ok/", depth=0, on_response=check_response)

        (error,) = excinfo.value.exceptions
        if sys.version_info >= (3, 11):
            assert isinstance(error, ValueError)
            assert error.__notes__ == ["URL: /ok/"]
        else:
            assert isinstance(error, ResponseError)
            assert isinstance(error.__cause__, ValueError)

    def test_invalid_start_url(self):
        with pytest.raises(ValueError) as excinfo:
            django_crawl.crawl("https://example.com/")

        assert str(excinfo.value) == (
            "Start URL must be an internal path or on an allowed host: "
            "'https://example.com/'."
        )
