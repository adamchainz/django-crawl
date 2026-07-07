from __future__ import annotations

from argparse import ArgumentTypeError
from dataclasses import dataclass
from io import StringIO
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from rich.console import Console

from django_crawl.management.commands import crawl
from django_crawl.management.commands.crawl import Command
from tests.utils import run_command


@dataclass
class AnchorAttrs:
    attrs: dict[str, object]


@dataclass
class AnchorAttributes:
    attributes: dict[str, object]


class AnchorGet:
    def __init__(self, href: object) -> None:
        self.href = href

    def get(self, name: str) -> object:
        assert name == "href"
        return self.href


class CrawlCommandTests(TestCase):
    def test_depth_zero_does_not_follow_links(self):
        out, err, returncode = run_command("crawl", "/ok/", "--depth", "0")

        assert out == "Crawled 1 URL.\n"
        assert err == ""
        assert returncode == 0

    def test_crawl_reports_all_status_errors_and_tracebacks(self):
        out, err, returncode = run_command("crawl", "/", "--depth", "1")

        assert returncode == 1
        assert "Crawled 5 URLs" in out
        assert "URL: /bad/" in out
        assert "HTTP 400 Bad Request" in out
        assert "URL: /not-found/" in out
        assert "HTTP 404 Not Found" in out
        assert "URL: /server-error/" in out
        assert "HTTP 500 Internal Server Error" in out
        assert "ValueError: broken" in out
        assert "Found 3 errors." in out
        assert err == ""

    def test_crawl_follows_redirects(self):
        out, err, returncode = run_command(
            "crawl",
            "/redirect/",
            "--depth",
            "0",
            "-c",
            "print(response.wsgi_request.path)",
        )

        assert out == "/target/\nCrawled 1 URL.\n"
        assert err == ""
        assert returncode == 0

    def test_crawl_runs_code_for_every_response(self):
        out, err, returncode = run_command(
            "crawl",
            "/ok/",
            "--depth",
            "1",
            "-c",
            "print(response.status_code, response.wsgi_request.path)",
        )

        assert out == "200 /ok/\n200 /deep/\nCrawled 2 URLs.\n"
        assert err == ""
        assert returncode == 0

    def test_crawl_reports_response_code_exceptions(self):
        out, err, returncode = run_command(
            "crawl",
            "/",
            "--depth",
            "0",
            "-c",
            "raise ValueError('check failed')",
        )

        assert returncode == 1
        assert "Crawled 1 URL" in out
        assert "Response code raised an exception." in out
        assert "ValueError: check failed" in out
        assert "Found 1 error." in out
        assert err == ""

    def test_crawl_setup_code_can_configure_client(self):
        out, err, returncode = run_command(
            "crawl",
            "/needs-setup/",
            "--depth",
            "0",
            "--setup-code",
            "client.defaults['HTTP_X_SETUP'] = '1'",
        )

        assert out == "Crawled 1 URL.\n"
        assert err == ""
        assert returncode == 0

    def test_crawl_setup_code_can_configure_host(self):
        out, err, returncode = run_command(
            "crawl",
            "/needs-host/",
            "--depth",
            "0",
            "--setup-code",
            "client.defaults['HTTP_HOST'] = 'docs.example.com'",
        )

        assert out == "Crawled 1 URL.\n"
        assert err == ""
        assert returncode == 0

    def test_crawl_starts_at_root_by_default(self):
        out, err, returncode = run_command(
            "crawl",
            "--depth",
            "0",
            "-c",
            "print(response.wsgi_request.path)",
        )

        assert out == "/\nCrawled 1 URL.\n"
        assert err == ""
        assert returncode == 0

    def test_external_start_urls_are_rejected(self):
        out, err, returncode = run_command("crawl", "https://example.com/")

        assert out == ""
        assert "Start URL must be an internal path" in err
        assert returncode == 1

    def test_setup_negative_paths_report_errors(self):
        out, err, returncode = run_command("crawl", "/needs-setup/", "--depth", "0")

        assert "HTTP 403 Forbidden" in out
        assert "Found 1 error." in out
        assert "Crawled 1 URL." in out
        assert err == ""
        assert returncode == 1

    def test_host_negative_path_reports_error(self):
        out, err, returncode = run_command("crawl", "/needs-host/", "--depth", "0")

        assert "HTTP 403 Forbidden" in out
        assert "Found 1 error." in out
        assert "Crawled 1 URL." in out
        assert err == ""
        assert returncode == 1

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_wildcard_allowed_hosts_skips_override(self):
        out, err, returncode = run_command("crawl", "/ok/", "--depth", "0")

        assert out == "Crawled 1 URL.\n"
        assert err == ""
        assert returncode == 0


