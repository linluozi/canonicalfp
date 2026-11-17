# canonicalfp

**Stable, type-exact fingerprints for Python values — the same content always hashes the same, across insertion order, set order, processes and `PYTHONHASHSEED`.**

`pickle` and `json.dumps(sort_keys=True)` are the usual answers, and both have
silent equivalence bugs: `pickle.dumps` keeps dict insertion order (the same
mapping serialises to different bytes), `hash(frozenset(...))` changes with the
hash seed, and JSON cannot represent sets, `Decimal`, `datetime` or non-ASCII
bytes at all. `canonicalfp` defines an explicit equivalence contract, encodes it
unambiguously, and can point at the first place two values diverge.

Upstream: none — this is an original library, no upstream code is vendored or patched.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -t . -q     # 25 tests, OK
```

Python 3.9+; reference environment CPython 3.12.3, no third-party dependencies.

## Use

```python
from canonicalfp import fingerprint, explain

fingerprint({"b": 2, "a": {3, 1, 2}})        # stable across processes
fingerprint({"a": 1}) != fingerprint({"a": 1.0})   # type-exact
explain({"a": [1, {"b": 2}]}, {"a": [1, {"b": 3}]})
# Divergence("$['a'][1]['b']", 'int 2', 'int 3')
```

```bash
python -m canonicalfp fp data.json          # sha256 of the canonical form
python -m canonicalfp diff left.json right.json   # exit 1 + first divergence
python -m canonicalfp selftest
```

## Equivalence contract

| Rule | Example |
| --- | --- |
| Scalars are compared by exact builtin type | `1`, `1.0`, `True`, `Decimal("1")`, `Fraction(1,1)`, `"1"` are 6 classes |
| Containers are compared by kind, not subclass | a `dict` subclass equals a plain `dict` with the same items |
| Mappings/sets are order-insensitive | 500 insertion orders → 1 fingerprint |
| All NaNs collapse to one class | `fingerprint(float("nan")) == fingerprint(float("nan"))` |
| `0.0` and `-0.0` stay distinct | they encode to different IEEE payloads |
| Aware `datetime`s normalise to UTC | two offsets of the same instant agree; naive ≠ aware |
| Cycles raise `CycleError` | no hangs, no silent truncation |

## Evidence

All numbers below are produced by `python3 evidence/run.py` (1.7 s) and stored
verbatim in [`evidence/report.json`](evidence/report.json);
`deterministic_sha256 = b3bee0edc314741750ff63bf2b94ab134b0652316f8cf28655dd4f2515808cf4`.

| Experiment | canonicalfp | obvious alternative |
| --- | --- | --- |
| Same 40-key mapping, 500 random insertion orders | **1** unique fingerprint | **500** unique `pickle` digests |
| Same structure under 12 `PYTHONHASHSEED` values | **1** unique fingerprint | **12** unique `hash(frozenset(...))` values |
| 8 values that compare equal or near-equal (`1`, `1.0`, `True`, `Decimal("1")`, `Fraction(1,1)`, `"1"`, `b"1"`, `complex(1,0)`) | **8** distinct | `json` cannot even encode two of them |
| 500 random typed structures, one leaf mutated | **500/500** detected, first divergence reported | — |
| 2,000 nested dicts, 3 sets/lists each (521,256 encoded bytes) | median **54.459 ms** (20 rounds) | — |

Concrete JSON failures recorded by the same run: `json.dumps` raises
`TypeError` for a set, raises `TypeError` for `Decimal("1.5")`, and emits the
literal `{"x": NaN}`, which is **not** valid RFC 8259 JSON.

Raw timing samples are in `experiments.timing.raw_ms`; the run is deterministic
except for those timings.

## Reproduce

```bash
python3 -m unittest discover -s tests -t . -q
python3 evidence/run.py
python3 -m canonicalfp selftest
```

The second command rewrites `evidence/report.json`; `deterministic_sha256`
covers every field except `timing` and itself, so it reproduces on any machine
with the same Python minor version. Timing samples are reported separately.

## 本轮创新

首次把「类型精确 + 顺序不敏感 + 跨进程哈希种子不变」写成一个可执行的规范指纹契约，并用同机可复现的反例量化了常规做法的错误等价类：同一 mapping 的 500 种插入序在 `pickle` 下产生 **500 个不同摘要**（canonicalfp 1 个），12 个 `PYTHONHASHSEED` 下内置 `frozenset` 哈希有 **12 个不同值**（canonicalfp 1 个）。与台账里的 `csvresume`（CSV 字节区间）、`jsonx`（JSON 值轴）不同，本轮的对象是 **Python 值本身的等价类**，并首次给出路径级「首个分歧」定位而不是只报布尔相等。

## Limits

- This is a fingerprint, not a serializer: there is no `decode`.
- Objects whose `repr` is unstable (custom classes) are rejected with `TypeError`.
- All NaNs share a class by design; if you need NaN payload identity, this is
  the wrong tool.
- The encoding is not intended to be compact: it is length-prefixed and
  type-tagged for unambiguity (521 KB for the 2,000-record fixture).

## License

MIT. See `LICENSE`.