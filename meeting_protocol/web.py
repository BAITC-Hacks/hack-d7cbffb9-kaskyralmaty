"""Минимальный вход в общий конвейер; сервер слушает localhost по README."""
import os
import json
import tempfile
import threading
import uuid
from collections import OrderedDict
from datetime import date
from html import escape
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from .protocol import Protocol, export_docx, meeting_presets, replay, resolve_context

app = FastAPI(title="Протокол совещания")
processing = threading.Lock()
# Results live only in this process memory: nothing is written to disk, restart clears them.
results: "OrderedDict[str, tuple[Protocol, bool]]" = OrderedDict()
MAX_RESULTS = 20

UI = Path(__file__).parent / "ui"
STATUS_CLASS = {"просрочено": "s-late", "скоро срок": "s-soon", "в работе": "s-ok", "без даты": "s-none"}
PALETTE = ["#0f6b52", "#3b5bdb", "#c2255c", "#e8590c", "#7048e8", "#0c8599", "#5c940d", "#862e9c"]


def asset(name: str) -> str:
    return (UI / name).read_text(encoding="utf-8")


def header(replay_mode: bool) -> str:
    chip = '<span class="chip">Воспроизведение, не проверка моделей</span>' if replay_mode else '<span class="chip live">Локальные модели · GPU</span>'
    return f'<header class="top"><div class="top-in"><a class="logo" href="/"><span class="logo-mark">Х</span>Хаттама</a><span class="spacer"></span>{chip}</div></header>'


def initials(name: str) -> str:
    return "".join(part[0] for part in name.split()[:2]).upper() or "?"


def color(key: str) -> str:
    return PALETTE[sum(map(ord, key)) % len(PALETTE)]


