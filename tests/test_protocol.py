"""Проверяем публичный результат: документ и безопасное воспроизведение."""
from datetime import date
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

from meeting_protocol.protocol import Assignment, MeetingContext, Protocol, Segment, export_docx, replay, resolve_context


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


def test_context_by_audio_content_and_explicit_override(tmp_path):
    original = Path('docs/Трек 8 Инновации/Совещание №2.mp3')
    renamed = tmp_path / 'renamed.mp3'
    renamed.write_bytes(original.read_bytes())
    context = resolve_context(renamed)
    assert 'Ботагоз Нурлановна' in context.participants
    assert 'Жандос Талгатович' in context.participants
    assert context.topic == 'Доклады по производственным показателям направлений'
    custom = resolve_context(renamed, ' Динара ; Айбек\nДинара ', ' Новая тема ')
    assert custom == MeetingContext(participants=['Динара', 'Айбек'], topic='Новая тема')
    with pytest.raises(ValueError, match='не пересчитывает'):
        replay(renamed, context=custom)


def test_person_must_match_roster_but_department_is_preserved():
    from meeting_protocol.pipeline import AgentAssignment, AgentExtraction, validate_names
    context = MeetingContext(participants=['Ботагоз Нурлановна'])
    task = dict(task='Подготовить договор', deadline_text=None, evidence=[0])
    result = AgentExtraction(summary='', assignments=[AgentAssignment(**task, responsible='Батагус Нурлановна', responsible_type='person')])
    with pytest.raises(ValueError, match='точно совпадать'):
        validate_names(result, context)
    result.assignments[0].responsible = 'Ботагоз Нурлановна'
    validate_names(result, context)
    result.assignments.append(AgentAssignment(**task, responsible='Юридический департамент', responsible_type='department'))
    validate_names(result, context)


def test_context_reaches_agent_but_not_asr(monkeypatch, tmp_path):
    from meeting_protocol import pipeline
    from meeting_protocol.protocol import Extraction
    audio = tmp_path / 'test.mp3'
    audio.write_bytes(b'regression boundary')
    segments = [Segment(id=0, start=0, end=1, text='Батагус, подготовьте договор.')]
    context = MeetingContext(participants=['Ботагоз Нурлановна'], topic='Договор')
    seen = {}

    def asr(path):
        assert path == audio
        return segments

    def agent(transcript, meeting_date, received_context):
        seen['context'] = received_context
        return Extraction(summary='Договор', assignments=[Assignment(task='Подготовить договор', responsible=context.participants[0], deadline_text=None, evidence=[0])])

    monkeypatch.setattr(pipeline, 'transcribe', asr)
    monkeypatch.setattr(pipeline, 'diarize', lambda path, found: found)
    monkeypatch.setattr(pipeline, 'extract', agent)
    result = pipeline.process(audio, date(2026, 9, 23), context)
    assert seen['context'] == context
    assert result.segments == segments
    assert result.context == context
    assert result.assignments[0].responsible == 'Ботагоз Нурлановна'


def test_web_form_context_and_replay_mismatch():
    from fastapi.testclient import TestClient
    from meeting_protocol.web import app
    audio = Path('docs/Трек 8 Инновации/Совещание №2.mp3')
    with TestClient(app) as client:
        page = client.get('/').text
        assert 'name="participants"' in page and 'name="topic"' in page
        response = client.post('/protocol', files={'audio': ('meeting.mp3', audio.read_bytes(), 'audio/mpeg')},
                               data={'meeting_date': '2026-09-23', 'participants': 'Другой человек', 'topic': 'Изменено'})
        assert response.status_code == 422
        assert 'не пересчитывает' in response.json()['detail']


def test_web_replay_accepts_prefilled_context():
    from fastapi.testclient import TestClient
    from meeting_protocol.web import app
    audio = Path('docs/Трек 8 Инновации/Совещание №2.mp3')
    context = resolve_context(audio)
    with TestClient(app) as client:
        response = client.post('/protocol', files={'audio': ('meeting.mp3', audio.read_bytes(), 'audio/mpeg')},
                               data={'meeting_date': '2026-09-23', 'participants': '\n'.join(context.participants), 'topic': context.topic})
        assert response.status_code == 200
        docx = client.get(response.url.path + '.docx')
    doc = Document(BytesIO(docx.content))
    owners = {row.cells[1].text for row in doc.tables[0].rows[1:]}
    assert 'Ботагоз Нурлановна' in owners
    assert 'Жандос Талгатович' in owners


