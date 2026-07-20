from __future__ import annotations

from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
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
        <a href="//other.example.com/external-protocol-relative/">external protocol-relative</a>
        """
    )


def ok(request: HttpRequest) -> HttpResponse:
    return HttpResponse('<a href="/deep/">deep</a>')


def query_variants(request: HttpRequest) -> HttpResponse:
    return HttpResponse(
        """
        <a href="/query-variants/?a=1">one</a>
        <a href="/query-variants/?a=2">two</a>
        <a href="/query-variants/?a=3">three</a>
        """
    )


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


def redirect_external(request: HttpRequest) -> HttpResponse:
    return redirect("https://example.com/")


def redirect_no_location(request: HttpRequest) -> HttpResponse:
    return HttpResponse(status=302)


def redirect_loop_a(request: HttpRequest) -> HttpResponse:
    return redirect("/redirect-loop-b/")


def redirect_loop_b(request: HttpRequest) -> HttpResponse:
    return redirect("/redirect-loop-a/")


def target(request: HttpRequest) -> HttpResponse:
    return HttpResponse("target")


def nested_page(request: HttpRequest) -> HttpResponse:
    return HttpResponse('<a href="../../target/">relative target</a>')


def needs_setup(request: HttpRequest) -> HttpResponse:
    if request.headers.get("x-setup") == "1":
        return HttpResponse("setup")
    return HttpResponse("forbidden", status=403)


def needs_host(request: HttpRequest) -> HttpResponse:
    if request.get_host() == "docs.example.com":
        return HttpResponse("host")
    return HttpResponse("forbidden", status=403)


def plain(request: HttpRequest) -> HttpResponse:
    return HttpResponse("no links here", content_type="text/plain")


def sitemap(request: HttpRequest) -> HttpResponse:
    return HttpResponse(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://testserver/ok/</loc></url>"
        "<url><loc>https://testserver/target/</loc></url>"
        "</urlset>",
        content_type="application/xml",
    )


def streaming(request: HttpRequest) -> StreamingHttpResponse:
    return StreamingHttpResponse(
        iter([b'<a href="/ok/">ok</a>']),
        content_type="text/html",
    )


urlpatterns = [
    path("", index),
    path("ok/", ok),
    path("deep/", deep),
    path("query-variants/", query_variants),
    path("bad/", bad),
    path("not-found/", not_found),
    path("server-error/", server_error),
    path("redirect/", redirect_view),
    path("redirect-external/", redirect_external),
    path("redirect-no-location/", redirect_no_location),
    path("redirect-loop-a/", redirect_loop_a),
    path("redirect-loop-b/", redirect_loop_b),
    path("target/", target),
    path("nested/page/", nested_page),
    path("needs-setup/", needs_setup),
    path("needs-host/", needs_host),
    path("plain/", plain),
    path("sitemap.xml", sitemap),
    path("streaming/", streaming),
]
