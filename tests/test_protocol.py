"""Проверяем публичный результат: документ и безопасное воспроизведение."""
from datetime import date
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

from meeting_protocol.protocol import Assignment, Protocol, Segment, export_docx, replay


def test_docx_preserves_kazakh_and_assignment():
    protocol = Protocol(
        source_sha256="a" * 64, source_name="recording.mp3", meeting_date=date(2026, 9, 23),
        segments=[Segment(id=0, start=0, end=3, text="Динара, жұмаға дейін дайындаңыз.")],
        assignments=[Assignment(task="Подготовить договор", responsible="Динара", deadline_text="жұмаға дейін", evidence=[0])],
        summary="Обсудили договор.", provenance={"asr": "test"},
    )
    doc = Document(BytesIO(export_docx(protocol)))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "жұмаға дейін" in text
    assert "Обсудили договор" in text
    assert "Динара" in doc.tables[0].cell(1, 1).text


def test_replay_rejects_unknown_audio(tmp_path):
    audio = tmp_path / "unknown.mp3"
    audio.write_bytes(b"not a known recording")
    with pytest.raises(ValueError, match="Нет сохранённого результата"):
        replay(audio)


def test_web_rejects_unknown_recording():
    from fastapi.testclient import TestClient
    from meeting_protocol.web import app
    with TestClient(app) as client:
        response = client.post("/protocol", files={"audio": ("other.mp3", b"unknown", "audio/mpeg")}, data={"meeting_date": "2026-09-23"})
    assert response.status_code == 422
    assert "Нет сохранённого результата" in response.json()["detail"]


def test_replay_works_without_model_imports():
    import subprocess
    import sys
    script = """
import sys
from pathlib import Path
from meeting_protocol.protocol import replay
for n in (1, 2):
    p = replay(Path(f'docs/Трек 8 Инновации/Совещание №{n}.mp3'))
    assert p.assignments
assert not {'torch', 'faster_whisper', 'pydantic_ai'} & sys.modules.keys()
"""
    subprocess.run([sys.executable, "-c", script], check=True)
