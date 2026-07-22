from __future__ import annotations

import re
import sys
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import Any, cast
from urllib.parse import urldefrag, urljoin, urlparse, urlsplit, urlunsplit

from django.apps import apps
from django.conf import settings
from django.contrib.staticfiles.handlers import StaticFilesHandlerMixin
from django.core.handlers.base import BaseHandler
from django.http import Http404
from django.http.request import validate_host
from django.test import Client, override_settings
from django.test.client import ClientHandler

from django_crawl.ext.html import extract_links as extract_html_links
from django_crawl.ext.html import is_html
from django_crawl.ext.xml import extract_links as extract_xml_links
from django_crawl.ext.xml import is_xml

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

DEFAULT_DEPTH = 5
DEFAULT_MAX_URLS = 1000
DEFAULT_MAX_QUERY_VARIANTS = 10
TESTSERVER = "testserver"


@dataclass(frozen=True)
class QueueItem:
    url: str
    depth: int


@dataclass
class CrawlError:
    url: str
    message: str
    exc_info: tuple[type[BaseException], BaseException, TracebackType | None] | None = (
        None
    )


class StopReason(Enum):
    NO_MORE_LINKS = "no_more_links"
    MAX_URLS = "max_urls"


@dataclass
class CrawlResult:
    count: int
    errors: list[CrawlError]
    stop_reason: StopReason


class ResponseError(Exception):
    """An error response found by crawl(check=True)."""


def normalize_url(
    url: str,
    allowed_hosts: tuple[str, ...] = (),
    client_host: str | None = None,
) -> str | None:
    url, _fragment = urldefrag(url)
    parts = urlsplit(url)
    if parts.scheme and parts.scheme not in ("http", "https"):
        return None
    if parts.scheme and not parts.netloc:
        return None
    netloc = ""
    if parts.netloc:
        host_port = split_host(parts.netloc)
        if host_port is None:
            return None
        host, port = host_port
        # A '*' entry would make every host look internal, so ignore it.
        if not validate_host(host, [h for h in allowed_hosts if h != "*"]):
            return None
        client_host_port = split_host(client_host) if client_host else None
        if client_host_port is None or host != client_host_port[0]:
            # Keep the host so the URL is requested with a matching Host
            # header, for sites that route on it.
            netloc = host if port is None else f"{host}:{port}"
    path = parts.path or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    return urlunsplit(("", netloc, path, parts.query, ""))


def split_host(netloc: str) -> tuple[str, int | None] | None:
    """Extract the lowercased host, without userinfo, and port from a netloc."""
    parts = urlsplit(f"//{netloc}")
    try:
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if not host:
        return None
    if ":" in host:
        host = f"[{host}]"
    return host, port


def normalize_start_urls(
    urls: Sequence[str],
    allowed_hosts: tuple[str, ...],
    client_host: str | None,
) -> list[str]:
    normalized = []
    for url in urls:
        normalized_url = normalize_url(url, allowed_hosts, client_host)
        if normalized_url is None:
            raise ValueError(
                f"Start URL must be an internal path or on an allowed host: {url!r}."
            )
        normalized.append(normalized_url)
    return normalized


@contextmanager
def extended_allowed_hosts(*hosts: str | None) -> Iterator[None]:
    """Extend ALLOWED_HOSTS with the given hosts, unless it allows all."""
    if "*" not in settings.ALLOWED_HOSTS:
        extra = [h for h in hosts if h and h not in settings.ALLOWED_HOSTS]
        if extra:
            with override_settings(ALLOWED_HOSTS=[*settings.ALLOWED_HOSTS, *extra]):
                yield
            return
    yield


