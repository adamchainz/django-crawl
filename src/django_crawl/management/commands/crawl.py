from __future__ import annotations

import logging
import sys
from argparse import ArgumentParser, ArgumentTypeError
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
from functools import partial
from types import TracebackType
from typing import Any
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist
from django.core.management.base import CommandError
from django.http.request import validate_host
from django.test import Client, override_settings
from django_rich.management import RichCommand
from justhtml import JustHTML
from rich.console import Console
from rich.traceback import Traceback

DEFAULT_DEPTH = 5
DEFAULT_MAX_PAGES = 1000
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
    exc_info: tuple[type[BaseException], BaseException, TracebackType] | None = None


@dataclass
class CrawlResult:
    count: int
    errors: list[CrawlError]


class SuppressDjangoRequestLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return False


def non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise ArgumentTypeError("must be an integer") from None
    if number < 0:
        raise ArgumentTypeError("must be greater than or equal to 0")
    return number


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise ArgumentTypeError("must be an integer") from None
    if number <= 0:
        raise ArgumentTypeError("must be greater than 0")
    return number


def max_query_variants(value: str) -> int | None:
    if value == "unlimited":
        return None
    return positive_int(value)


def normalize_url(url: str, allowed_hosts: tuple[str, ...] = ()) -> str | None:
    url, _fragment = urldefrag(url)
    parts = urlsplit(url)
    if parts.scheme:
        return None
    if parts.netloc and not validate_host(parts.netloc, allowed_hosts):
        return None
    path = parts.path or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    return urlunsplit(("", "", path, parts.query, ""))


def is_html(response: Any) -> bool:
    return "text/html" in response.headers.get("Content-Type", "")


def pluralize(count: int, singular: str, plural: str) -> str:
    if count == 1:
        return f"1 {singular}"
    return f"{count} {plural}"


