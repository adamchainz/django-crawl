from __future__ import annotations

from argparse import ArgumentTypeError

from django.test import SimpleTestCase
from unittest_parametrize import ParametrizedTestCase, parametrize

from django_crawl.ext import argparse as ext_argparse


class ArgparseTests(ParametrizedTestCase, SimpleTestCase):
    @parametrize(
        ("function", "value", "message"),
        [
            (ext_argparse.non_negative_int, "x", "must be an integer"),
            (
                ext_argparse.non_negative_int,
                "-1",
                "must be greater than or equal to 0",
            ),
            (ext_argparse.positive_int, "x", "must be an integer"),
            (ext_argparse.positive_int, "0", "must be greater than 0"),
            (ext_argparse.max_query_variants, "x", "must be an integer"),
            (ext_argparse.max_query_variants, "0", "must be greater than 0"),
        ],
    )
    def test_int_argument_parsers_reject_invalid_values(self, function, value, message):
        with self.assertRaisesRegex(ArgumentTypeError, message):
            function(value)

    def test_positive_int_accepts_positive_values(self):
        assert ext_argparse.positive_int("1") == 1

    def test_max_query_variants_accepts_unlimited(self):
        assert ext_argparse.max_query_variants("unlimited") is None