def excluded(url: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    return any(pattern.search(url) for pattern in patterns)


def pluralize(count: int, singular: str, plural: str) -> str:
    if count == 1:
        return f"1 {singular}"
    return f"{count} {plural}"


class StaticFilesClientHandler(StaticFilesHandlerMixin, ClientHandler):
    """
    Test client handler that serves static files with the staticfiles
    finders, like runserver, when the URL isn't otherwise handled. This
    allows checking asset links without static-serving URL configuration.
    """

    # The mixin no-ops load_middleware for wrapping handlers, but this
    # handler serves regular requests itself, so restore it.
    load_middleware = BaseHandler.load_middleware

    def __init__(self, enforce_csrf_checks: bool = True) -> None:
        super().__init__(enforce_csrf_checks)
        self.base_url = urlparse(self.get_base_url())

    def get_response(self, request: Any) -> Any:
        response = BaseHandler.get_response(self, request)
        if response.status_code == 404 and self._should_handle(request.path):
            try:
                return self.serve(request)
            except Http404:
                pass
        return response


class CrawlClient(Client):
    """Test client that serves static files for asset URLs, like runserver."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if apps.is_installed("django.contrib.staticfiles") and settings.STATIC_URL:
            self.handler = StaticFilesClientHandler(self.handler.enforce_csrf_checks)


def crawl(
    *start_urls: str,
    client: Client | None = None,
    depth: int = DEFAULT_DEPTH,
    max_urls: int = DEFAULT_MAX_URLS,
    max_query_variants: int | None = DEFAULT_MAX_QUERY_VARIANTS,
    exclude: Sequence[str | re.Pattern[str]] = (),
    on_response: Callable[[Any], object] | None = None,
    check: bool = True,
) -> CrawlResult:
    """Crawl the site in-process and report broken pages."""
    if client is None:
        client = CrawlClient(HTTP_HOST=TESTSERVER)
    http_host = client.defaults.get("HTTP_HOST")
    client_host = http_host or TESTSERVER
    allowed_hosts = tuple(
        dict.fromkeys(h for h in (TESTSERVER, http_host, *settings.ALLOWED_HOSTS) if h)
    )
    if start_urls:
        urls = normalize_start_urls(start_urls, allowed_hosts, client_host)
    else:
        urls = ["/"]
    exclude_patterns = [
        re.compile(pattern) if isinstance(pattern, str) else pattern
        for pattern in exclude
    ]

    on_response_hook: Callable[[Any, str], CrawlError | None] | None = None
    if on_response is not None:
        check_response = on_response

        def run_check(response: Any, url: str) -> CrawlError | None:
            try:
                check_response(response)
            except Exception:
                exc_info = sys.exc_info()
                return CrawlError(
                    url=url,
                    message="Response check raised an exception.",
                    exc_info=exc_info if exc_info[0] is not None else None,
                )
            return None

        on_response_hook = run_check

    with extended_allowed_hosts(TESTSERVER, http_host):
        result = crawl_urls(
            client,
            urls,
            depth=depth,
            max_urls=max_urls,
            max_query_variants=max_query_variants,
            allowed_hosts=allowed_hosts,
            client_host=client_host,
            exclude=exclude_patterns,
            on_response=on_response_hook,
        )

    if check and result.errors:
        raise error_group(result.errors)
    return result


def error_group(errors: Sequence[CrawlError]) -> ExceptionGroup[Exception]:
    exceptions: list[Exception] = []
    for error in errors:
        if error.exc_info is not None:
            exc = cast(Exception, error.exc_info[1])
            if hasattr(exc, "add_note"):
                exc.add_note(f"URL: {error.url}")
                exceptions.append(exc)
            else:
                wrapper = ResponseError(f"{error.message}: {error.url}")
                wrapper.__cause__ = exc
                exceptions.append(wrapper)
        else:
            exceptions.append(ResponseError(f"{error.message}: {error.url}"))
    return ExceptionGroup(
        f"Crawling found {pluralize(len(exceptions), 'error', 'errors')}.",
        exceptions,
    )


def crawl_urls(
    client: Client,
    start_urls: Sequence[str],
    *,
    depth: int,
    max_urls: int,
    max_query_variants: int | None,
    allowed_hosts: tuple[str, ...] = (),
    client_host: str | None = None,
    exclude: Sequence[re.Pattern[str]] = (),
    on_url: Callable[[str, int], None] | None = None,
    on_response: Callable[[Any, str], CrawlError | None] | None = None,
    on_error: Callable[[CrawlError], None] | None = None,
) -> CrawlResult:
    queue = deque(QueueItem(url, 0) for url in start_urls)
    seen: set[str] = set()
    query_variants: dict[str, set[str]] = {}
    errors: list[CrawlError] = []

    def record(error: CrawlError) -> None:
        errors.append(error)
        if on_error is not None:
            on_error(error)

    stop_reason = StopReason.NO_MORE_LINKS
    while queue:
        item = queue.popleft()
        if item.url in seen:
            continue
        if not allow_query_variant(item.url, query_variants, max_query_variants):
            continue
        if len(seen) >= max_urls:
            stop_reason = StopReason.MAX_URLS
            break
        seen.add(item.url)
        if on_url is not None:
            on_url(item.url, len(seen))

        path = item.url
        headers: dict[str, str] = {}
        url_parts = urlsplit(item.url)
        if url_parts.netloc:
            path = urlunsplit(("", "", url_parts.path, url_parts.query, ""))
            headers["host"] = url_parts.netloc

        try:
            response = client.get(path, headers=headers)
        except Exception:
            _exc = sys.exc_info()
            record(
                CrawlError(
                    url=item.url,
                    message="HTTP 500 Internal Server Error",
                    exc_info=_exc if _exc[0] is not None else None,
                )
            )
            continue

        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location")
            if location:
                linked_url = normalize_url(
                    urljoin(item.url, location), allowed_hosts, client_host
                )
                if (
                    linked_url is not None
                    and linked_url not in seen
                    and not excluded(linked_url, exclude)
                ):
                    queue.append(QueueItem(linked_url, item.depth))
            continue
        if response.status_code >= 400:
            record(status_error(item.url, response))

        # Extract links before running response hooks, which may consume
        # a streaming response's body.
        links: list[str] = []
        if item.depth < depth:
            if is_html(response):
                links = extract_html_links(response)
            elif is_xml(response):
                links = extract_xml_links(response)

        if on_response is not None:
            response_error = on_response(response, item.url)
            if response_error is not None:
                record(response_error)

        for href in links:
            linked_url = normalize_url(
                urljoin(item.url, href), allowed_hosts, client_host
            )

            if (
                linked_url is not None
                and linked_url not in seen
                and not excluded(linked_url, exclude)
            ):
                queue.append(QueueItem(linked_url, item.depth + 1))

        # Release unconsumed streaming responses, e.g. served static
        # files, which otherwise hold their files open.
        if response.streaming and not response.closed:
            response.close()

    return CrawlResult(count=len(seen), errors=errors, stop_reason=stop_reason)


def allow_query_variant(
    url: str,
    query_variants: dict[str, set[str]],
    max_query_variants: int | None,
) -> bool:
    if max_query_variants is None:
        return True
    parts = urlsplit(url)
    variants = query_variants.setdefault(f"{parts.netloc}{parts.path}", set())
    if parts.query in variants:
        return True
    if len(variants) >= max_query_variants:
        return False
    variants.add(parts.query)
    return True


def status_error(url: str, response: Any) -> CrawlError:
    return CrawlError(
        url=url,
        message=f"HTTP {response.status_code} {response.reason_phrase}",
        exc_info=getattr(response, "exc_info", None),
    )
