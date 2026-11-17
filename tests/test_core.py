"""Behavioural tests for canonicalfp."""

from __future__ import annotations

import copy
import json
import os
import random
import subprocess
import sys
import unittest
from decimal import Decimal
from fractions import Fraction

from canonicalfp import CycleError, encode, explain, fingerprint


def _random_value(rng: random.Random, depth: int = 0):
    """Generate a random JSON-ish/typed value."""
    if depth >= 3:
        kind = rng.choice(["int", "str", "float", "bool", "none", "bytes", "decimal"])
    else:
        kind = rng.choice(
            ["int", "str", "float", "bool", "none", "bytes", "decimal",
             "list", "tuple", "dict", "set", "frozenset"]
        )
    if kind == "int":
        return rng.randint(-10**6, 10**6)
    if kind == "str":
        return rng.choice(["", "a", "ü", "日本", "\x00x", "line\nbreak", "x" * 70])
    if kind == "float":
        return rng.choice([0.0, -0.0, 1.5, -1.5, 1e300, 1e-300])
    if kind == "bool":
        return rng.choice([True, False])
    if kind == "none":
        return None
    if kind == "bytes":
        return bytes(rng.randrange(256) for _ in range(rng.randrange(0, 8)))
    if kind == "decimal":
        return Decimal(rng.choice(["0", "1", "1.0", "1.00", "-0", "3.14159"]))
    if kind in ("list", "tuple"):
        items = [_random_value(rng, depth + 1) for _ in range(rng.randrange(0, 5))]
        return items if kind == "list" else tuple(items)
    if kind == "dict":
        result = {}
        for _ in range(rng.randrange(0, 5)):
            result[rng.choice(["a", "b", "c", str(rng.randrange(5)), 7])] = _random_value(
                rng, depth + 1
            )
        return result
    if kind in ("set", "frozenset"):
        items = {rng.choice(["a", "b", "c", "ü", "x"]) for _ in range(rng.randrange(0, 5))}
        return items if kind == "set" else frozenset(items)
    raise AssertionError(kind)


class TestTypeExactness(unittest.TestCase):
    def test_scalars_that_compare_equal_have_different_fingerprints(self):
        values = [1, 1.0, True, Decimal("1"), Fraction(1, 1), "1", b"1", complex(1, 0)]
        digests = [fingerprint(v) for v in values]
        self.assertEqual(len(set(digests)), len(values))

    def test_int_and_float_are_distinct_in_structures(self):
        self.assertNotEqual(fingerprint({"x": 1}), fingerprint({"x": 1.0}))

    def test_containers_by_kind_not_exact_class(self):
        class MyDict(dict):
            pass

        self.assertEqual(fingerprint(MyDict(a=1)), fingerprint({"a": 1}))
        self.assertNotEqual(fingerprint([1, 2]), fingerprint((1, 2)))


