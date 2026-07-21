from __future__ import annotations

import logging
import sys
import threading
import warnings
from argparse import ArgumentParser
from collections import deque
from collections.abc import Iterator
from contextlib import (
    ExitStack,
    contextmanager,
    nullcontext,
    redirect_stderr,
    redirect_stdout,
)
from dataclasses import dataclass
from enum import Enum
from functools import partial
from types import TracebackType
from typing import Any
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

from django.apps import apps
from django.conf import settings as settings
from django.contrib.auth import get_user_model as get_user_model
from django.core.exceptions import FieldDoesNotExist as FieldDoesNotExist
from django.core.exceptions import MultipleObjectsReturned as MultipleObjectsReturned
from django.core.exceptions import ObjectDoesNotExist as ObjectDoesNotExist
from django.core.management.base import CommandError as CommandError
from django.http.request import validate_host
from django.test import Client, override_settings
from django_rich.management import RichCommand
from rich.console import Console
from rich.traceback import Traceback

from django_crawl.ext.argparse import (
    max_query_variants as max_query_variants_type,
)
from django_crawl.ext.argparse import non_negative_int, positive_int
from django_crawl.ext.html import extract_links as extract_html_links
from django_crawl.ext.html import is_html
from django_crawl.ext.xml import extract_links as extract_xml_links
from django_crawl.ext.xml import is_xml

if sys.version_info >= (3, 11):
    from typing import assert_never
else:

    def assert_never(value: Any) -> None:  # pragma: no cover
        raise AssertionError(f"Expected code to be unreachable, but got: {value!r}")


DEFAULT_DEPTH = 5
DEFAULT_MAX_URLS = 1000
DEFAULT_MAX_QUERY_VARIANTS = 10
TESTSERVER = "testserver"


auth_installed = partial(apps.is_installed, "django.contrib.auth")


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


class SuppressDjangoRequestLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return False


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


def pluralize(count: int, singular: str, plural: str) -> str:
    if count == 1:
        return f"1 {singular}"
    return f"{count} {plural}"


@contextmanager
def status_aware_stderr(status: Any) -> Iterator[None]:
    real_stderr = sys.stderr
    # The lock stops pauses interleaving when the crawled app writes from
    # threads; the thread-local flag keeps re-entrant writes from
    # double-pausing.
    lock = threading.Lock()
    local = threading.local()

    def _pause_status(fn: Any, *args: Any, **kwargs: Any) -> Any:
        if getattr(local, "pausing", False):
            return fn(*args, **kwargs)
        local.pausing = True
        try:
            with lock:
                stop = getattr(status, "stop", None)
                start = getattr(status, "start", None)
                if stop is not None:
                    stop()
                try:
                    return fn(*args, **kwargs)
                finally:
                    if start is not None:
                        start()
        finally:
            local.pausing = False

    class _Stream:
        def write(self, data: str) -> int:
            return _pause_status(real_stderr.write, data)  # type: ignore[no-any-return]

        def flush(self) -> None:
            real_stderr.flush()

        def __getattr__(self, name: str) -> Any:
            return getattr(real_stderr, name)

    sys.stderr = _Stream()

    original_emit = logging.StreamHandler.emit

    def _emit(
        handler_self: logging.StreamHandler[Any], record: logging.LogRecord
    ) -> None:
        _pause_status(original_emit, handler_self, record)

    logging.StreamHandler.emit = _emit  # type: ignore[assignment]

    original_showwarning = warnings.showwarning

    def _showwarning(
        message: Warning | str,
        category: type[Warning],
        filename: str,
        lineno: int,
        file: Any = None,
        line: str | None = None,
    ) -> None:
        _pause_status(
            original_showwarning, message, category, filename, lineno, file, line
        )

    warnings.showwarning = _showwarning

    try:
        yield
    finally:
        sys.stderr = real_stderr
        logging.StreamHandler.emit = original_emit  # type: ignore[method-assign]
        warnings.showwarning = original_showwarning


