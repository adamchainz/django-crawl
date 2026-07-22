=========
Changelog
=========

Unreleased
----------

* Add ``django_crawl.crawl()``, a Python API for crawling within your test suite.
  See the new :doc:`API documentation <api>`.

* Parse HTML with `html5ever <https://github.com/servo/html5ever>`__, the Servo browser engine’s Rust HTML parser, replacing justhtml.
  Link extraction is around 40 to 100 times faster, making crawls of large sites much quicker.
  Binary wheels are provided for common platforms; building from source now requires a Rust toolchain.

1.0.0 (2026-07-22)
------------------

* Initial release.
