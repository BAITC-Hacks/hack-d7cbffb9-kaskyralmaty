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

STYLE = """
:root{--bg:#f5f5ef;--card:#fff;--ink:#17302b;--muted:#5d6f6a;--line:#dfe3dc;--accent:#195e4b;--hl:#fff3b0;
--late:#b42318;--soon:#b54708;--ok:#1a7f37;--none:#667085}
@media (prefers-color-scheme:dark){:root{--bg:#111816;--card:#1a2421;--ink:#e6eeeb;--muted:#9fb1ab;--line:#2c3a36;
--accent:#4fb393;--hl:#4a4217;--late:#f97066;--soon:#fdb022;--ok:#47cd89;--none:#98a2b3}}
*{box-sizing:border-box}body{font:16px/1.5 system-ui;margin:0;padding:24px 16px;color:var(--ink);background:var(--bg)}
main{max-width:1000px;margin:0 auto}section{background:var(--card);border-radius:14px;padding:20px;margin:16px 0}
h1{margin:0 0 4px}h2{margin:0 0 12px;font-size:20px}.muted{color:var(--muted)}
.bar{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.btn{display:inline-block;padding:10px 16px;border-radius:8px;
background:var(--accent);color:#fff;text-decoration:none;font-weight:600}.btn.ghost{background:none;color:var(--accent);border:1px solid var(--accent)}
.warn{background:var(--hl);padding:10px 14px;border-radius:8px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--line);vertical-align:top}
.scroll{overflow-x:auto}.badge{font-size:13px;font-weight:600;white-space:nowrap}
.s-late{color:var(--late)}.s-soon{color:var(--soon)}.s-ok{color:var(--ok)}.s-none{color:var(--none)}
.ref{margin-right:6px;color:var(--accent)}.seg{padding:6px 8px;border-radius:6px;scroll-margin-top:80px}
.seg:target{background:var(--hl)}.who{font-weight:600}.t{color:var(--muted);font-variant-numeric:tabular-nums;margin-right:8px}
"""
STATUS_CLASS = {"просрочено": "s-late", "скоро срок": "s-soon", "в работе": "s-ok", "без даты": "s-none"}


