API
===

django-crawl can also be called from Python with ``django_crawl.crawl()``.
This is most useful for crawling your site within your test suite, where you can use your factories or fixtures to populate the database, and broken pages fail the test with their exceptions.
Minimal usage looks like:

.. code-block:: python

    from django.test import TestCase

    import django_crawl


    class CrawlTests(TestCase):
        def test_crawl(self):
            django_crawl.crawl()

.. currentmodule:: django_crawl

.. function:: crawl(*start_urls, client=None, depth=5, max_urls=1000, max_query_variants=10, exclude=(), on_response=None, check=True)

   Crawl the site in-process and return a |CrawlResult|__, like the :doc:`crawl management command <cli>`.

   .. |CrawlResult| replace:: ``CrawlResult``
   __ #results

   :param start_urls:
       URL paths to start crawling from.
       Defaults to ``/``.
       Invalid start URLs raise ``ValueError``.

   :param client:
       The Django test client instance to crawl with.
       Defaults to a fresh ``django_crawl.CrawlClient``, a test ``Client`` subclass that also serves static files, like ``runserver`` does.
       Pass in a client to customize log in, request headers, or other behaviour, per the below example.

   :param depth:
       Maximum link depth to crawl.
       ``0`` means crawl only the start URLs without following links.

   :param max_urls:
       Maximum number of URLs to request.

   :param max_query_variants:
       Maximum number of query string variants to crawl per path, or ``None`` for unlimited.

   :param exclude:
       Regular expressions, as strings or compiled patterns.
       Discovered URLs matching any pattern are skipped; start URLs are always crawled.

   :param on_response:
       A callable invoked with each response, for making custom checks.
       Exceptions it raises, such as from ``assert`` statements, are recorded as errors for that URL.

   :param check:
       Whether to raise an ``ExceptionGroup`` at the end if any errors were found (the default).
       Pass ``False`` to instead return the errors in the result.

   Unlike the management command, ``crawl()``:

   1. does not log in automatically.
   2. produces no output.
   3. stops at the first ``ValueError`` for an invalid start URL rather than reporting errors as it goes.

Logging in
----------

To crawl pages that require authentication, create a client, log it in, and pass it in:

.. code-block:: python

    from django.contrib.auth.models import User
    from django.test import TestCase

    import django_crawl


    class CrawlTests(TestCase):
        @classmethod
        def setUpTestData(cls):
            cls.admin = User.objects.create_superuser(username="admin")

        def test_crawl(self):
            client = django_crawl.CrawlClient()
            client.force_login(self.admin)
            django_crawl.crawl("/", "/admin/", client=client)

The client can also customize requests in other ways, such as sending extra headers:

.. code-block:: python

    client = django_crawl.CrawlClient(headers={"accept-language": "de"})
    django_crawl.crawl(client=client)

Checking responses
------------------

Use ``on_response`` to check every response, like the management command’s ``-c`` option:

.. code-block:: python

    class CrawlTests(TestCase):
        def test_crawl(self):
            def check_csp(response):
                assert (
                    "content-security-policy" in response.headers
                ), response.wsgi_request.path

            django_crawl.crawl(on_response=check_csp)

Results
-------

With ``check=True`` (the default), broken pages raise an |ExceptionGroup|__.
Each contained exception is the original exception the page raised, with the URL attached as a note, or a ``django_crawl.ResponseError`` for plain HTTP error statuses, like ``HTTP 404 Not Found: /dead-link/``.
(On Python 3.10, original exceptions are wrapped in ``ResponseError`` with ``__cause__`` set, since exception notes require Python 3.11.)

.. |ExceptionGroup| replace:: ``ExceptionGroup``
__ https://docs.python.org/3/library/exceptions.html#exception-groups

With ``check=False``, ``crawl()`` returns a ``CrawlResult`` without raising:

.. code-block:: python

    result = django_crawl.crawl(check=False)

``CrawlResult`` has three attributes:

* ``count``: the number of URLs crawled.

* ``errors``: a list of ``CrawlError`` instances, each with ``url``, ``message``, and ``exc_info`` attributes.

* ``stop_reason``: a ``django_crawl.StopReason`` enum value, ``NO_MORE_LINKS`` or ``MAX_URLS``.
