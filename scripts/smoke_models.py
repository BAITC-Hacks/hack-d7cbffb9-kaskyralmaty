"""Проверка реального распознавания на GPU, без оценки языковой точности."""
import argparse
import json
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", choices=["whisper", "seamless"])
    parser.add_argument("audio", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    from faster_whisper.audio import decode_audio
    audio = decode_audio(str(args.audio), sampling_rate=16000)[:20 * 16000]
    if args.engine == "whisper":
        import ctranslate2
        from faster_whisper import WhisperModel
        print("CTranslate2", ctranslate2.__version__, "CUDA devices", ctranslate2.get_cuda_device_count(), flush=True)
        model = WhisperModel("large-v3", device="cuda", compute_type="float16")
        segments, info = model.transcribe(audio, beam_size=1)
        text = " ".join(s.text for s in segments)
        result = {"engine": args.engine, "language": info.language, "text": text}
    else:
        import torch
        from transformers import AutoProcessor, SeamlessM4Tv2ForSpeechToText
        print("PyTorch", torch.__version__, "CUDA", torch.version.cuda, "GPU", torch.cuda.get_device_name(), flush=True)
        processor = AutoProcessor.from_pretrained("facebook/seamless-m4t-v2-large")
        model = SeamlessM4Tv2ForSpeechToText.from_pretrained(
            "facebook/seamless-m4t-v2-large", torch_dtype=torch.float16
        ).to("cuda").eval()
        inputs = processor(audio=audio, sampling_rate=16000, return_tensors="pt").to("cuda")
        inputs["input_features"] = inputs["input_features"].to(torch.float16)
        with torch.inference_mode():
            tokens = model.generate(**inputs, tgt_lang="kaz", max_new_tokens=256)
        text = processor.batch_decode(tokens, skip_special_tokens=True)[0]
        result = {"engine": args.engine, "language": "kaz", "text": text}
    if not text.strip():
        raise RuntimeError("Модель не выдала текст")
    result["seconds"] = round(time.monotonic() - started, 2)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
