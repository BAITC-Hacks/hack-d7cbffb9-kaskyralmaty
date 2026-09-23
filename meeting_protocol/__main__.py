"""CLI для одного аудиофайла, одинаковый результат в двух режимах."""
import argparse
from datetime import date
from pathlib import Path

from .protocol import export_docx, replay


def main():
    parser = argparse.ArgumentParser(description="MP3 → протокол и DOCX")
    parser.add_argument("audio", type=Path)
    parser.add_argument("--mode", choices=["replay", "gpu"], default="replay")
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--output", type=Path, default=Path("outputs/protocol"))
    args = parser.parse_args()
    if args.mode == "gpu" and args.date is None:
        parser.error("Для GPU укажите дату встречи --date YYYY-MM-DD")
    if args.mode == "replay":
        protocol = replay(args.audio)
        if args.date and args.date != protocol.meeting_date:
            parser.error("Дата сохранённого результата отличается: воспроизведение не пересчитывает протокол")
        print("Воспроизведение — не проверка моделей")
    else:
        from .pipeline import process
        protocol = process(args.audio, args.date)
        print("Реальный запуск ASR и LLM")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(protocol.model_dump_json(indent=2), encoding="utf-8")
    args.output.with_suffix(".docx").write_bytes(export_docx(protocol, replay_mode=args.mode == "replay"))
    print(f"Реплик: {len(protocol.segments)}; поручений: {len(protocol.assignments)}; DOCX: {args.output.with_suffix('.docx')}")


if __name__ == "__main__":
    main()
