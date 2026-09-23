"""Проверяемый протокол и экспорт, не зависящие от GPU и моделей."""
import hashlib
from datetime import date
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.shared import Pt
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parent.parent


class Segment(BaseModel):
    id: int
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str
    speaker: str | None = None


class Assignment(BaseModel):
    task: str = Field(min_length=1)
    responsible: str | None = None
    deadline_text: str | None = None
    evidence: list[int] = Field(min_length=1)


class Extraction(BaseModel):
    assignments: list[Assignment]
    summary: str


class Protocol(Extraction):
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_name: str
    meeting_date: date
    segments: list[Segment] = Field(min_length=1)
    provenance: dict[str, str]

    @model_validator(mode="after")
    def validate_evidence(self):
        ids = {segment.id for segment in self.segments}
        if len(ids) != len(self.segments):
            raise ValueError("Идентификаторы реплик должны быть уникальными")
        for assignment in self.assignments:
            if not set(assignment.evidence) <= ids:
                raise ValueError("Поручение ссылается на отсутствующую реплику")
        return self


def audio_hash(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def replay(audio: Path) -> Protocol:
    digest = audio_hash(audio)
    for path in sorted((ROOT / "data" / "replay").glob("*.json")):
        protocol = Protocol.model_validate_json(path.read_text())
        if protocol.source_sha256 == digest:
            return protocol
    raise ValueError("Нет сохранённого результата для этого аудио. Нужен режим GPU.")


def export_docx(protocol: Protocol, *, replay_mode: bool = False) -> bytes:
    doc = Document()
    doc.styles["Normal"].font.name = "Arial"
    doc.styles["Normal"].font.size = Pt(11)
    doc.add_heading("Протокол совещания", 0)
    doc.add_paragraph(f"Запись: {protocol.source_name}. Дата встречи: {protocol.meeting_date}.")
    if replay_mode:
        doc.add_paragraph("Воспроизведение заранее вычисленного результата — не проверка моделей.")
    doc.add_paragraph("Черновик ИИ: проверьте имена, сроки и содержание по записи. Диаризация в этапе 1 ещё не реализована.")
    doc.add_heading("Саммари", 1)
    doc.add_paragraph(protocol.summary or "Не сформировано")
    doc.add_heading("Поручения", 1)
    table = doc.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    for cell, title in zip(table.rows[0].cells, ["Суть", "Ответственный", "Срок (как сказано)", "Реплики"]):
        cell.text = title
    for assignment in protocol.assignments:
        values = [assignment.task, assignment.responsible or "Не указан", assignment.deadline_text or "Не указан", ", ".join(map(str, assignment.evidence))]
        for cell, value in zip(table.add_row().cells, values):
            cell.text = value
    doc.add_heading("Транскрипт", 1)
    for segment in protocol.segments:
        doc.add_paragraph(f"[{segment.id}; {segment.start:.1f}–{segment.end:.1f} с] {segment.speaker or 'Говорящий не определён'}: {segment.text}")
    doc.add_heading("Происхождение", 1)
    doc.add_paragraph(f"SHA-256: {protocol.source_sha256}")
    for key, value in protocol.provenance.items():
        doc.add_paragraph(f"{key}: {value}")
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()
