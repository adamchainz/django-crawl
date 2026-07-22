=========
Changelog
=========

Unreleased
----------

* Add ``django_crawl.crawl()``, a Python API for crawling within your test suite.
  See the new :doc:`API documentation <api>`.

  `PR #37 <https://github.com/adamchainz/django-crawl/pull/37>`__.

* Parse HTML with `html5ever <https://github.com/servo/html5ever>`__ instead of justhtml, speeding up link extraction by up to 100x.

  `PR #40 <https://github.com/adamchainz/django-crawl/pull/40>`__.

1.0.0 (2026-07-22)
------------------

* Initial release.
