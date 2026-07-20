from __future__ import annotations

from io import StringIO
from typing import Any

from django.core.management import call_command
from django.core.management.base import CommandError


def run_command(*args: Any, **kwargs: Any) -> tuple[str, str, int | str | None]:
    out = StringIO()
    err = StringIO()
    returncode: int | str | None = 0
    try:
        call_command(*args, stdout=out, stderr=err, **kwargs)
    except CommandError as exc:
        err.write(str(exc))
        returncode = 1
    except SystemExit as exc:
        returncode = exc.code
    return out.getvalue(), err.getvalue(), returncode