class ParserTests(TestCase):
    def test_pluralize_url(self):
        assert crawl.pluralize_url(0) == "0 URLs"
        assert crawl.pluralize_url(1) == "1 URL"
        assert crawl.pluralize_url(2) == "2 URLs"

    def test_pluralize_error(self):
        assert crawl.pluralize_error(0) == "0 errors"
        assert crawl.pluralize_error(1) == "1 error"
        assert crawl.pluralize_error(2) == "2 errors"

    def test_int_argument_parsers_reject_invalid_values(self):
        cases = [
            (crawl.non_negative_int, "x", "must be an integer"),
            (crawl.non_negative_int, "-1", "must be greater than or equal to 0"),
            (crawl.positive_int, "x", "must be an integer"),
            (crawl.positive_int, "0", "must be greater than 0"),
        ]
        for function, value, message in cases:
            with self.subTest(function=function, value=value):
                with self.assertRaisesRegex(ArgumentTypeError, message):
                    function(value)

    def test_positive_int_accepts_positive_values(self):
        assert crawl.positive_int("1") == 1


class URLTests(TestCase):
    def test_normalize_url_accepts_relative_urls(self):
        assert crawl.normalize_url("relative/?x=1#fragment") == "/relative/?x=1"

    def test_response_url_falls_back_without_request(self):
        assert crawl.response_url(object(), "/fallback/") == "/fallback/"

    def test_start_urls_default_to_root(self):
        assert Command().start_urls([]) == ["/"]


class HTMLTests(TestCase):
    def test_anchor_href(self):
        cases = [
            (AnchorAttrs({"href": "/attrs/"}), "/attrs/"),
            (AnchorAttrs({"href": 1}), None),
            (AnchorAttributes({"href": "/attributes/"}), "/attributes/"),
            (AnchorAttributes({"href": 1}), None),
            (AnchorGet("/get/"), "/get/"),
            (AnchorGet(1), None),
            (object(), None),
        ]
        for anchor, href in cases:
            with self.subTest(anchor=anchor):
                assert crawl.anchor_href(anchor) == href

    def test_extract_links_ignores_non_string_hrefs(self):
        command = Command()

        class Document:
            def query(self, selector):
                assert selector == "a[href]"
                return [object()]

        class Response:
            content = b""
            charset = "utf-8"

        with (
            patch.object(crawl, "JustHTML", lambda *args, **kwargs: Document()),
            patch.object(crawl, "anchor_href", lambda anchor: None),
        ):
            assert command.extract_links(Response()) == []


class OutputTests(TestCase):
    def test_raw_output_flushes_wrapped_output(self):
        class Output:
            def __init__(self) -> None:
                self.value = ""
                self.flushed = False

            def write(self, text: str, ending: str = "\n") -> None:
                self.value += f"{text}{ending}"

            def flush(self) -> None:
                self.flushed = True

        output = Output()
        raw = crawl.RawOutput(output)

        raw.write("hello")
        raw.flush()

        assert output.value == "hello"
        assert output.flushed

    def test_report_error_without_traceback(self):
        err = StringIO()
        command = Command()
        console = Console(file=err, force_terminal=False)

        command.report_error(console, crawl.CrawlError("/", "HTTP 404 Not Found"))

        assert "URL: /" in err.getvalue()
        assert "HTTP 404 Not Found" in err.getvalue()

    def test_report_error_does_not_duplicate_exception_notes(self):
        err = StringIO()
        command = Command()
        console = Console(file=err, force_terminal=False)
        exception = ValueError("bad")
        error = crawl.CrawlError(
            "/bad/",
            "HTTP 500 Internal Server Error",
            (ValueError, exception, exception.__traceback__),
        )

        command.report_error(console, error)
        command.report_error(console, error)

        assert exception.__notes__ == [
            "URL: /bad/",
            "HTTP 500 Internal Server Error",
        ]


