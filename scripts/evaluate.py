"""Reproducible CER / RTF evaluation on the bundled labelled fixtures.

    python scripts/evaluate.py --engine sensevoice
    python scripts/evaluate.py --engine qwen3 --out docs/accuracy_results.json

The normative text of every fixture is stored in tests/fixtures/manifest.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from voxscribe.core import audio  # noqa: E402
from voxscribe.engines.manager import EngineManager  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
_TAG = re.compile(r"<\|[^|]*\|>")
CN2DIGIT = dict(zip("零一二三四五六七八九", "0123456789"))
CN2DIGIT["〇"] = "0"
CN2DIGIT["两"] = "2"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", _TAG.sub("", text or "")).lower()
    out = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf":
            out.append(CN2DIGIT.get(ch, ch))
        elif ch.isalnum():
            out.append(ch)
    return "".join(out)


def edit_distance(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref: str, hyp: str) -> float:
    r, h = normalize(ref), normalize(hyp)
    if not r:
        return 0.0 if not h else 1.0
    return edit_distance(r, h) / len(r)


def load_manifest() -> list[dict]:
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


def evaluate(engine: str = "auto", ids: set[str] | None = None) -> dict:
    mgr = EngineManager(threads=4)
    rows = []
    for item in load_manifest():
        if ids and item["id"] not in ids:
            continue
        # Fixtures are flattened into tests/fixtures/ in the repository.
        wav = FIXTURES / Path(item["wav"]).name
        if not wav.is_file():
            continue
        a = audio.load_audio(wav)
        t0 = time.perf_counter()
        try:
            text, used, _ = mgr.transcribe(a.samples, engine,
                                           sample_rate=a.sample_rate,
                                           allow_fallback=True)
        except Exception as exc:
            text, used = f"<ERROR {exc}>", "none"
        secs = time.perf_counter() - t0
        rows.append({
            "id": item["id"], "ref": item["text"], "hyp": text,
            "cer": round(cer(item["text"], text), 4), "engine": used,
            "duration": round(a.duration, 2), "secs": round(secs, 3),
        })
    scored = [r for r in rows if normalize(r["ref"])]
    return {
        "engine": engine,
        "samples": len(rows),
        "cer": round(sum(r["cer"] for r in scored) / max(1, len(scored)), 4),
        "rtf": round(sum(r["secs"] for r in rows) /
                     max(0.001, sum(r["duration"] for r in rows)), 4),
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="auto")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--out")
    args = ap.parse_args()
    result = evaluate(args.engine, set(args.ids) if args.ids else None)
    print(f"engine={result['engine']}  samples={result['samples']}  "
          f"CER={result['cer']:.4f}  RTF={result['rtf']:.4f}")
    for r in result["rows"]:
        print(f"  {r['id']:<22} cer={r['cer']:.3f}  {r['engine']:<12} {r['hyp'][:48]}")
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
