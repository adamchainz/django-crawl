from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import path


def index(request: HttpRequest) -> HttpResponse:
    return HttpResponse(
        """
        <a href="/ok/">ok</a>
        <a href="/bad/">bad</a>
        <a href="/not-found/">not found</a>
        <a href="/server-error/">server error</a>
        <a href="https://example.com/external/">external</a>
        """
    )


def ok(request: HttpRequest) -> HttpResponse:
    return HttpResponse('<a href="/deep/">deep</a>')


def deep(request: HttpRequest) -> HttpResponse:
    return HttpResponse("deep")


def bad(request: HttpRequest) -> HttpResponse:
    return HttpResponse("bad", status=400)


def not_found(request: HttpRequest) -> HttpResponse:
    return HttpResponse("not found", status=404)


def server_error(request: HttpRequest) -> HttpResponse:
    raise ValueError("broken")


def redirect_view(request: HttpRequest) -> HttpResponse:
    return redirect("/target/")


def target(request: HttpRequest) -> HttpResponse:
    return HttpResponse("target")


def needs_setup(request: HttpRequest) -> HttpResponse:
    if request.headers.get("x-setup") == "1":
        return HttpResponse("setup")
    return HttpResponse("forbidden", status=403)


def needs_host(request: HttpRequest) -> HttpResponse:
    if request.get_host() == "docs.example.com":
        return HttpResponse("host")
    return HttpResponse("forbidden", status=403)


urlpatterns = [
    path("", index),
    path("ok/", ok),
    path("deep/", deep),
    path("bad/", bad),
    path("not-found/", not_found),
    path("server-error/", server_error),
    path("redirect/", redirect_view),
    path("target/", target),
    path("needs-setup/", needs_setup),
    path("needs-host/", needs_host),
]
