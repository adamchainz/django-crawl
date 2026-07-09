from __future__ import annotations

import sys
from io import StringIO
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from rich.console import Console

from django_crawl.management.commands import crawl
from django_crawl.management.commands.crawl import Command
from tests.utils import run_command


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

        assert out == "/target/\nCrawled 2 URLs.\n"
        assert err == ""
        assert returncode == 0

    def test_crawl_ignores_external_redirect_target(self):
        out, err, returncode = run_command(
            "crawl", "/redirect-external/", "--depth", "0"
        )

        assert out == "Crawled 1 URL.\n"
        assert err == ""
        assert returncode == 0

    def test_crawl_handles_redirect_without_location(self):
        out, err, returncode = run_command(
            "crawl", "/redirect-no-location/", "--depth", "0"
        )

        assert out == "Crawled 1 URL.\n"
        assert err == ""
        assert returncode == 0

    def test_crawl_follows_relative_href(self):
        out, err, returncode = run_command(
            "crawl",
            "/nested/page/",
            "--depth",
            "1",
            "-c",
            "print(response.wsgi_request.path)",
        )

        assert out == "/nested/page/\n/target/\nCrawled 2 URLs.\n"
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
    def test_pluralize(self):
        assert crawl.pluralize(0, "URL", "URLs") == "0 URLs"
        assert crawl.pluralize(1, "URL", "URLs") == "1 URL"
        assert crawl.pluralize(2, "URL", "URLs") == "2 URLs"
        assert crawl.pluralize(0, "error", "errors") == "0 errors"
        assert crawl.pluralize(1, "error", "errors") == "1 error"
        assert crawl.pluralize(2, "error", "errors") == "2 errors"


class URLTests(TestCase):
    def test_normalize_url_accepts_relative_urls(self):
        assert crawl.normalize_url("relative/?x=1#fragment") == "/relative/?x=1"

    def test_normalize_url_accepts_protocol_relative_urls(self):
        assert (
            crawl.normalize_url("//example.com/foo/?x=1", ("example.com",))
            == "/foo/?x=1"
        )

    def test_normalize_url_rejects_protocol_relative_urls_to_other_hosts(self):
        assert crawl.normalize_url("//other.example.com/foo/", ("example.com",)) is None

    def test_normalize_url_rejects_urls_with_scheme(self):
        assert crawl.normalize_url("https://example.com/foo/") is None

    def test_start_urls_default_to_root(self):
        assert Command().start_urls([]) == ["/"]


class IsHtmlTests(TestCase):
    def test_is_html(self):
        def response(content_type):
            return type("R", (), {"headers": {"Content-Type": content_type}})()

        assert crawl.is_html(response("text/html"))
        assert crawl.is_html(response("text/html; charset=utf-8"))
        assert crawl.is_html(response("  Text/HTML ; charset=utf-8"))
        assert not crawl.is_html(response("text/html-fragment"))
        assert not crawl.is_html(response("application/xhtml+xml"))
        assert not crawl.is_html(response("text/plain"))
        assert not crawl.is_html(response(""))


class HTMLTests(TestCase):
    def test_extract_links_returns_hrefs_and_skips_anchors_without_href(self):
        command = Command()

        class Response:
            content = b'<a href="/one/">one</a><a>no href</a><a href="two/">two</a>'
            charset = "utf-8"

        assert command.extract_links(Response()) == ["/one/", "two/"]


class OutputTests(TestCase):
    def test_passthrough_stream_flushes_wrapped_output(self):
        class Output:
            def __init__(self) -> None:
                self.value = ""
                self.flushed = False

            def write(self, text: str, ending: str = "\n") -> None:
                self.value += f"{text}{ending}"

            def flush(self) -> None:
                self.flushed = True

        output = Output()
        raw = crawl.PassthroughStream(output)

        assert raw.write("hello") == 5
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

        if sys.version_info >= (3, 11):
            assert exception.__notes__ == [
                "URL: /bad/",
                "HTTP 500 Internal Server Error",
            ]
        else:
            output = err.getvalue()
            assert output.count("URL: /bad/") == 2
            assert output.count("HTTP 500 Internal Server Error") == 2


