"""Качество на собственных тестовых записях: WER транскрипта и совпадение поручений с эталоном.

Эталон — сценарий из data/test/*.reference.md (на слух не сверен), поэтому WER ориентировочный.
Запуск после GPU-прогона: python scripts/evaluate.py outputs/kz_01.json outputs/mix_01.json
"""
import json
import re
import sys
from pathlib import Path


def norm(text: str) -> list[str]:
    text = re.sub(r"[^\w\s]", " ", text.lower().replace("ё", "е"))
    return text.split()


def wer(reference: str, hypothesis: str) -> float:
    r, h = norm(reference), norm(hypothesis)
    row = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        previous, row[0] = row[0], i
        for j in range(1, len(h) + 1):
            current = min(row[j] + 1, row[j - 1] + 1, previous + (r[i - 1] != h[j - 1]))
            previous, row[j] = row[j], current
    return row[len(h)] / max(len(r), 1)


def reference(name: str) -> tuple[str, list[dict]]:
    text = Path(f"data/test/{name}.reference.md").read_text(encoding="utf-8")
    script = " ".join(re.findall(r"^> \*\*[^*]+:\*\*\s*(.+)$", text, re.M))
    table = text.split("## Ожидаемые поручения", 1)[1].split("##", 1)[0]
    rows = []
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0].isdigit():
            dates = re.findall(r"\d{2}\.\d{2}\.\d{4}", cells[4])
            rows.append({"responsible": cells[2], "dates": dates})
    return script, rows


def matches(expected: dict, actual: dict) -> bool:
    owner = (actual.get("responsible") or "").lower()
    expected_owner = expected["responsible"].lower()
    same_owner = owner and (owner.split()[0] in expected_owner or expected_owner.split()[0] in owner)
    if not expected["dates"] or len(expected["dates"]) > 1:   # no date or ambiguous: owner is enough
        return bool(same_owner)
    day = actual.get("deadline_date") or ""
    return bool(same_owner) and day == "-".join(reversed(expected["dates"][0].split(".")))


for path in map(Path, sys.argv[1:]):
    result = json.loads(path.read_text(encoding="utf-8"))
    name = path.stem
    script, expected = reference(name)
    transcript = " ".join(s["text"] for s in result["segments"])
    languages = sorted({s.get("language") or "?" for s in result["segments"]})
    found = sum(any(matches(e, a) for a in result["assignments"]) for e in expected)
    correct = sum(any(matches(e, a) for e in expected) for a in result["assignments"])
    print(f"{name}: WER {wer(script, transcript):.1%}; языки окон {languages}; "
          f"поручения: найдено {found}/{len(expected)} (recall), верных {correct}/{len(result['assignments'])} (precision)")
