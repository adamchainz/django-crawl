from __future__ import annotations

import logging
import sys
import threading
import time
import warnings
from contextlib import nullcontext
from io import StringIO
from unittest.mock import PropertyMock, patch

import pytest
from django.core.exceptions import MultipleObjectsReturned
from django.core.management.base import OutputWrapper
from django.test import Client, TestCase, override_settings
from rich.console import Console

from django_crawl.management.commands import crawl
from django_crawl.management.commands.crawl import Command, CrawlResult, StopReason
from tests.utils import run_command


class CrawlCommandTests(TestCase):
    def test_depth_zero_does_not_follow_links(self):
        out, err, returncode = run_command("crawl", "/ok/", "--depth", "0")

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "🦋 Crawled 1 URL, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
        assert err == ""
        assert returncode == 0

    def test_crawl_reports_all_status_errors_and_tracebacks(self):
        out, err, returncode = run_command("crawl", "/", "--depth", "1")

        assert returncode == 1
        assert "🐛 Crawling up to 1000 URLs\n" in out
        assert "URL: /bad/" in out
        assert "HTTP 400 Bad Request" in out
        assert "URL: /not-found/" in out
        assert "HTTP 404 Not Found" in out
        assert "URL: /server-error/" in out
        assert "HTTP 500 Internal Server Error" in out
        assert "ValueError: broken" in out
        assert (
            "🦋 Crawled 5 URLs, encountered 3 errors, "
            "stopped due to finding no more links."
        ) in out
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

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "/target/\n"
            "🦋 Crawled 2 URLs, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
        assert err == ""
        assert returncode == 0

    def test_crawl_ignores_external_redirect_target(self):
        out, err, returncode = run_command(
            "crawl", "/redirect-external/", "--depth", "0"
        )

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "🦋 Crawled 1 URL, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
        assert err == ""
        assert returncode == 0

    def test_crawl_stops_on_redirect_loop(self):
        out, err, returncode = run_command("crawl", "/redirect-loop-a/", "--depth", "0")

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "🦋 Crawled 2 URLs, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
        assert err == ""
        assert returncode == 0

    def test_crawl_handles_redirect_without_location(self):
        out, err, returncode = run_command(
            "crawl", "/redirect-no-location/", "--depth", "0"
        )

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "🦋 Crawled 1 URL, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
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

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "/nested/page/\n/target/\n"
            "🦋 Crawled 2 URLs, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
        assert err == ""
        assert returncode == 0

    def test_crawl_follows_links_from_streaming_response(self):
        out, err, returncode = run_command(
            "crawl",
            "/streaming/",
            "--depth",
            "1",
            "-c",
            "print(response.wsgi_request.path)",
        )

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "/streaming/\n/ok/\n"
            "🦋 Crawled 2 URLs, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
        assert err == ""
        assert returncode == 0

    def test_crawl_follows_streaming_links_when_code_reads_body(self):
        out, err, returncode = run_command(
            "crawl",
            "/streaming/",
            "--depth",
            "1",
            "-c",
            "response.getvalue(); print(response.wsgi_request.path)",
        )

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "/streaming/\n/ok/\n"
            "🦋 Crawled 2 URLs, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
        assert err == ""
        assert returncode == 0

    def test_crawl_follows_sitemap_urls(self):
        out, err, returncode = run_command(
            "crawl",
            "/sitemap.xml",
            "--depth",
            "1",
            "-c",
            "print(response.wsgi_request.path)",
        )

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "/sitemap.xml\n/ok/\n/target/\n"
            "🦋 Crawled 3 URLs, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
        assert err == ""
        assert returncode == 0

    def test_crawl_follows_feed_urls(self):
        out, err, returncode = run_command(
            "crawl",
            "/feed.rss",
            "--depth",
            "1",
            "-c",
            "print(response.wsgi_request.path)",
        )

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "/feed.rss\n/ok/\n/target/\n"
            "🦋 Crawled 3 URLs, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
        assert err == ""
        assert returncode == 0

    def test_crawl_skips_extraction_for_plain_text(self):
        out, err, returncode = run_command("crawl", "/plain/", "--depth", "1")

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "🦋 Crawled 1 URL, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
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

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "200 /ok/\n200 /deep/\n"
            "🦋 Crawled 2 URLs, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
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
        assert "🐛 Crawling up to 1000 URLs\n" in out
        assert "Response code raised an exception." in out
        assert "ValueError: check failed" in out
        assert (
            "🦋 Crawled 1 URL, encountered 1 error, "
            "stopped due to finding no more links."
        ) in out
        assert err == ""

    def test_crawl_code_shares_setup_namespace(self):
        out, err, returncode = run_command(
            "crawl",
            "/ok/",
            "--depth",
            "0",
            "--setup-code",
            "count = 0",
            "-c",
            "count += 1; print(count, client is not None)",
        )

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "1 True\n"
            "🦋 Crawled 1 URL, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
        assert err == ""
        assert returncode == 0

    def test_crawl_setup_code_can_configure_client(self):
        out, err, returncode = run_command(
            "crawl",
            "/needs-setup/",
            "--depth",
            "0",
            "--setup-code",
            "client.defaults['HTTP_X_SETUP'] = '1'",
        )

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "🦋 Crawled 1 URL, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
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

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "🦋 Crawled 1 URL, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
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

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "/\n"
            "🦋 Crawled 1 URL, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
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
        assert (
            "🦋 Crawled 1 URL, encountered 1 error, "
            "stopped due to finding no more links."
        ) in out
        assert err == ""
        assert returncode == 1

    def test_host_negative_path_reports_error(self):
        out, err, returncode = run_command("crawl", "/needs-host/", "--depth", "0")

        assert "HTTP 403 Forbidden" in out
        assert (
            "🦋 Crawled 1 URL, encountered 1 error, "
            "stopped due to finding no more links."
        ) in out
        assert err == ""
        assert returncode == 1

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_wildcard_allowed_hosts_skips_override(self):
        out, err, returncode = run_command("crawl", "/ok/", "--depth", "0")

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "🦋 Crawled 1 URL, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
        assert err == ""
        assert returncode == 0

    @override_settings(ALLOWED_HOSTS=["example.com"])
    def test_testserver_added_to_allowed_hosts_when_not_present(self):
        out, err, returncode = run_command("crawl", "/needs-host/", "--depth", "0")

        # /needs-host/ calls request.get_host(). If testserver is not in
        # ALLOWED_HOSTS, Django raises DisallowedHost → HTTP 400. With the
        # fix, testserver is added, so get_host() succeeds and the view
        # returns its normal 403 (wrong host for that view).
        assert "HTTP 403 Forbidden" in out
        assert returncode == 1

    def test_verbose_crawl_prints_every_url(self):
        out, err, returncode = run_command(
            "crawl", "/ok/", "--depth", "0", "--verbosity", "2"
        )

        assert out == (
            "🐛 Crawling up to 1000 URLs\n"
            "/ok/\n"
            "🦋 Crawled 1 URL, encountered 0 errors, "
            "stopped due to finding no more links.\n"
        )
        assert err == ""
        assert returncode == 0

    def test_start_message_includes_max_urls(self):
        out, _err, returncode = run_command(
            "crawl", "/ok/", "--depth", "0", "--max-urls", "5"
        )

        assert returncode == 0
        lines = out.splitlines()
        assert lines[0] == "🐛 Crawling up to 5 URLs"

    def test_start_message_includes_logged_in_user(self):
        class FakeUser:
            def __str__(self) -> str:
                return "alice"

        user = FakeUser()

        with (
            patch.object(Command, "login_superuser", return_value=user),
            patch.object(
                Command,
                "crawl",
                return_value=CrawlResult(0, [], StopReason.NO_MORE_LINKS),
            ),
        ):
            out, _err, returncode = run_command("crawl", "/ok/", "--depth", "0")

        assert returncode == 0
        lines = out.splitlines()
        assert lines[0] == "🐛 Crawling up to 1000 URLs, logged in as alice"

    def test_stops_at_max_urls_limit(self):
        out, _err, returncode = run_command(
            "crawl", "/", "--depth", "5", "--max-urls", "1"
        )

        assert returncode == 0
        lines = out.splitlines()
        assert lines[-1] == (
            "🦋 Crawled 1 URL, encountered 0 errors, "
            "stopped due to reaching max URL limit of 1."
        )


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

    def test_normalize_url_accepts_absolute_urls_to_allowed_hosts(self):
        assert (
            crawl.normalize_url("https://example.com/foo/?x=1", ("example.com",))
            == "/foo/?x=1"
        )

    def test_normalize_url_accepts_http_absolute_urls(self):
        assert (
            crawl.normalize_url("http://example.com/foo/", ("example.com",)) == "/foo/"
        )

    def test_normalize_url_rejects_absolute_urls_to_other_hosts(self):
        assert (
            crawl.normalize_url("https://other.example.com/", ("example.com",)) is None
        )

    def test_normalize_url_rejects_absolute_urls_without_allowed_hosts(self):
        assert crawl.normalize_url("https://example.com/foo/") is None

    def test_normalize_url_rejects_non_http_schemes(self):
        assert crawl.normalize_url("mailto:someone@example.com") is None

    def test_start_urls_default_to_root(self):
        assert Command().start_urls([]) == ["/"]


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

    def test_run_response_code_pauses_status_once(self):
        calls = []

        class Status:
            def stop(self):
                calls.append("stop")

            def start(self):
                calls.append("start")

        command = Command()
        command.stdout = OutputWrapper(StringIO())
        command.stderr = OutputWrapper(StringIO())

        error = command.run_response_code(
            "print('a'); print('b')", {}, response=None, url="/", status=Status()
        )

        assert error is None
        assert calls == ["stop", "start"]

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
        options: dict[str, object] = {
            "setup_code": [],
            "login": None,
            "no_login": False,
        }

        with patch.object(command, "login_superuser") as login_superuser:
            command.configure_client(client, options, {})

        login_superuser.assert_called_once_with(client)

    def test_configure_client_skips_login_with_no_login(self):
        command = Command()
        client = Client()
        options: dict[str, object] = {
            "setup_code": [],
            "login": None,
            "no_login": True,
        }

        with patch.object(command, "login_superuser") as login_superuser:
            command.configure_client(client, options, {})

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
            command.configure_client(client, options, {})

        login_user.assert_called_once_with(client, "test@example.com")

    def test_login_and_no_login_are_mutually_exclusive(self):
        _out, err, returncode = run_command("crawl", "--login", "alice", "--no-login")
        assert returncode != 0
        assert "not allowed with" in err or "mutually exclusive" in err

    def test_login_superuser(self):
        command = Command()
        client = Client()
        user = object()
        force_login_calls: list[object] = []

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
        force_login_calls: list[object] = []

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
        force_login_calls: list[object] = []

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
        force_login_calls: list[object] = []

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

        with (
            patch.object(crawl, "get_user_model", return_value=User),
            self.assertRaisesRegex(
                crawl.CommandError, "User 'missing@example.com' does not exist"
            ),
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

        with (
            patch.object(crawl, "get_user_model", return_value=User),
            self.assertRaisesRegex(
                crawl.CommandError, "User 'missing@example.com' does not exist"
            ),
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

        with (
            patch.object(crawl, "get_user_model", return_value=User),
            self.assertRaisesRegex(
                crawl.CommandError, "User 'missing@example.com' does not exist"
            ),
        ):
            command.login_user(Client(), "missing@example.com")

    def test_login_user_multiple_users_errors(self):
        command = Command()

        class Manager:
            def get(self, **kwargs):
                raise MultipleObjectsReturned

        class User:
            USERNAME_FIELD = "username"
            _default_manager = Manager()

        with (
            patch.object(crawl, "get_user_model", return_value=User),
            self.assertRaisesRegex(
                crawl.CommandError, "Multiple users have username 'alice'"
            ),
        ):
            command.login_user(Client(), "alice")

    def test_login_user_multiple_email_users_errors(self):
        command = Command()

        class Meta:
            def get_field(self, name):
                assert name == "email"

        class Manager:
            def get(self, **kwargs):
                if "username" in kwargs:
                    raise crawl.ObjectDoesNotExist
                raise crawl.MultipleObjectsReturned

        class User:
            USERNAME_FIELD = "username"
            _meta = Meta()
            _default_manager = Manager()

        with (
            patch.object(crawl, "get_user_model", return_value=User),
            self.assertRaisesRegex(
                crawl.CommandError, "Multiple users have email 'test@example.com'"
            ),
        ):
            command.login_user(Client(), "test@example.com")

    def test_login_user_by_email(self):
        command = Command()
        client = Client()
        user = object()
        force_login_calls: list[object] = []

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
    def test_duplicate_urls_are_skipped(self):
        command = Command()
        client = Client()

        result = command.crawl(client, ["/ok/", "/ok/"], 0, 2, 10, None)

        assert result.count == 1
        assert result.errors == []

    def test_stop_reason_no_more_links_when_queue_has_only_seen_urls(self):
        command = Command()
        client = Client()

        result = command.crawl(client, ["/ok/", "/deep/"], 1, 2, 10, None)

        assert result.count == 2
        assert result.stop_reason == StopReason.NO_MORE_LINKS

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

    def test_crawl_updates_status_per_url(self):
        command = Command()
        client = Client()
        updates: list[str] = []

        class Status:
            def update(self, text: str) -> None:
                updates.append(text)

        result = command.crawl(
            client, ["/ok/", "/target/"], 0, 10, 10, None, status=Status()
        )

        assert result.count == 2
        assert updates == ["Crawling URL 1…", "Crawling URL 2…"]

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


class StatusAwareStderrTests(TestCase):
    def test_replaces_and_restores_sys_stderr(self):
        real = sys.stderr
        with crawl.status_aware_stderr(None):
            assert sys.stderr is not real
        assert sys.stderr is real

    def test_patches_and_restores_streamhandler_emit(self):
        original = logging.StreamHandler.emit
        with crawl.status_aware_stderr(None):
            assert logging.StreamHandler.emit is not original
        assert logging.StreamHandler.emit is original

    def test_patches_and_restores_showwarning(self):
        original = warnings.showwarning
        with crawl.status_aware_stderr(None):
            assert warnings.showwarning is not original
        assert warnings.showwarning is original

    def test_stderr_write_pauses_status(self):
        calls = []

        class Status:
            def stop(self):
                calls.append("stop")

            def start(self):
                calls.append("start")

        real = sys.stderr
        sys.stderr = StringIO()
        try:
            with crawl.status_aware_stderr(Status()):
                sys.stderr.write("hello")
        finally:
            sys.stderr = real

        assert calls == ["stop", "start"]

    def test_emit_pauses_status(self):
        calls = []

        class Status:
            def stop(self):
                calls.append("stop")

            def start(self):
                calls.append("start")

        handler = logging.StreamHandler(StringIO())
        record = logging.LogRecord("test", logging.WARNING, "", 0, "msg", (), None)
        with crawl.status_aware_stderr(Status()):
            handler.emit(record)

        assert calls == ["stop", "start"]

    def test_showwarning_pauses_status(self):
        calls = []

        class Status:
            def stop(self):
                calls.append("stop")

            def start(self):
                calls.append("start")

        with (
            pytest.warns(UserWarning, match="msg"),
            crawl.status_aware_stderr(Status()),
        ):
            warnings.warn("msg", UserWarning, stacklevel=2)

        assert calls == ["stop", "start"]

    def test_pauses_are_serialized_across_threads(self):
        events = []

        class Status:
            def stop(self):
                events.append("stop")
                time.sleep(0.001)

            def start(self):
                time.sleep(0.001)
                events.append("start")

        real = sys.stderr
        sys.stderr = StringIO()
        try:
            with crawl.status_aware_stderr(Status()):

                def write():
                    for _ in range(10):
                        sys.stderr.write("x")

                threads = [threading.Thread(target=write) for _ in range(10)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
        finally:
            sys.stderr = real

        assert events == ["stop", "start"] * 100

    def test_pausing_guard_prevents_double_pause(self):
        calls = []

        class Status:
            def stop(self):
                calls.append("stop")

            def start(self):
                calls.append("start")

        real = sys.stderr
        sys.stderr = StringIO()
        try:
            with crawl.status_aware_stderr(Status()):
                handler = logging.StreamHandler(sys.stderr)
                record = logging.LogRecord("t", logging.WARNING, "", 0, "m", (), None)
                handler.emit(record)
        finally:
            sys.stderr = real

        assert calls == ["stop", "start"]

    def test_stream_flush_delegates_to_real_stderr(self):
        flushed = []

        class FakeStream:
            def flush(self) -> None:
                flushed.append(True)

            def write(self, data: str) -> int:  # pragma: no cover
                return len(data)

        real = sys.stderr
        sys.stderr = FakeStream()
        try:
            with crawl.status_aware_stderr(None):
                sys.stderr.flush()
        finally:
            sys.stderr = real

        assert flushed == [True]

    def test_stream_proxies_attributes_to_real_stderr(self):
        real_encoding = sys.stderr.encoding
        with crawl.status_aware_stderr(None):
            assert sys.stderr.encoding == real_encoding

    def test_pause_with_null_status_does_not_raise(self):
        real = sys.stderr
        sys.stderr = StringIO()
        try:
            with crawl.status_aware_stderr(None):
                sys.stderr.write("hello")
        finally:
            sys.stderr = real

    def test_entered_when_console_is_terminal(self):
        with (
            patch.object(
                Console, "is_terminal", new_callable=PropertyMock, return_value=True
            ),
            patch.object(Console, "status", return_value=nullcontext()),
        ):
            out, err, returncode = run_command("crawl", "/ok/", "--depth", "0")

        assert returncode == 0
