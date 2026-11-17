"""Reproduce every number quoted in README.md.

Run:  python3 evidence/run.py
Out:  evidence/report.json  (raw counts + timings, replay-stable)
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import platform
import random
import subprocess
import sys
import time
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from canonicalfp import encode, explain, fingerprint  # noqa: E402


def env_info() -> dict:
    cpu = ""
    with open("/proc/cpuinfo", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    mem_kb = 0
    with open("/proc/meminfo", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("MemTotal:"):
                mem_kb = int(line.split()[1])
                break
    return {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "cpu": cpu,
        "mem_total_kb": mem_kb,
    }


def experiment_dict_order(permutations: int = 500, keys: int = 40) -> dict:
    base = [f"k{i}" for i in range(keys)]
    rng = random.Random(20261117)
    digests = set()
    for _ in range(permutations):
        rng.shuffle(base)
        digests.add(fingerprint({key: key.upper() for key in base}))
    return {
        "permutations": permutations,
        "keys": keys,
        "unique_fingerprints": len(digests),
    }


def experiment_pickle_order(permutations: int = 500, keys: int = 40) -> dict:
    """The same mapping, 500 insertion orders, hashed with pickle."""
    base = [f"k{i}" for i in range(keys)]
    rng = random.Random(11)
    digests = set()
    for _ in range(permutations):
        rng.shuffle(base)
        digests.add(hashlib.sha256(pickle.dumps({k: k.upper() for k in base})).hexdigest())
    return {"permutations": permutations, "unique_pickle_digests": len(digests)}


def experiment_cross_process(seeds: int = 12) -> dict:
    program = (
        "import sys; sys.path.insert(0, %r);"
        "from canonicalfp import fingerprint;"
        "value = {'b': frozenset({'x', 'y', 'z'}), 'a': [1, 2.5, None, '\\u00fc']};"
        "print(fingerprint(value));"
        "print(hash(frozenset({'x', 'y', 'z', 'w', 'v', str(1), str(2)})))" % str(ROOT)
    )
    canon, builtin = set(), set()
    for seed in range(seeds):
        env = dict(os.environ, PYTHONHASHSEED=str(seed * 7919))
        out = subprocess.run(
            [sys.executable, "-c", program], capture_output=True, text=True, check=True, env=env
        ).stdout.split()
        canon.add(out[0])
        builtin.add(out[1])
    return {
        "pythonhashseed_values": seeds,
        "unique_canonicalfp_digests": len(canon),
        "unique_builtin_frozenset_hashes": len(builtin),
    }


def experiment_type_matrix() -> dict:
    values = {
        "int": 1,
        "float": 1.0,
        "bool": True,
        "decimal": Decimal("1"),
        "fraction": Fraction(1, 1),
        "str": "1",
        "bytes": b"1",
        "complex": complex(1, 0),
    }
    digests = {name: fingerprint(value) for name, value in values.items()}
    return {
        "values": list(values),
        "unique_fingerprints": len(set(digests.values())),
        "digests": digests,
    }


def _random_value(rng: random.Random, depth: int = 0):
    if depth >= 3:
        kind = rng.choice(["int", "str", "float", "bool", "none", "bytes", "decimal"])
    else:
        kind = rng.choice(
            ["int", "str", "float", "bool", "none", "bytes", "decimal",
             "list", "tuple", "dict", "set"]
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
        return Decimal(rng.choice(["0", "1", "1.0", "-0", "3.14159"]))
    if kind in ("list", "tuple"):
        items = [_random_value(rng, depth + 1) for _ in range(rng.randrange(0, 5))]
        return items if kind == "list" else tuple(items)
    if kind == "dict":
        result = {}
        for _ in range(rng.randrange(0, 5)):
            result[rng.choice(["a", "b", "c", str(rng.randrange(5)), 7])] = _random_value(rng, depth + 1)
        return result
    items = {rng.choice(["a", "b", "c", "ü", "x"]) for _ in range(rng.randrange(0, 5))}
    return items


def experiment_mutations(cases: int = 500) -> dict:
    rng = random.Random(20261117)
    detected = 0
    exercised = 0
    for _ in range(cases):
        value = _random_value(rng)
        if isinstance(value, dict) and value:
            mutated = dict(value)
            mutated[rng.choice(list(mutated))] = "__mutated__"
        elif isinstance(value, (list, tuple)) and value:
            items = list(value)
            items[rng.randrange(len(items))] = "__mutated__"
            mutated = items if isinstance(value, list) else tuple(items)
        else:
            mutated = "__mutated__"
        if encode(value) == encode(mutated):
            continue
        exercised += 1
        if fingerprint(value) != fingerprint(mutated) and explain(value, mutated) is not None:
            detected += 1
    return {"cases": cases, "exercised": exercised, "detected": detected}


def experiment_json_limits() -> dict:
    """What the obvious alternatives cannot represent."""
    result = {}
    try:
        json.dumps({"s": {1, 2, 3}}, sort_keys=True)
        result["json_set"] = "ok"
    except TypeError as exc:
        result["json_set"] = type(exc).__name__
    try:
        json.dumps({"d": Decimal("1.5")}, sort_keys=True)
        result["json_decimal"] = "ok"
    except TypeError as exc:
        result["json_decimal"] = type(exc).__name__
    nan_text = json.dumps({"x": float("nan")}, sort_keys=True)
    result["json_nan_output"] = nan_text
    result["json_nan_is_rfc8259"] = "NaN" not in nan_text
    result["canonicalfp_set_ok"] = bool(fingerprint({1, 2, 3}))
    return result


def experiment_timing(rounds: int = 20) -> dict:
    rng = random.Random(5)
    big = {
        f"row{i}": {
            "id": i,
            "name": "用户-%d" % i,
            "tags": {rng.choice(["a", "b", "c", "d"]) for _ in range(3)},
            "payload": [rng.random(), rng.randint(0, 10**9), None],
        }
        for i in range(2000)
    }
    samples = []
    for _ in range(rounds):
        started = time.perf_counter()
        fingerprint(big)
        samples.append((time.perf_counter() - started) * 1000.0)
    samples.sort()
    return {
        "structure": "2000 nested dicts (3 sets/lists each)",
        "rounds": rounds,
        "median_ms": round(samples[len(samples) // 2], 3),
        "min_ms": round(samples[0], 3),
        "max_ms": round(samples[-1], 3),
        "raw_ms": [round(x, 3) for x in samples],
        "encoded_bytes": len(encode(big)),
    }


def main() -> int:
    report = {
        "generated_by": "evidence/run.py",
        "environment": env_info(),
        "experiments": {
            "dict_order": experiment_dict_order(),
            "pickle_order": experiment_pickle_order(),
            "cross_process": experiment_cross_process(),
            "type_matrix": experiment_type_matrix(),
            "mutations": experiment_mutations(),
            "json_limits": experiment_json_limits(),
            "timing": experiment_timing(),
        },
    }
    stable = json.loads(json.dumps(report, ensure_ascii=False))
    stable["experiments"].pop("timing", None)
    canonical = json.dumps(stable, sort_keys=True, ensure_ascii=False)
    report["deterministic_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    out = ROOT / "evidence" / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False)[:4000])
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())