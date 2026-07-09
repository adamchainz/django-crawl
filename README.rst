============
django-crawl
============

.. image:: https://img.shields.io/github/actions/workflow/status/adamchainz/django-crawl/main.yml.svg?branch=main&style=for-the-badge
   :target: https://github.com/adamchainz/django-crawl/actions?workflow=CI

.. image:: https://img.shields.io/badge/Coverage-100%25-success?style=for-the-badge
   :target: https://github.com/adamchainz/django-crawl/actions?workflow=CI

.. image:: https://img.shields.io/pypi/v/django-crawl.svg?style=for-the-badge
   :target: https://pypi.org/project/django-crawl/

.. image:: https://img.shields.io/badge/code%20style-black-000000.svg?style=for-the-badge
   :target: https://github.com/psf/black

.. image:: https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white&style=for-the-badge
   :target: https://github.com/pre-commit/pre-commit
   :alt: pre-commit

An in-process site crawler using Django’s test client.

----

**Work smarter and faster** with my book `Boost Your Django DX <https://adamchainz.gumroad.com/l/byddx>`__ which covers many tools to improve your development experience.

----

Requirements
============

Python 3.10 to 3.14 supported.

Django 5.1 to 6.1 supported.

Installation
============

**First,** install with pip:

.. code-block:: bash

    python -m pip install django-crawl

**Second,** add the app to your ``INSTALLED_APPS`` setting:

.. code-block:: python

    INSTALLED_APPS = [
        ...,
        "django_crawl",
        ...,
    ]

Usage
=====

django-crawl provides a ``crawl`` management command that iteratively crawls through your site using Django’s tst client.
It renders pages within the same process and avoids serializing requests and responses to HTTP, making it somewhat faster and a lot more flexible than regular HTTP crawlers.
``crawl`` follows internal links, follows redirects, and reports every broken page it finds before failing.

To get started, run the ``crawl`` management command:

.. code-block:: console

    $ ./manage.py crawl

By default, the command starts at ``/`` and crawls up to 100 pages, up to five links deep.
Pass one or more start URLs to crawl specific areas:

.. code-block:: console

    $ ./manage.py crawl /admin/ /accounts/

Use ``--depth`` to control how many links are followed from each start URL:

.. code-block:: console

    $ ./manage.py crawl --depth 2

By default, django-crawl crawls up to 10 query string variants per path.
This avoids it getting stuck in large spaces of sorting and filtering links, such as Django admin changelists.
Use ``--max-query-variants`` to change this limit, or ``unlimited`` to disable it:

.. code-block:: console

    $ ./manage.py crawl --max-query-variants 20
    $ ./manage.py crawl --max-query-variants unlimited

The command follows redirects.
It reports HTTP 400, 404, 500, and other 4xx/5xx responses, including Django exception tracebacks when available.
It keeps crawling after errors and exits non-zero after reporting them all.

Response checks
===============

Pass ``-c`` or ``--command`` to run Python code for every response.
The response is available as ``response`` in locals, like ``manage.py shell -c``.
For example, to audit all URLs’ ``content-security-policy`` headers:

.. code-block:: console

    $ ./manage.py crawl -c 'print(response.wsgi_request.path, response.headers.get("Content-Security-Policy", ""))'

The code namespace persists between responses, so it can accumulate state.
If the code raises an exception, the command reports the URL and traceback, then continues crawling.

Setup
=====

By default, if ``django.contrib.auth`` is installed, django-crawl logs in as the first active superuser, ordered by the user model’s username field.
Disable this with ``--no-login``:

.. code-block:: console

    $ ./manage.py crawl --no-login

Use ``--login`` to log in as a specific user by username or email address:

.. code-block:: console

    $ ./manage.py crawl --login alice
    $ ./manage.py crawl --login alice@example.com

Use ``--setup-code`` for small snippets that configure the client before crawling.
Setup code runs after login, so it can inspect or adjust the logged-in session.
For example, to set the ``x-site`` header:

.. code-block:: console

    $ ./manage.py crawl --setup-code 'client.defaults["HTTP_X_SITE"] = "docs"'

For multi-host sites where middleware selects ``request.urlconf`` from the host, set the host header:

.. code-block:: console

    $ ./manage.py crawl --setup-code 'client.defaults["HTTP_HOST"] = "docs.example.com"'