def render_result(key: str, protocol: Protocol, replay_mode: bool, as_of: date) -> str:
    rows = "".join(
        f"<tr><td>{escape(a.responsible or 'Не указан')}</td><td>{escape(a.task)}</td>"
        f"<td>{escape(a.deadline_text or 'Не указан')}</td>"
        f"<td>{a.deadline_date.strftime('%d.%m.%Y') if a.deadline_date else '—'}</td>"
        f"<td class='badge {STATUS_CLASS[a.status(as_of)]}'>{a.status(as_of)}</td>"
        f"<td>{''.join(f'<a class=ref href=#seg-{i}>→ #{i}</a>' for i in a.evidence)}</td></tr>"
        for a in protocol.assignments)
    transcript = "".join(
        f"<div class=seg id=seg-{s.id}><span class=t>{int(s.start // 60):02d}:{int(s.start % 60):02d}</span>"
        f"<span class=who>{escape(protocol.speaker_title(s.speaker))}:</span> {escape(s.text)} <span class=muted>#{s.id}</span></div>"
        for s in protocol.segments)
    speakers = "; ".join(escape(protocol.speaker_title(s.label)) for s in protocol.speakers) or "не определены"
    notice = "<p class=warn>Воспроизведение заранее вычисленного результата — не проверка моделей.</p>" if replay_mode else ""
    return f"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Протокол совещания</title><style>{STYLE}</style><main>
    <section><h1>Протокол совещания</h1>
    <p class=muted>{escape(protocol.source_name)} · дата встречи {protocol.meeting_date:%d.%m.%Y}{' · ' + escape(protocol.context.topic) if protocol.context.topic else ''}</p>
    {notice}<div class=bar><a class=btn href="/result/{key}.docx">Скачать DOCX</a><a class="btn ghost" href="/">Новая запись</a></div></section>
    <section><h2>Поручения ({len(protocol.assignments)})</h2><p class=muted>Статус на {as_of:%d.%m.%Y}: «скоро срок» — осталось не больше 3 дней.
    Нажмите «→ #N», чтобы увидеть реплику, из которой взято поручение.</p>
    <div class=scroll><table><tr><th>Кто</th><th>Что</th><th>Срок (как сказано)</th><th>Дата</th><th>Статус</th><th>Источник</th></tr>{rows}</table></div></section>
    <section><h2>Саммари</h2><p>{escape(protocol.summary or 'Не сформировано')}</p></section>
    <section><h2>Транскрипт</h2><p class=muted>Говорящие: {speakers}. Метки — по голосу, имена — по обращениям в разговоре.</p>{transcript}</section>
    <p class=muted>Черновик ИИ: проверьте имена, сроки и содержание по записи.</p></main></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    mode = os.environ.get("APP_MODE", "replay")
    label = "Воспроизведение — не проверка моделей" if mode == "replay" else "Локальные модели на GPU"
    presets = json.dumps(meeting_presets(), ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!doctype html><html lang="ru"><meta charset="utf-8"><title>Протокол совещания</title>
    <style>body{{font:18px system-ui;max-width:760px;margin:60px auto;padding:20px;color:#17302b;background:#f5f5ef}}form{{display:grid;gap:20px;padding:28px;background:white;border-radius:16px}}button{{padding:14px;background:#195e4b;color:white;border:0;border-radius:8px;font-size:18px}}</style>
    <h1>Протокол совещания</h1><p>{label}</p>
    <p>Запись → транскрипт с говорящими → поручения «кто / что / срок» → DOCX.</p>
    <p style="background:#fff3b0;padding:10px 14px;border-radius:8px">Встреча записывается и транскрибируется ИИ — объявите об этом участникам перед началом записи.</p>
    <form action="/protocol" method="post" enctype="multipart/form-data">
    <label>Аудиозапись <input id="audio" name="audio" type="file" accept="audio/*" required></label>
    <label>Дата встречи <input name="meeting_date" type="date" value="2026-09-23" required></label>
    <label>Тема <input id="topic" name="topic" maxlength="1000" style="width:100%"></label>
    <label>Участники <textarea id="participants" name="participants" rows="6" style="width:100%" placeholder="Каждое ФИО с новой строки"></textarea></label>
    <small>Укажите участников и известных ответственных, в том числе не выступавших. Тема и имена передаются только агенту для разбора, не в распознавание речи. Для двух комплектных MP3 поля заполняются по эталонным протоколам; фамилии, которых нет в источнике, не добавлены.</small>
    <p id="context-note" aria-live="polite"></p>
    <button id="submit">Получить протокол</button><p>Обработка может занять несколько минут. В режиме воспроизведения доступны только два комплектных MP3; изменение темы или участников требует GPU.</p></form>
    <script>
    const presets = {presets};
    let selection = 0;
    document.getElementById('audio').addEventListener('change', async event => {{
      const current = ++selection;
      const file = event.target.files[0];
      const submit = document.getElementById('submit');
      submit.disabled = true;
      try {{
        let preset;
        if (file && file.size <= 100 * 1024 * 1024) {{
          const hash = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
          const digest = Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, '0')).join('');
          preset = presets[digest];
        }}
        if (current !== selection) return;
        document.getElementById('topic').value = preset?.topic || '';
        document.getElementById('participants').value = (preset?.participants || []).join('\\n');
        document.getElementById('context-note').textContent = preset ? 'Тема и имена заполнены: ' + preset.label + '. Проверьте перед отправкой.' : 'Введите тему и участников своей встречи.';
      }} catch {{
        if (current === selection) document.getElementById('context-note').textContent = 'Не удалось заполнить поля автоматически; введите тему и участников вручную.';
      }} finally {{ if (current === selection) submit.disabled = false; }}
    }});
    </script></html>"""


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
                    raise ValueError("Для сохранённых примеров дата встречи — 2026-09-23")
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
