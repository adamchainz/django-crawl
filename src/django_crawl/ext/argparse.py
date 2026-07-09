from __future__ import annotations

from argparse import ArgumentTypeError


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
