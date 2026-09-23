#!/usr/bin/env bash
set -euo pipefail
mode="${1:-all}"
case "$mode" in replay|gpu|all) ;; *) echo 'Использование: bash scripts/check.sh [replay|gpu|all]' >&2; exit 2;; esac
source_root="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
revision="$(git -C "$source_root" rev-parse HEAD)"
check_dir="$(mktemp -d "${TMPDIR:-/tmp}/meeting-check.XXXXXXXX")"
export COMPOSE_PROJECT_NAME="meeting-check-$$"
# Кэш сохраняется между проверками, исходники всегда берутся из свежего клона.
export LLM_CACHE_DIR="${LLM_CACHE_DIR:-$source_root/.cache/llm}"
export ASR_CACHE_DIR="${ASR_CACHE_DIR:-$source_root/.cache/asr}"
compose_started=0
cleanup() {
    if [[ "$compose_started" == 1 ]]; then docker compose down --remove-orphans; fi
    case "$check_dir" in */meeting-check.*) rm -rf -- "$check_dir";; esac
}
trap cleanup EXIT
git clone --quiet --no-hardlinks "$source_root" "$check_dir/repo"
cd "$check_dir/repo"
git checkout --quiet --detach "$revision"
echo "Проверяется коммит $revision; режим $mode"
if [[ "$mode" == replay || "$mode" == all ]]; then
    uv sync --locked
    uv run --locked python -m meeting_protocol 'docs/Трек 8 Инновации/Совещание №1.mp3' --output outputs/meeting-1
    uv run --locked python -m meeting_protocol 'docs/Трек 8 Инновации/Совещание №2.mp3' --output outputs/meeting-2
    uv run --locked python -m pytest -q
    uv run --locked python scripts/verify_outputs.py
    echo 'PASS replay: не проверка моделей'
fi
if [[ "$mode" == gpu || "$mode" == all ]]; then
    # Dev vLLM останавливает оператор; проверка не трогает чужие контейнеры.
    running_llm="$(docker ps -q | while IFS= read -r container_id; do
        docker inspect --format '{{.Name}} {{.Config.Image}} {{index .Config.Labels "com.docker.compose.service"}}' "$container_id"
    done | awk 'tolower($0) ~ /vllm/ || $NF == "llm"')"
    if [[ -n "$running_llm" ]]; then
        echo 'GPU-проверка не запущена: уже работает vLLM. Сначала: docker compose -p meeting-dev stop' >&2
        echo "$running_llm" >&2
        exit 1
    fi
    mkdir -p outputs
    docker compose build app
    compose_started=1
    docker compose up -d --wait --wait-timeout 900 llm
    docker compose run --rm app -m meeting_protocol 'docs/Трек 8 Инновации/Совещание №1.mp3' --mode gpu --date 2026-09-23 --output outputs/meeting-1
    docker compose run --rm app -m meeting_protocol 'docs/Трек 8 Инновации/Совещание №2.mp3' --mode gpu --date 2026-09-23 --output outputs/meeting-2
    docker compose run --rm app scripts/verify_outputs.py
    echo 'PASS gpu: реальный запуск ASR и LLM'
fi
