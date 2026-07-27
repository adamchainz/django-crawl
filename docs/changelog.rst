=========
Changelog
=========

* Add ``--max-errors`` option, and ``max_errors`` argument to ``django_crawl.crawl()``, to stop the crawl after a given number of errors.

  `PR #44 <https://github.com/adamchainz/django-crawl/pull/44>`__.
  Thanks to Sébastien Corbin for the suggestion in `Issue #43 <https://github.com/adamchainz/django-crawl/issues/43>`__.

* Report Django URL name, if any, after URL path on errors.

  `PR #41 <https://github.com/adamchainz/django-crawl/pull/41>`__.

1.1.0 (2026-07-22)
------------------

* Add ``django_crawl.crawl()``, a Python API for crawling within your test suite.
  See the new :doc:`API documentation <api>`.

  `PR #37 <https://github.com/adamchainz/django-crawl/pull/37>`__.

* Parse HTML with `html5ever <https://github.com/servo/html5ever>`__ instead of justhtml, speeding up link extraction by up to 100x.

  `PR #40 <https://github.com/adamchainz/django-crawl/pull/40>`__.

1.0.0 (2026-07-22)
------------------

* Initial release.
