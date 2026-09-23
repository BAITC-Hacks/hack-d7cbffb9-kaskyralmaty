"""Минимальный вход в общий конвейер; сервер слушает localhost по README."""
import os
import tempfile
import threading
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from .protocol import export_docx, replay

app = FastAPI(title="Протокол совещания")
processing = threading.Lock()


@app.get("/", response_class=HTMLResponse)
def index():
    mode = os.environ.get("APP_MODE", "replay")
    label = "Воспроизведение — не проверка моделей" if mode == "replay" else "Локальные модели на GPU"
    return f"""<!doctype html><html lang="ru"><meta charset="utf-8"><title>Протокол совещания</title>
    <style>body{{font:18px system-ui;max-width:760px;margin:60px auto;padding:20px;color:#17302b;background:#f5f5ef}}form{{display:grid;gap:20px;padding:28px;background:white;border-radius:16px}}button{{padding:14px;background:#195e4b;color:white;border:0;border-radius:8px;font-size:18px}}</style>
    <h1>Протокол совещания</h1><p>{label}</p>
    <p>MP3 → транскрипт → поручения → DOCX. В этапе 1 говорящие ещё не разделяются.</p>
    <form action="/protocol" method="post" enctype="multipart/form-data">
    <label>Аудиозапись <input name="audio" type="file" accept="audio/*" required></label>
    <label>Дата встречи <input name="meeting_date" type="date" value="2026-09-23" required></label>
    <button>Получить DOCX</button><p>Обработка может занять несколько минут. В режиме воспроизведения доступны только два комплектных MP3.</p></form></html>"""


@app.get("/health")
def health():
    return {"status": "ok", "mode": os.environ.get("APP_MODE", "replay")}


@app.post("/protocol")
def protocol(audio: UploadFile = File(...), meeting_date: date = Form(...)):
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
            if mode == "replay":
                result = replay(path)
                if result.meeting_date != meeting_date:
                    raise ValueError("Для сохранённых примеров дата встречи — 2026-09-23")
            else:
                from .pipeline import process
                result = process(path, meeting_date)
            return Response(export_docx(result, replay_mode=mode == "replay"),
                            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            headers={"Content-Disposition": 'attachment; filename="protocol.docx"'})
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    finally:
        audio.file.close()
        processing.release()
