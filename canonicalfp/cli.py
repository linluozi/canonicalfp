"""Command line interface: ``python -m canonicalfp``."""

from __future__ import annotations

import argparse
import json
import sys

from .core import CycleError, encode, explain, fingerprint


def _load(path: str):
    if path == "-":
        return json.load(sys.stdin)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _cmd_fp(args: argparse.Namespace) -> int:
    value = _load(args.path)
    print(fingerprint(value, args.algorithm))
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    left = _load(args.left)
    right = _load(args.right)
    same = encode(left) == encode(right)
    result = {
        "equal": same,
        "left_fingerprint": fingerprint(left),
        "right_fingerprint": fingerprint(right),
        "divergence": None,
    }
    divergence = explain(left, right)
    if divergence is not None:
        result["divergence"] = {
            "path": divergence.path,
            "left": divergence.left,
            "right": divergence.right,
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if same else 1


def _cmd_selftest(_: argparse.Namespace) -> int:
    cases = [
        ({"a": 1, "b": [1, 2]}, {"b": [1, 2], "a": 1}, True),
        (1, 1.0, False),
        (True, 1, False),
        ({"x": {3, 1, 2}}, {"x": {1, 2, 3}}, True),
    ]
    failures = []
    for left, right, expected in cases:
        got = encode(left) == encode(right)
        if got != expected:
            failures.append({"left": repr(left), "right": repr(right), "expected": expected})
    print(json.dumps({"cases": len(cases), "failures": failures}, indent=2))
    return 0 if not failures else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="canonicalfp",
        description="Stable, type-exact fingerprints for Python/JSON values.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    fp_parser = sub.add_parser("fp", help="fingerprint a JSON file ('-' for stdin)")
    fp_parser.add_argument("path")
    fp_parser.add_argument("--algorithm", default="sha256")
    fp_parser.set_defaults(func=_cmd_fp)

    diff_parser = sub.add_parser("diff", help="compare two JSON files")
    diff_parser.add_argument("left")
    diff_parser.add_argument("right")
    diff_parser.set_defaults(func=_cmd_diff)

    test_parser = sub.add_parser("selftest", help="run the built-in smoke test")
    test_parser.set_defaults(func=_cmd_selftest)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CycleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())