class LoginTests(TestCase):
    def test_setup_namespace_without_auth_installed(self):
        command = Command()
        client = Client()

        with override_settings(INSTALLED_APPS=["django_crawl"]):
            namespace = command.setup_namespace(client)

        assert namespace == {
            "client": client,
            "settings": crawl.settings,
            "get_user_model": crawl.get_user_model,
        }

    def test_configure_client_logs_in_default_superuser(self):
        command = Command()
        client = Client()
        options = {
            "setup_code": [],
            "login": None,
            "no_login": False,
        }

        with patch.object(command, "login_superuser") as login_superuser:
            command.configure_client(client, options)

        login_superuser.assert_called_once_with(client)

    def test_configure_client_skips_login_with_no_login(self):
        command = Command()
        client = Client()
        options = {
            "setup_code": [],
            "login": None,
            "no_login": True,
        }

        with patch.object(command, "login_superuser") as login_superuser:
            command.configure_client(client, options)

        login_superuser.assert_not_called()

    def test_configure_client_logs_in_explicit_user(self):
        command = Command()
        client = Client()
        options = {
            "setup_code": [],
            "login": "test@example.com",
            "no_login": False,
        }

        with patch.object(command, "login_user") as login_user:
            command.configure_client(client, options)

        login_user.assert_called_once_with(client, "test@example.com")

    def test_login_and_no_login_are_mutually_exclusive(self):
        _out, err, returncode = run_command("crawl", "--login", "alice", "--no-login")
        assert returncode != 0
        assert "not allowed with" in err or "mutually exclusive" in err

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

    def test_login_superuser_ignores_missing_user(self):
        command = Command()
        client = Client()
        force_login_calls = []

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

        with (
            patch.object(crawl, "get_user_model", return_value=User),
            patch.object(client, "force_login", force_login_calls.append),
        ):
            command.login_superuser(client)

        assert force_login_calls == []

    def test_login_superuser_without_auth_installed(self):
        command = Command()
        client = Client()
        force_login_calls = []

        with (
            override_settings(INSTALLED_APPS=["django_crawl"]),
            patch.object(client, "force_login", force_login_calls.append),
        ):
            command.login_superuser(client)

        assert force_login_calls == []

    def test_login_user_without_auth_installed_errors(self):
        command = Command()
        client = Client()

        with (
            override_settings(INSTALLED_APPS=["django_crawl"]),
            self.assertRaisesRegex(
                crawl.CommandError,
                r"'django\.contrib\.auth' is not installed",
            ),
        ):
            command.login_user(client, "alice")

    def test_login_user_by_username(self):
        command = Command()
        client = Client()
        user = object()
        force_login_calls = []

        class Manager:
            def get(self, **kwargs):
                assert kwargs == {"username": "alice"}
                return user

        class User:
            USERNAME_FIELD = "username"
            _default_manager = Manager()

        with (
            patch.object(crawl, "get_user_model", return_value=User),
            patch.object(client, "force_login", force_login_calls.append),
        ):
            command.login_user(client, "alice")

        assert force_login_calls == [user]

    def test_login_user_missing_user_errors(self):
        command = Command()

        class Manager:
            def get(self, **kwargs):
                raise crawl.ObjectDoesNotExist

        class User:
            USERNAME_FIELD = "email"
            _default_manager = Manager()

        with patch.object(crawl, "get_user_model", return_value=User):
            with self.assertRaisesRegex(
                crawl.CommandError, "User 'missing@example.com' does not exist"
            ):
                command.login_user(Client(), "missing@example.com")

    def test_login_user_missing_email_field_errors(self):
        command = Command()

        class Meta:
            def get_field(self, name):
                raise crawl.FieldDoesNotExist

        class Manager:
            def get(self, **kwargs):
                raise crawl.ObjectDoesNotExist

        class User:
            USERNAME_FIELD = "username"
            _meta = Meta()
            _default_manager = Manager()

        with patch.object(crawl, "get_user_model", return_value=User):
            with self.assertRaisesRegex(
                crawl.CommandError, "User 'missing@example.com' does not exist"
            ):
                command.login_user(Client(), "missing@example.com")

    def test_login_user_missing_email_user_errors(self):
        command = Command()

        class Meta:
            def get_field(self, name):
                assert name == "email"

        class Manager:
            def get(self, **kwargs):
                raise crawl.ObjectDoesNotExist

        class User:
            USERNAME_FIELD = "username"
            _meta = Meta()
            _default_manager = Manager()

        with patch.object(crawl, "get_user_model", return_value=User):
            with self.assertRaisesRegex(
                crawl.CommandError, "User 'missing@example.com' does not exist"
            ):
                command.login_user(Client(), "missing@example.com")

    def test_login_user_by_email(self):
        command = Command()
        client = Client()
        user = object()
        force_login_calls = []

        class Meta:
            def get_field(self, name):
                assert name == "email"

        class Manager:
            def get(self, **kwargs):
                if kwargs == {"username": "test@example.com"}:
                    raise crawl.ObjectDoesNotExist
                assert kwargs == {"email": "test@example.com"}
                return user

        class User:
            USERNAME_FIELD = "username"
            _meta = Meta()
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

        result = command.crawl(client, ["/ok/", "/ok/"], 0, 2, 10, None)

        assert result.count == 1
        assert result.errors == []

    def test_query_variants_are_limited_per_path(self):
        command = Command()
        client = Client()

        result = command.crawl(client, ["/query-variants/"], 1, 10, 2, None)

        assert result.count == 2
        assert result.errors == []

    def test_query_variant_limit_can_be_disabled(self):
        command = Command()
        client = Client()

        result = command.crawl(client, ["/query-variants/"], 1, 10, None, None)

        assert result.count == 4
        assert result.errors == []

    def test_seen_query_variant_is_allowed_after_limit(self):
        command = Command()
        query_variants = {"/path/": {"a=1"}}

        assert command.allow_query_variant("/path/?a=1", query_variants, 1)
        assert not command.allow_query_variant("/path/?a=2", query_variants, 1)

    def test_client_request_exception_is_reported(self):
        command = Command()
        client = Client()

        def get(*args, **kwargs):
            raise RuntimeError("boom")

        with patch.object(client, "get", get):
            result = command.crawl(client, ["/"], 0, 1, 10, None)

        assert result.count == 1
        assert len(result.errors) == 1
        assert result.errors[0].url == "/"
        assert result.errors[0].message == "HTTP 500 Internal Server Error"
        assert result.errors[0].exc_info is not None
