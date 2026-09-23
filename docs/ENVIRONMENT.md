# Проверенная среда запуска

Этот файл описывает машину, на которой проверен полный GPU-путь (реальные ASR, диаризация и LLM), и как получить такую же. Путь без GPU (воспроизведение) описан в README и работает на любом ноутбуке с uv.

Снимок снят скриптом `scripts/env_report.sh` 23.09.2026, журнал: [docs/runs](runs/) (`*-env-report-brev.log`).

## Машина

| Параметр | Значение |
|---|---|
| Провайдер | NVIDIA Brev, облако AWS, регион `us-west-2` |
| Тип инстанса | `g7e.2xlarge`, $4.08 в час (в остановленном виде $0.04 в час) |
| GPU | NVIDIA RTX PRO 6000 Blackwell Server Edition, 96 ГБ VRAM (compute capability 12.0) |
| Драйвер / CUDA | 595.91.07 / CUDA 13.2 (драйвер) |
| CPU / RAM | 8 vCPU / 62 ГБ |
| Диск | 248 ГБ; на чистой машине после полного запуска занято на 71 ГБ больше (образы 42,6 ГБ, веса моделей в `.cache`) |
| ОС | Ubuntu 22.04.5 LTS, ядро 6.8.0-1063-aws |
| Docker | 29.8.1, Docker Compose v5.5.1 |
| NVIDIA Container Toolkit | 1.20.1 |

Brev использован как эмуляция сервера заказчика (закрытый контур): все модели работают в собственных контейнерах на этой машине, аудио и текст не уходят во внешние API. Минимальные требования для других GPU не измерялись; vLLM занимает 45% видеопамяти (`--gpu-memory-utilization 0.45`), ASR и диаризация работают в той же видеокарте.

## Что скачивается при первом запуске

| Компонент | Размер | Откуда |
|---|---|---|
| Образ `vllm/vllm-openai` (digest закреплён в `compose.yaml`) | 30.7 ГБ | Docker Hub |
| Образ приложения (собирается из `Dockerfile`, зависимости из `uv.lock`) | 11.8 ГБ | PyPI, download.pytorch.org |
| Qwen3.8-27B-NVFP4 (ревизия в `compose.yaml`) | 21 ГБ | Hugging Face |
| faster-whisper large-v3 | 2.9 ГБ | Hugging Face |
| SeamlessM4T-v2-large | 8.7 ГБ | Hugging Face |
| SpeechBrain ECAPA | около 90 МБ | Hugging Face |

Аккаунты и токены не нужны: все модели открыты для скачивания без входа. Ревизии всех весов закреплены в коде и `compose.yaml`.

## Как получить такую же машину

1. В консоли NVIDIA Brev создать GPU-инстанс с RTX PRO 6000 Blackwell (AWS `g7e.2xlarge`), образ Ubuntu 22.04 с Docker и NVIDIA Container Toolkit (стандартный VM-режим Brev).
2. Подключиться: `brev refresh`, затем `ssh <имя-инстанса>`.
3. Проверить конфигурацию: `bash scripts/env_report.sh` после клонирования репозитория.
4. Дальше строго по README, раздел про GPU-путь (`docker compose`).
5. После проверки остановить инстанс в консоли Brev (Stop), иначе оплата продолжается.

## Время работы на этой машине

| Операция | Время |
|---|---|
| Обработка Совещания №1 (около 4,5 мин аудио) при запущенном стеке | 45-65 с |
| Обработка Совещания №2 (около 3,5 мин аудио) | 32-52 с |
| `kz_01` (70 с, казахский, с SeamlessM4T) | 34-63 с (больше при первой загрузке Seamless) |
| `mix_01` (55 с) | 16-19 с |

## Холодный старт на новой машине

23.09.2026, новый инстанс того же типа без Docker-образов и без uv, команды README строго по порядку ([журнал](runs/1645-fresh-machine-cold-readme.log)). Все шаги завершились успешно.

| Шаг README | Время |
|---|---|
| Установка uv 0.12.18, `uv sync --locked`, оба MP3 в режиме воспроизведения | меньше 10 с |
| `docker compose build app` | 4 мин 22 с |
| `docker compose up -d --wait llm` (скачивание образа vLLM и весов Qwen, загрузка, компиляция) | 10 мин 31 с |
| Совещание №1 на GPU, первый запуск со скачиванием Whisper, Seamless, ECAPA | 3 мин 26 с |
| Совещание №2 на GPU | 1 мин |
| `verify_outputs.py`, запуск веб-страницы | меньше 30 с |

Итого около 20 минут от пустой машины до готового протокола. Сеть AWS быстрая; на медленном канале скачивание займёт больше, поэтому ожидание vLLM в README увеличено до 1800 с. В этом прогоне команда ещё была с 900 с и уложилась.

## Постоянный dev-стек на Brev (для команды)

Все рабочие прогоны и тесты выполняются на Brev. До первого старта остановите другие vLLM. На сервере для уже скачанных весов задаём `LLM_CACHE_DIR=/home/ubuntu/hf-cache` и `ASR_CACHE_DIR=/home/ubuntu/.cache/huggingface`; на новой машине используются стандартные каталоги из `.env.example`.

```bash
mkdir -p outputs
docker compose -p meeting-dev up -d
```

Между прогонами vLLM остаётся запущенным. После правки кода обновляйте только приложение:

```bash
docker compose -p meeting-dev build app
docker compose -p meeting-dev up -d --no-deps app
bash scripts/check.sh replay
docker compose -p meeting-dev exec -T app bash scripts/gpu-python.sh -m meeting_protocol "docs/Трек 8 Инновации/Совещание №1.mp3" --mode gpu --date 2026-09-23 --output outputs/meeting-1
docker compose -p meeting-dev exec -T app bash scripts/gpu-python.sh -m meeting_protocol "docs/Трек 8 Инновации/Совещание №2.mp3" --mode gpu --date 2026-09-23 --output outputs/meeting-2
docker compose -p meeting-dev exec -T app bash scripts/gpu-python.sh scripts/verify_outputs.py
```

Полный `check.sh gpu` со своим vLLM — только при закрытии этапа и перед кандидатом. Проверка отказывается стартовать, если уже работает контейнер vLLM. Два vLLM одновременно не запускаем:

```bash
docker compose -p meeting-dev stop
bash scripts/check.sh gpu
docker compose -p meeting-dev up -d
```
