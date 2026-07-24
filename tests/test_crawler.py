from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase

from django_crawl.crawler import pluralize, response_url_name


class PluralizeTests(SimpleTestCase):
    def test_pluralize(self):
        assert pluralize(0, "URL", "URLs") == "0 URLs"
        assert pluralize(1, "URL", "URLs") == "1 URL"
        assert pluralize(2, "URL", "URLs") == "2 URLs"
        assert pluralize(0, "error", "errors") == "0 errors"
        assert pluralize(1, "error", "errors") == "1 error"
        assert pluralize(2, "error", "errors") == "2 errors"


class ResponseUrlNameTests(SimpleTestCase):
    def test_missing_resolver_match_attribute(self):
        assert response_url_name(SimpleNamespace()) is None

    def test_none_resolver_match(self):
        assert response_url_name(SimpleNamespace(resolver_match=None)) is None

    def test_resolver_match_with_url_name(self):
        response = SimpleNamespace(resolver_match=SimpleNamespace(url_name="not-found"))

        assert response_url_name(response) == "not-found"