class PassthroughStream:
    """
    Adapt a Django ``OutputWrapper`` to the file-like interface expected by
    ``redirect_stdout``/``redirect_stderr`` and ``print()``: suppress the
    wrapper's default trailing newline and return the number of characters
    written from ``write()``.
    """

    def __init__(self, output: Any) -> None:
        self.output = output

    def write(self, text: str) -> int:
        self.output.write(text, ending="")
        return len(text)

    def flush(self) -> None:
        self.output.flush()


class Command(RichCommand):
    help = "Crawl the Django site with the test client and report broken pages."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "urls",
            nargs="*",
            help=("URL paths to start crawling from. Defaults to /."),
        )
        parser.add_argument(
            "--depth",
            type=non_negative_int,
            default=DEFAULT_DEPTH,
            help=(
                f"Maximum link depth to crawl. Defaults to {DEFAULT_DEPTH}. "
                "0 means crawl only the start URLs without following links."
            ),
        )
        parser.add_argument(
            "--max-urls",
            type=positive_int,
            default=DEFAULT_MAX_URLS,
            help=f"Maximum number of URLs to request. Defaults to {DEFAULT_MAX_URLS}.",
        )
        parser.add_argument(
            "--max-query-variants",
            type=max_query_variants_type,
            default=DEFAULT_MAX_QUERY_VARIANTS,
            help=(
                "Maximum number of query string variants to crawl per path. "
                f"Defaults to {DEFAULT_MAX_QUERY_VARIANTS}. Use 'unlimited' to disable."
            ),
        )
        login_group = parser.add_mutually_exclusive_group()
        login_group.add_argument(
            "--no-login",
            action="store_true",
            help="Do not automatically log in before crawling.",
        )
        login_group.add_argument(
            "--login",
            metavar="USERNAME_OR_EMAIL",
            help="Log in as the user with this username or email address.",
        )
        parser.add_argument(
            "--setup-code",
            action="append",
            default=[],
            metavar="CODE",
            help="Python code to run before crawling with client in locals.",
        )
        parser.add_argument(
            "-c",
            "--command",
            dest="code",
            metavar="CODE",
            help="Python code to run for every response with response in locals.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        depth: int = options["depth"]
        max_urls: int = options["max_urls"]
        max_query_variants: int | None = options["max_query_variants"]
        code: str | None = options["code"]
        verbosity: int = options["verbosity"]

        client = Client(HTTP_HOST=TESTSERVER)
        namespace = self.setup_namespace(client)
        user = self.configure_client(client, options, namespace)

        http_host = client.defaults.get("HTTP_HOST")
        allowed_hosts = tuple(
            dict.fromkeys(
                h for h in (TESTSERVER, http_host, *settings.ALLOWED_HOSTS) if h
            )
        )
        start_urls = self.start_urls(options["urls"], allowed_hosts, http_host)

        start_message = f"🐛 Crawling up to {pluralize(max_urls, 'URL', 'URLs')}"
        if user is not None:
            start_message += f", logged in as {user}"
        self.console.print(start_message, soft_wrap=True)

        django_request_logger = logging.getLogger("django.request")
        log_filter = SuppressDjangoRequestLogs()
        status: Any = (
            self.console.status("Crawling URL 1…")
            if self.console.is_terminal
            else nullcontext()
        )
        with ExitStack() as stack:
            if "*" not in settings.ALLOWED_HOSTS:
                extra = [
                    h
                    for h in (TESTSERVER, http_host)
                    if h and h not in settings.ALLOWED_HOSTS
                ]
                if extra:
                    stack.enter_context(
                        override_settings(
                            ALLOWED_HOSTS=[*settings.ALLOWED_HOSTS, *extra]
                        )
                    )
            django_request_logger.addFilter(log_filter)
            stack.callback(django_request_logger.removeFilter, log_filter)
            stack.enter_context(status)
            if self.console.is_terminal:
                stack.enter_context(status_aware_stderr(status))
            result = self.crawl(
                client,
                start_urls,
                depth,
                max_urls,
                max_query_variants,
                code,
                allowed_hosts,
                verbosity=verbosity,
                status=status,
                code_namespace=namespace,
                client_host=http_host,
            )

        match result.stop_reason:
            case StopReason.MAX_URLS:
                reason = f"reaching max URL limit of {max_urls}"
            case StopReason.NO_MORE_LINKS:
                reason = "finding no more links"
            case _:  # pragma: no cover
                assert_never(result.stop_reason)
        self.console.print(
            f"🦋 Crawled {pluralize(result.count, 'URL', 'URLs')}, "
            f"encountered {pluralize(len(result.errors), 'error', 'errors')}, "
            f"stopped due to {reason}.",
            soft_wrap=True,
        )
        if result.errors:
            raise SystemExit(1)

    def start_urls(
        self,
        urls: list[str],
        allowed_hosts: tuple[str, ...] = (),
        client_host: str | None = None,
    ) -> list[str]:
        if urls:
            return self.normalize_start_urls(urls, allowed_hosts, client_host)
        return ["/"]

    def normalize_start_urls(
        self,
        urls: list[str],
        allowed_hosts: tuple[str, ...],
        client_host: str | None,
    ) -> list[str]:
        normalized = []
        for url in urls:
            normalized_url = normalize_url(url, allowed_hosts, client_host)
            if normalized_url is None:
                raise CommandError(
                    f"Start URL must be an internal path or on an allowed host: "
                    f"{url!r}."
                )
            normalized.append(normalized_url)
        return normalized

    def configure_client(
        self, client: Client, options: dict[str, Any], namespace: dict[str, Any]
    ) -> Any:
        login = options["login"]
        if login is not None:
            user: Any = self.login_user(client, login)
        elif not options["no_login"]:
            user = self.login_superuser(client)
        else:
            user = None

        for code in options["setup_code"]:
            exec(code, namespace, namespace)

        return user

    def setup_namespace(self, client: Client) -> dict[str, Any]:
        namespace = {
            "client": client,
            "settings": settings,
            "get_user_model": get_user_model,
        }
        if auth_installed():
            namespace["User"] = get_user_model()
        return namespace

    def login_superuser(self, client: Client) -> Any:
        if not auth_installed():
            return None
        User = get_user_model()
        user = (
            User._default_manager.filter(is_active=True, is_superuser=True)
            .order_by(User.USERNAME_FIELD)  # type: ignore[attr-defined]
            .first()
        )
        if user is not None:
            client.force_login(user)
        return user

    def login_user(self, client: Client, username_or_email: str) -> Any:
        if not auth_installed():
            raise CommandError(
                "Cannot use --login: 'django.contrib.auth' is not installed."
            )
        User = get_user_model()
        query = {User.USERNAME_FIELD: username_or_email}  # type: ignore[attr-defined]
        try:
            user = User._default_manager.get(**query)
        except ObjectDoesNotExist:
            user = self.get_user_by_email(User, username_or_email)
        except MultipleObjectsReturned:
            username_field: str = User.USERNAME_FIELD  # type: ignore[attr-defined]
            raise CommandError(
                f"Multiple users have {username_field} {username_or_email!r}."
            ) from None
        client.force_login(user)
        return user

    def get_user_by_email(self, User: Any, email: str) -> Any:
        if User.USERNAME_FIELD == "email":
            raise CommandError(f"User {email!r} does not exist.")
        try:
            User._meta.get_field("email")
        except FieldDoesNotExist:
            raise CommandError(f"User {email!r} does not exist.") from None
        try:
            return User._default_manager.get(email=email)
        except ObjectDoesNotExist:
            raise CommandError(f"User {email!r} does not exist.") from None
        except MultipleObjectsReturned:
            raise CommandError(f"Multiple users have email {email!r}.") from None

    def crawl(
        self,
        client: Client,
        start_urls: list[str],
        depth: int,
        max_urls: int,
        max_query_variants: int | None,
        code: str | None,
        allowed_hosts: tuple[str, ...] = (),
        verbosity: int = 1,
        status: Any = None,
        code_namespace: dict[str, Any] | None = None,
        client_host: str | None = None,
    ) -> CrawlResult:
        queue = deque(QueueItem(url, 0) for url in start_urls)
        seen: set[str] = set()
        query_variants: dict[str, set[str]] = {}
        errors: list[CrawlError] = []
        if code_namespace is None:
            code_namespace = {}
        update_status = getattr(status, "update", None)

        while queue and len(seen) < max_urls:
            item = queue.popleft()
            if item.url in seen:
                continue
            if not self.allow_query_variant(
                item.url, query_variants, max_query_variants
            ):
                continue
            seen.add(item.url)
            if update_status is not None:
                update_status(f"Crawling URL {len(seen)}…")

            path = item.url
            headers: dict[str, str] = {}
            url_parts = urlsplit(item.url)
            if url_parts.netloc:
                path = urlunsplit(("", "", url_parts.path, url_parts.query, ""))
                headers["host"] = url_parts.netloc

            if verbosity >= 2:
                self.console.print(item.url, markup=False, soft_wrap=True)

            try:
                response = client.get(path, headers=headers)
            except Exception:
                _exc = sys.exc_info()
                error = CrawlError(
                    url=item.url,
                    message="HTTP 500 Internal Server Error",
                    exc_info=_exc if _exc[0] is not None else None,
                )
                errors.append(error)
                self.report_error(self.console, error)
                continue

            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if location:
                    linked_url = normalize_url(
                        urljoin(item.url, location), allowed_hosts, client_host
                    )
                    if linked_url is not None and linked_url not in seen:
                        queue.append(QueueItem(linked_url, item.depth))
                continue
            if response.status_code >= 400:
                error = self.status_error(item.url, response)
                errors.append(error)
                self.report_error(self.console, error)

            # Extract links before running response code, which may consume
            # a streaming response's body.
            links: list[str] = []
            if item.depth < depth:
                if is_html(response):
                    links = extract_html_links(response)
                elif is_xml(response):
                    links = extract_xml_links(response)

            if code is not None:
                code_error = self.run_response_code(
                    code, code_namespace, response, item.url, status
                )
                if code_error is not None:
                    errors.append(code_error)
                    self.report_error(self.console, code_error)

            for href in links:
                linked_url = normalize_url(
                    urljoin(item.url, href), allowed_hosts, client_host
                )

                if linked_url is not None and linked_url not in seen:
                    queue.append(QueueItem(linked_url, item.depth + 1))

        stop_reason = (
            StopReason.MAX_URLS
            if any(item.url not in seen for item in queue)
            else StopReason.NO_MORE_LINKS
        )
        return CrawlResult(count=len(seen), errors=errors, stop_reason=stop_reason)

    def allow_query_variant(
        self,
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

    def status_error(self, url: str, response: Any) -> CrawlError:
        return CrawlError(
            url=url,
            message=f"HTTP {response.status_code} {response.reason_phrase}",
            exc_info=getattr(response, "exc_info", None),
        )

    def run_response_code(
        self,
        code: str,
        namespace: dict[str, Any],
        response: Any,
        url: str,
        status: Any = None,
    ) -> CrawlError | None:
        namespace["response"] = response
        stop = getattr(status, "stop", None)
        start = getattr(status, "start", None)
        if stop is not None:
            stop()
        try:
            with (
                redirect_stdout(PassthroughStream(self.stdout)),
                redirect_stderr(PassthroughStream(self.stderr)),
            ):
                exec(code, namespace, namespace)
        except Exception:
            _exc = sys.exc_info()
            return CrawlError(
                url=url,
                message="Response code raised an exception.",
                exc_info=_exc if _exc[0] is not None else None,
            )
        finally:
            if start is not None:
                start()
        return None

    def report_error(self, console: Console, error: CrawlError) -> None:
        if error.exc_info is None:
            console.print(f"[bold red]URL:[/] {error.url}")
            console.print(f"[red]{error.message}[/]")
            return

        type_, value, traceback = error.exc_info
        notes = [f"URL: {error.url}", error.message]
        added_notes = hasattr(value, "add_note")
        if added_notes:
            for note in notes:
                if note not in getattr(value, "__notes__", ()):
                    value.add_note(note)
        console.print(
            Traceback.from_exception(
                type_,
                value,
                traceback,
                show_locals=False,
                suppress=["django"],
            )
        )
        if not added_notes:
            for note in notes:
                console.print(note)
