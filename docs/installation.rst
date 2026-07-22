Installation
============

Requirements
------------

Python 3.10 to 3.14 supported.

Django 5.1 to 6.1 supported.

Installation
------------

1. Install with **pip**:

   .. code-block:: sh

       python -m pip install django-crawl

   django-crawl’s HTML parser is built in Rust, using the same parser as the Servo browser engine.
   Binary wheels are provided for common platforms; installing on other platforms requires a `Rust toolchain <https://www.rust-lang.org/tools/install>`__ to build from source.

2. Add django-crawl to your ``INSTALLED_APPS``:

   .. code-block:: python

       INSTALLED_APPS = [
           ...,
           "django_crawl",
           ...,
       ]

Now you can crawl your site with either the :doc:`CLI <cli>` or the :doc:`API <api>`.
