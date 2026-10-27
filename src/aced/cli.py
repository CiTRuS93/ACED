"""Offline conformance entry point; real integration belongs to trusted host Python."""

import argparse
import asyncio

from ._json import canonical_text
from .reference import conformance


def main() -> int:
    parser = argparse.ArgumentParser(prog="aced")
    parser.add_argument("--database", default=":memory:")
    parser.add_argument("command", choices=["conformance"])
    args = parser.parse_args()
    print(canonical_text(asyncio.run(conformance(args.database))))
    return 0