def render_result(key: str, protocol: Protocol, replay_mode: bool, as_of: date) -> str:
    statuses = [a.status(as_of) for a in protocol.assignments]
    tasks = "".join(
        f"""<article class=task><div class=task-what>{escape(a.task)}</div>
        <div class=task-when><span class="pill {STATUS_CLASS[st]}">{st}</span></div>
        <div class=task-who><span class=avatar style="background:{color(a.responsible or '?')}">{escape(initials(a.responsible or '?'))}</span>{escape(a.responsible or 'Ответственный не указан')}</div>
        <div class=task-when>{escape(a.deadline_text or 'Срок не указан')}{'<br><b>' + a.deadline_date.strftime('%d.%m.%Y') + '</b>' if a.deadline_date else ''}</div>
        <div class=task-src><span class=muted>Источник:</span>{''.join(f'<a class=src href=#seg-{i}>→ #{i}</a>' for i in a.evidence)}</div></article>"""
        for a, st in zip(protocol.assignments, statuses))
    transcript = "".join(
        f"<div class=seg id=seg-{s.id}><span class=t>{int(s.start // 60):02d}:{int(s.start % 60):02d}</span><div>"
        f"<span class=who style='color:{color(s.speaker or '?')}'>{escape(protocol.speaker_title(s.speaker))}</span>"
        f"{'<span class=lang>KZ</span>' if s.language == 'kk' else ''} <span class=muted small>#{s.id}</span><br>{escape(s.text)}</div></div>"
        for s in protocol.segments)
    speakers = "".join(
        f"<span class=speaker><span class=avatar style='background:{color(sp.label)}'>{escape(initials(sp.name or sp.label[-1:]))}</span>{escape(protocol.speaker_title(sp.label))}</span>"
        for sp in protocol.speakers) or "<span class=muted>не определены</span>"
    duration = protocol.segments[-1].end
    notice = "<div class='notice'>Воспроизведение заранее вычисленного результата, не проверка моделей.</div>" if replay_mode else ""
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Протокол: {escape(protocol.source_name)}</title><style>{asset('style.css')}</style></head><body>{header(replay_mode)}<main>
    <section class=hero><h1>{escape(protocol.context.topic or 'Протокол совещания')}</h1></section>
    <div class=meta><span>Дата встречи {protocol.meeting_date:%d.%m.%Y}</span><span>Запись {escape(protocol.source_name)}</span><span>Длительность {int(duration // 60)} мин {int(duration % 60)} с</span></div>
    {notice}
    <div class=kpis><div class=kpi><b>{len(protocol.assignments)}</b><span>поручений</span></div>
    <div class=kpi><b style="color:var(--soon)">{statuses.count('скоро срок')}</b><span>скоро срок (≤ 3 дней)</span></div>
    <div class=kpi><b style="color:var(--late)">{statuses.count('просрочено')}</b><span>просрочено</span></div>
    <div class=kpi><b>{len({s.speaker for s in protocol.segments if s.speaker})}</b><span>голосов в записи</span></div></div>
    <div class=grid><div>
    <section class=card><h2>Поручения <span class=count>{len(protocol.assignments)}</span><span class=spacer></span>
    <a class=btn href="/result/{key}.docx">Скачать DOCX</a></h2>
    <p class="muted small">Статус на {as_of:%d.%m.%Y}. Нажмите «→ #N», чтобы увидеть реплику, из которой взято поручение.</p>
    <div class=tasks>{tasks or '<p class=muted>Поручения не найдены</p>'}</div></section>
    <section class=card><h2>Саммари</h2><p style="margin:0">{escape(protocol.summary or 'Не сформировано')}</p></section>
    </div><div class=sticky>
    <section class=card><h2>Транскрипт <span class=count>{len(protocol.segments)}</span></h2>
    <div class=speakers style="margin-bottom:12px">{speakers}</div>
    <div class=transcript>{transcript}</div>
    <p class="muted small">Голоса размечены автоматически, имена взяты из обращений в разговоре. Метка KZ: фрагмент распознан SeamlessM4T.</p></section>
    </div></div>
    <p class="muted small">Черновик ИИ: проверьте имена, сроки и содержание по записи. <a href="/">Обработать другую запись</a></p>
    </main></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    replay_mode = os.environ.get("APP_MODE", "replay") == "replay"
    presets = json.dumps(meeting_presets(), ensure_ascii=False).replace("<", "\\u003c")
    return (asset("index.html").replace("__STYLE__", asset("style.css")).replace("__SCRIPT__", asset("app.js"))
            .replace("__PRESETS__", presets).replace("__REPLAY__", "true" if replay_mode else "false")
            .replace("__MODE_CLASS__", "" if replay_mode else "live")
            .replace("__MODE_LABEL__", "Воспроизведение, не проверка моделей" if replay_mode else "Локальные модели · GPU"))


@app.get("/health")
def health():
    return {"status": "ok", "mode": os.environ.get("APP_MODE", "replay")}


@app.post("/protocol")
def protocol(audio: UploadFile = File(...), meeting_date: date = Form(...),
             participants: str = Form(""), topic: str = Form("")):
    mode = os.environ.get("APP_MODE", "replay")
    if mode not in {"replay", "gpu"}:
        raise HTTPException(503, "Некорректный режим сервиса")
    if not processing.acquire(blocking=False):
        raise HTTPException(409, "Уже обрабатывается запись, повторите после завершения")
    try:
        with tempfile.TemporaryDirectory(prefix="meeting-") as directory:
            path = Path(directory) / Path(audio.filename or "recording.mp3").name
            total = 0
            with path.open("wb") as target:
                while chunk := audio.file.read(1024 * 1024):
                    total += len(chunk)
                    if total > 100 * 1024 * 1024:
                        raise HTTPException(413, "Запись больше 100 МБ")
                    target.write(chunk)
            context = resolve_context(path, participants, topic)
            if mode == "replay":
                result = replay(path, context=context)
                if result.meeting_date != meeting_date:
                    raise ValueError("Для сохранённых примеров дата встречи 2026-09-23")
            else:
                from .pipeline import process
                result = process(path, meeting_date, context)
            key = uuid.uuid4().hex
            results[key] = (result, mode == "replay")
            while len(results) > MAX_RESULTS:
                results.popitem(last=False)
            return RedirectResponse(f"/result/{key}", status_code=303)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    finally:
        audio.file.close()
        processing.release()


def stored(key: str) -> tuple[Protocol, bool]:
    if key not in results:
        raise HTTPException(404, "Результат не найден: после перезапуска сервиса обработайте запись заново")
    return results[key]


@app.get("/result/{key}.docx")
def result_docx(key: str):
    protocol, replay_mode = stored(key)
    return Response(export_docx(protocol, replay_mode=replay_mode),
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": 'attachment; filename="protocol.docx"'})


@app.get("/result/{key}", response_class=HTMLResponse)
def result_page(key: str):
    protocol, replay_mode = stored(key)
    return render_result(key, protocol, replay_mode, date.today())