class LoginTests(TestCase):
    def test_setup_namespace_ignores_unconfigured_user_model(self):
        command = Command()

        def get_user_model():
            raise LookupError

        client = Client()

        with patch.object(crawl, "get_user_model", get_user_model):
            assert command.setup_namespace(client) == {
                "client": client,
                "settings": crawl.settings,
                "get_user_model": get_user_model,
            }

    def test_configure_client_runs_login_options(self):
        command = Command()
        client = Client()
        calls = []
        options = {
            "setup_code": [],
            "login_superuser": True,
            "login_user": "test@example.com",
        }

        with (
            patch.object(
                command, "login_superuser", lambda client: calls.append("superuser")
            ),
            patch.object(
                command, "login_user", lambda client, username: calls.append(username)
            ),
        ):
            command.configure_client(client, options)

        assert calls == ["superuser", "test@example.com"]

    def test_login_superuser(self):
        command = Command()
        client = Client()
        user = object()
        force_login_calls = []

        class QuerySet:
            def filter(self, **kwargs):
                assert kwargs == {"is_active": True, "is_superuser": True}
                return self

            def order_by(self, field):
                assert field == "username"
                return self

            def first(self):
                return user

        class User:
            USERNAME_FIELD = "username"
            _default_manager = QuerySet()

        with (
            patch.object(crawl, "get_user_model", return_value=User),
            patch.object(client, "force_login", force_login_calls.append),
        ):
            command.login_superuser(client)

        assert force_login_calls == [user]

    def test_login_superuser_errors_without_user(self):
        command = Command()

        class QuerySet:
            def filter(self, **kwargs):
                return self

            def order_by(self, field):
                return self

            def first(self):
                return None

        class User:
            USERNAME_FIELD = "username"
            _default_manager = QuerySet()

        with patch.object(crawl, "get_user_model", return_value=User):
            with self.assertRaisesRegex(CommandError, "No active superuser found"):
                command.login_superuser(Client())

    def test_login_user(self):
        command = Command()
        client = Client()
        user = object()
        force_login_calls = []

        class Manager:
            def get(self, **kwargs):
                assert kwargs == {"email": "test@example.com"}
                return user

        class User:
            USERNAME_FIELD = "email"
            _default_manager = Manager()

        with (
            patch.object(crawl, "get_user_model", return_value=User),
            patch.object(client, "force_login", force_login_calls.append),
        ):
            command.login_user(client, "test@example.com")

        assert force_login_calls == [user]


class CrawlInternalsTests(TestCase):
    def test_paused_status_stops_and_restarts_status(self):
        calls = []

        class Status:
            def stop(self):
                calls.append("stop")

            def start(self):
                calls.append("start")

        with crawl.paused_status(Status()):
            calls.append("body")

        assert calls == ["stop", "body", "start"]

    def test_paused_status_allows_none(self):
        with crawl.paused_status(None):
            pass

    def test_duplicate_urls_are_skipped(self):
        command = Command()
        client = Client()

        result = command.crawl(client, ["/ok/", "/ok/"], 0, 2, None)

        assert result.count == 1
        assert result.errors == []

    def test_client_request_exception_is_reported(self):
        command = Command()
        client = Client()

        def get(*args, **kwargs):
            raise RuntimeError("boom")

        with patch.object(client, "get", get):
            result = command.crawl(client, ["/"], 0, 1, None)

        assert result.count == 1
        assert len(result.errors) == 1
        assert result.errors[0].url == "/"
        assert result.errors[0].message == "HTTP 500 Internal Server Error"
        assert result.errors[0].exc_info is not None