def test_web_gpu_forwards_form_fields(monkeypatch):
    from fastapi.testclient import TestClient
    from meeting_protocol import pipeline
    from meeting_protocol.web import app
    monkeypatch.setenv('APP_MODE', 'gpu')
    seen = {}

    def process(audio, meeting_date, context):
        seen['context'] = context
        return Protocol(source_sha256='a' * 64, source_name=audio.name, meeting_date=meeting_date,
                        segments=[Segment(id=0, start=0, end=1, text='Текст')], assignments=[],
                        summary='Саммари', provenance={}, context=context)

    monkeypatch.setattr(pipeline, 'process', process)
    with TestClient(app) as client:
        response = client.post('/protocol', files={'audio': ('new.mp3', b'new', 'audio/mpeg')},
                               data={'meeting_date': '2026-09-23', 'participants': 'Динара\nАйбек', 'topic': 'Договор'})
    assert response.status_code == 200
    assert seen['context'] == MeetingContext(participants=['Динара', 'Айбек'], topic='Договор')


def test_speaker_name_must_match_roster_and_be_unique():
    from meeting_protocol.pipeline import AgentExtraction, validate_names
    from meeting_protocol.protocol import SpeakerName
    context = MeetingContext(participants=['Ботагоз Нурлановна', 'Ерлан'])
    result = AgentExtraction(summary='', assignments=[], speakers=[SpeakerName(label='SPEAKER_2', name='Батагус', evidence=[1])])
    with pytest.raises(ValueError, match='говорящего'):
        validate_names(result, context)
    result.speakers = [SpeakerName(label='SPEAKER_2', name='Ботагоз Нурлановна', evidence=[1]),
                       SpeakerName(label='SPEAKER_3', name='Ботагоз Нурлановна', evidence=[4])]
    with pytest.raises(ValueError, match='нескольким меткам'):
        validate_names(result, context)
    result.speakers = [SpeakerName(label='SPEAKER_2', name='Ботагоз Нурлановна', evidence=[1]),
                       SpeakerName(label='SPEAKER_3', name=None, evidence=[])]
    validate_names(result, context)


def test_docx_shows_named_speakers():
    from meeting_protocol.protocol import SpeakerName
    protocol = Protocol(
        source_sha256="b" * 64, source_name="r.mp3", meeting_date=date(2026, 9, 23),
        segments=[Segment(id=0, start=0, end=2, text="Ботагоз, вам слово.", speaker="SPEAKER_1"),
                  Segment(id=1, start=2, end=5, text="По химическому направлению.", speaker="SPEAKER_2")],
        assignments=[], summary="", provenance={}, speakers=[SpeakerName(label="SPEAKER_2", name="Ботагоз Нурлановна", evidence=[0, 1])],
    )
    text = "\n".join(p.text for p in Document(BytesIO(export_docx(protocol))).paragraphs)
    assert "SPEAKER_2 (Ботагоз Нурлановна): По химическому направлению." in text
    assert "SPEAKER_1: Ботагоз, вам слово." in text


def test_clustering_separates_distinct_voices():
    np = pytest.importorskip("numpy")
    from meeting_protocol.diarization import cluster
    rng = np.random.default_rng(0)
    a, b = rng.normal(size=192), rng.normal(size=192)
    vectors = [a + rng.normal(scale=0.1, size=192) for _ in range(4)] + [b + rng.normal(scale=0.1, size=192) for _ in range(3)]
    labels = cluster(vectors)
    assert len(set(labels[:4])) == 1 and len(set(labels[4:])) == 1 and labels[0] != labels[4]


def test_web_result_page_links_assignments_to_replicas():
    from fastapi.testclient import TestClient
    from meeting_protocol.web import app
    audio = Path('docs/Трек 8 Инновации/Совещание №2.mp3')
    context = resolve_context(audio)
    with TestClient(app) as client:
        response = client.post('/protocol', files={'audio': ('meeting.mp3', audio.read_bytes(), 'audio/mpeg')},
                               data={'meeting_date': '2026-09-23', 'participants': '\n'.join(context.participants), 'topic': context.topic})
        assert response.status_code == 200 and response.url.path.startswith('/result/')
        page = response.text
        assert 'Ботагоз Нурлановна' in page and 'Скачать DOCX' in page and 'не проверка моделей' in page
        assert 'href=#seg-' in page and 'id=seg-0' in page
        docx = client.get(response.url.path + '.docx')
        assert docx.status_code == 200 and docx.content[:2] == b'PK'
        assert client.get('/result/missing').status_code == 404


def test_deadline_status_relative_to_date():
    task = Assignment(task='x', responsible=None, deadline_text='до пятницы', deadline_date=date(2026, 9, 25), evidence=[0])
    assert task.status(date(2026, 9, 23)) == 'скоро срок'
    assert task.status(date(2026, 9, 26)) == 'просрочено'
    assert task.status(date(2026, 9, 1)) == 'в работе'
    assert Assignment(task='x', responsible=None, deadline_text=None, evidence=[0]).status(date(2026, 9, 23)) == 'без даты'
