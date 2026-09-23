"""Side-by-side of the organisers' reference action items and our replay results.

The matching verdict is manual: this script only prints each reference row next to
our action items with the same responsible person (by first name), so a reviewer
can check the task, owner and deadline without a GPU.
Run: uv run --locked python scripts/compare_reference.py
"""
import hashlib
import json
from pathlib import Path

from docx import Document

CASE = Path("docs/Трек 8 Инновации")


def reference_rows(number: int) -> list[list[str]]:
    rows = []
    for table in Document(CASE / f"Протокол_совещания№{number}.docx").tables:
        header = [cell.text.strip() for cell in table.rows[0].cells]
        if header[0] == "Поручение":
            rows += [[cell.text.strip() for cell in row.cells] for row in table.rows[1:]]
    return rows


def replay(number: int) -> dict:
    digest = hashlib.sha256((CASE / f"Совещание №{number}.mp3").read_bytes()).hexdigest()
    for path in sorted(Path("data/replay").glob("*.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        if result["source_sha256"] == digest:
            return result
    raise SystemExit(f"Нет сохранённого результата для совещания №{number}")


def first_name(text: str | None) -> str:
    return (text or "").split(" ")[0].strip("(),").lower()


for number in (1, 2):
    ours = replay(number)["assignments"]
    rows = reference_rows(number)
    print(f"\n=== Совещание №{number}: строк эталона {len(rows)}, наших поручений {len(ours)}")
    for index, (task, owner, deadline) in enumerate(rows, 1):
        print(f"\nЭталон {index}: {task} | {owner} | {deadline}")
        candidates = [a for a in ours if first_name(a["responsible"]) == first_name(owner)]
        for a in candidates or [{"task": "— нет поручения с этим ответственным —", "responsible": "", "deadline_text": "", "deadline_date": ""}]:
            print(f"   наше: {a['task']} | {a['responsible']} | {a['deadline_text']} ({a['deadline_date']})")