class TestOrderInvariance(unittest.TestCase):
    def test_dict_insertion_order_does_not_matter(self):
        keys = [f"k{i}" for i in range(30)]
        rng = random.Random(20261117)
        expected = None
        for _ in range(200):
            rng.shuffle(keys)
            value = {key: key.upper() for key in keys}
            digest = fingerprint(value)
            if expected is None:
                expected = digest
            self.assertEqual(digest, expected)

    def test_set_construction_order_does_not_matter(self):
        items = [f"item-{i}" for i in range(40)]
        rng = random.Random(7)
        expected = None
        for _ in range(100):
            rng.shuffle(items)
            digest = fingerprint(set(items))
            if expected is None:
                expected = digest
            self.assertEqual(digest, expected)

    def test_cross_process_hash_seed_invariance(self):
        program = (
            "import sys; sys.path.insert(0, %r);"
            "from canonicalfp import fingerprint;"
            "value = {'b': {'x', 'y', 'z'}, 'a': [1, 2.5, None, 'ü']};"
            "print(fingerprint(value))" % os.getcwd()
        )
        digests = set()
        for seed in ("0", "1", "2", "7", "42", "123456"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            out = subprocess.run(
                [sys.executable, "-c", program],
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
            digests.add(out.stdout.strip())
        self.assertEqual(len(digests), 1)


class TestEdgeCases(unittest.TestCase):
    def test_all_nans_share_one_fingerprint(self):
        self.assertEqual(
            fingerprint(float("nan")),
            fingerprint(float("nan")),
        )
        self.assertEqual(
            fingerprint({"x": float("nan")}),
            fingerprint({"x": float("nan")}),
        )

    def test_signed_zero_is_distinct(self):
        self.assertNotEqual(fingerprint(0.0), fingerprint(-0.0))

    def test_decimal_trailing_zeros_are_normalised(self):
        self.assertEqual(fingerprint(Decimal("1.0")), fingerprint(Decimal("1.00")))
        self.assertEqual(fingerprint(Decimal("1.0")), fingerprint(Decimal("1")))

    def test_decimal_negative_zero(self):
        self.assertNotEqual(fingerprint(Decimal("-0")), fingerprint(Decimal("0")))

    def test_datetime_same_instant_is_equal_across_offsets(self):
        from datetime import datetime, timezone, timedelta

        utc = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
        shifted = utc.astimezone(timezone(timedelta(hours=5)))
        self.assertEqual(fingerprint(utc), fingerprint(shifted))
        self.assertNotEqual(fingerprint(utc), fingerprint(utc.replace(tzinfo=None)))

    def test_cycles_raise_instead_of_hanging(self):
        loop: list = []
        loop.append(loop)
        with self.assertRaises(CycleError):
            encode(loop)
        mapping: dict = {}
        mapping["self"] = mapping
        with self.assertRaises(CycleError):
            encode(mapping)

    def test_unsupported_type_is_rejected(self):
        with self.assertRaises(TypeError):
            encode(object())

    def test_nested_cycle_is_detected(self):
        loop: list = [1]
        loop.append({"inner": loop})
        with self.assertRaises(CycleError):
            encode(loop)


class TestExplain(unittest.TestCase):
    def test_equal_values_have_no_divergence(self):
        self.assertIsNone(explain({"a": [1, 2]}, {"a": [1, 2]}))

    def test_nested_path_is_reported(self):
        divergence = explain({"a": [1, {"b": 2}]}, {"a": [1, {"b": 3}]})
        self.assertIsNotNone(divergence)
        self.assertEqual(divergence.path, "$['a'][1]['b']")
        self.assertIn("2", divergence.left)
        self.assertIn("3", divergence.right)

    def test_missing_key_is_reported(self):
        divergence = explain({"a": 1}, {"a": 1, "b": 2})
        self.assertEqual(divergence.path, "$['b']")

    def test_list_length_difference(self):
        divergence = explain([1, 2], [1, 2, 3])
        self.assertEqual(divergence.path, "$[2]")

    def test_set_element_difference(self):
        divergence = explain({1, 2}, {1, 3})
        self.assertIsNotNone(divergence)
        self.assertIn("missing element", divergence.left + divergence.right)

    def test_type_change_at_leaf(self):
        divergence = explain({"a": 1}, {"a": True})
        self.assertEqual(divergence.path, "$['a']")
        self.assertIn("int", divergence.left)
        self.assertIn("bool", divergence.right)


class TestRandomised(unittest.TestCase):
    def test_mutation_always_changes_the_fingerprint(self):
        rng = random.Random(424242)
        checked = 0
        for _ in range(400):
            value = _random_value(rng)
            try:
                mutated = copy.deepcopy(value)
            except Exception:
                continue
            # Replace a random leaf with a different scalar.
            if isinstance(mutated, dict) and mutated:
                key = rng.choice(list(mutated))
                mutated[key] = "__mutated__"
            elif isinstance(mutated, (list, tuple)) and mutated:
                index = rng.randrange(len(mutated))
                items = list(mutated)
                items[index] = "__mutated__"
                mutated = items if isinstance(mutated, list) else tuple(items)
            else:
                mutated = "__mutated__"
            if encode(value) == encode(mutated):
                continue
            checked += 1
            self.assertNotEqual(fingerprint(value), fingerprint(mutated))
            self.assertIsNotNone(explain(value, mutated))
        self.assertGreaterEqual(checked, 300)

    def test_encoding_is_deterministic_for_repeated_calls(self):
        rng = random.Random(99)
        for _ in range(200):
            value = _random_value(rng)
            self.assertEqual(encode(value), encode(value))


class TestCli(unittest.TestCase):
    def _run(self, *args, stdin=None):
        return subprocess.run(
            [sys.executable, "-m", "canonicalfp", *args],
            capture_output=True,
            text=True,
            input=stdin,
            cwd=os.getcwd(),
        )

    def test_fingerprint_is_stable_across_calls(self):
        a = self._run("fp", "-", stdin='{"b": 2, "a": [1, 2]}')
        b = self._run("fp", "-", stdin='{"a": [1, 2], "b": 2}')
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual(a.stdout, b.stdout)

    def test_diff_exits_nonzero_for_type_change(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            left = os.path.join(tmp, "left.json")
            right = os.path.join(tmp, "right.json")
            with open(left, "w", encoding="utf-8") as handle:
                handle.write('{"a": 1}')
            with open(right, "w", encoding="utf-8") as handle:
                handle.write('{"a": 1.0}')
            result = self._run("diff", left, right)
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["equal"])
            self.assertEqual(payload["divergence"]["path"], "$['a']")

    def test_selftest_passes(self):
        result = self._run("selftest")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["failures"], [])


if __name__ == "__main__":
    unittest.main()