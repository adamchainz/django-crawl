from __future__ import annotations

from django.test import SimpleTestCase

from django_crawl.crawler import pluralize


class PluralizeTests(SimpleTestCase):
    def test_pluralize(self):
        assert pluralize(0, "URL", "URLs") == "0 URLs"
        assert pluralize(1, "URL", "URLs") == "1 URL"
        assert pluralize(2, "URL", "URLs") == "2 URLs"
        assert pluralize(0, "error", "errors") == "0 errors"
        assert pluralize(1, "error", "errors") == "1 error"
        assert pluralize(2, "error", "errors") == "2 errors"