@contextmanager
def paused_status(status: Any) -> Iterator[None]:
    stop = getattr(status, "stop", None)
    start = getattr(status, "start", None)
    if stop is not None:
        stop()
    try:
        yield
    finally:
        if start is not None:
            start()


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
            "--max-pages",
            type=positive_int,
            default=DEFAULT_MAX_PAGES,
            help=f"Maximum number of pages to request. Defaults to {DEFAULT_MAX_PAGES}.",
        )
        parser.add_argument(
            "--max-query-variants",
            type=max_query_variants,
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
        start_urls = self.start_urls(options["urls"])
        depth: int = options["depth"]
        max_pages: int = options["max_pages"]
        max_query_variants: int | None = options["max_query_variants"]
        code: str | None = options["code"]

        client = Client(HTTP_HOST=TESTSERVER)
        self.configure_client(client, options)

        django_request_logger = logging.getLogger("django.request")
        log_filter = SuppressDjangoRequestLogs()
        status: Any = (
            self.console.status("Crawling site…")
            if self.console.is_terminal
            else nullcontext()
        )
        with ExitStack() as stack:
            http_host = client.defaults.get("HTTP_HOST")
            if (
                http_host
                and http_host != TESTSERVER
                and http_host not in settings.ALLOWED_HOSTS
                and "*" not in settings.ALLOWED_HOSTS
            ):
                stack.enter_context(
                    override_settings(
                        ALLOWED_HOSTS=[*settings.ALLOWED_HOSTS, http_host]
                    )
                )
            django_request_logger.addFilter(log_filter)
            stack.callback(django_request_logger.removeFilter, log_filter)
            stack.enter_context(status)
            allowed_hosts = (
                (http_host, *settings.ALLOWED_HOSTS)
                if http_host
                else tuple(settings.ALLOWED_HOSTS)
            )
            result = self.crawl(
                client,
                start_urls,
                depth,
                max_pages,
                max_query_variants,
                code,
                status,
                allowed_hosts,
            )

        if result.errors:
            self.console.print(
                f"Found {pluralize(len(result.errors), 'error', 'errors')}."
            )
            self.console.print(f"Crawled {pluralize(result.count, 'URL', 'URLs')}.")
            raise SystemExit(1)
        self.console.print(f"Crawled {pluralize(result.count, 'URL', 'URLs')}.")

    def start_urls(self, urls: list[str]) -> list[str]:
        if urls:
            return self.normalize_start_urls(urls)
        return ["/"]

    def normalize_start_urls(self, urls: list[str]) -> list[str]:
        normalized = []
        for url in urls:
            normalized_url = normalize_url(url)
            if normalized_url is None:
                raise CommandError(f"Start URL must be an internal path: {url!r}.")
            normalized.append(normalized_url)
        return normalized

    def configure_client(self, client: Client, options: dict[str, Any]) -> None:
        namespace = self.setup_namespace(client)

        login = options["login"]
        if login is not None:
            self.login_user(client, login)
        elif not options["no_login"]:
            self.login_superuser(client)

        for code in options["setup_code"]:
            exec(code, namespace, namespace)

    def setup_namespace(self, client: Client) -> dict[str, Any]:
        namespace = {
            "client": client,
            "settings": settings,
            "get_user_model": get_user_model,
        }
        if auth_installed():
            namespace["User"] = get_user_model()
        return namespace

    def login_superuser(self, client: Client) -> None:
        if not auth_installed():
            return
        User = get_user_model()
        user = (
            User._default_manager.filter(is_active=True, is_superuser=True)
            .order_by(User.USERNAME_FIELD)
            .first()
        )
        if user is not None:
            client.force_login(user)

    def login_user(self, client: Client, username_or_email: str) -> None:
        if not auth_installed():
            raise CommandError(
                "Cannot use --login: 'django.contrib.auth' is not installed."
            )
        User = get_user_model()
        query = {User.USERNAME_FIELD: username_or_email}
        try:
            user = User._default_manager.get(**query)
        except ObjectDoesNotExist:
            user = self.get_user_by_email(User, username_or_email)
        client.force_login(user)

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

    def crawl(
        self,
        client: Client,
        start_urls: list[str],
        depth: int,
        max_pages: int,
        max_query_variants: int | None,
        code: str | None,
        status: Any = None,
        allowed_hosts: tuple[str, ...] = (),
    ) -> CrawlResult:
        queue = deque(QueueItem(url, 0) for url in start_urls)
        seen: set[str] = set()
        query_variants: dict[str, set[str]] = {}
        errors: list[CrawlError] = []
        code_namespace: dict[str, Any] = {}

        while queue and len(seen) < max_pages:
            item = queue.popleft()
            if item.url in seen:
                continue
            if not self.allow_query_variant(
                item.url, query_variants, max_query_variants
            ):
                continue
            seen.add(item.url)

            try:
                with paused_status(status):
                    response = client.get(item.url)
            except Exception:
                error = CrawlError(
                    url=item.url,
                    message="HTTP 500 Internal Server Error",
                    exc_info=sys.exc_info(),
                )
                errors.append(error)
                with paused_status(status):
                    self.report_error(self.console, error)
                continue

            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if location:
                    linked_url = normalize_url(
                        urljoin(item.url, location), allowed_hosts
                    )
                    if linked_url is not None and linked_url not in seen:
                        queue.append(QueueItem(linked_url, item.depth))
                continue
            if response.status_code >= 400:
                error = self.status_error(item.url, response)
                errors.append(error)
                with paused_status(status):
                    self.report_error(self.console, error)

            if code is not None:
                with paused_status(status):
                    error = self.run_response_code(
                        code, code_namespace, response, item.url
                    )
                if error is not None:
                    errors.append(error)
                    with paused_status(status):
                        self.report_error(self.console, error)

            if item.depth >= depth or not is_html(response):
                continue

            for href in self.extract_links(response):
                linked_url = normalize_url(urljoin(item.url, href), allowed_hosts)
                if linked_url is not None and linked_url not in seen:
                    queue.append(QueueItem(linked_url, item.depth + 1))

        return CrawlResult(count=len(seen), errors=errors)

    def allow_query_variant(
        self,
        url: str,
        query_variants: dict[str, set[str]],
        max_query_variants: int | None,
    ) -> bool:
        if max_query_variants is None:
            return True
        parts = urlsplit(url)
        variants = query_variants.setdefault(parts.path, set())
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
    ) -> CrawlError | None:
        namespace["response"] = response
        try:
            with (
                redirect_stdout(PassthroughStream(self.stdout)),
                redirect_stderr(PassthroughStream(self.stderr)),
            ):
                exec(code, namespace, namespace)
        except Exception:
            return CrawlError(
                url=url,
                message="Response code raised an exception.",
                exc_info=sys.exc_info(),
            )
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

    def extract_links(self, response: Any) -> list[str]:
        content = response.content.decode(response.charset or "utf-8", errors="replace")
        document = JustHTML(content, sanitize=False)
        return [anchor.attrs["href"] for anchor in document.query("a[href]")]
