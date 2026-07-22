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

2. Add django-crawl to your ``INSTALLED_APPS``:

   .. code-block:: python

       INSTALLED_APPS = [
           ...,
           "django_crawl",
           ...,
       ]

Now you can crawl your site with either the :doc:`CLI <cli>` or the :doc:`API <api>`.
