#!/usr/bin/env bash
# Print the machine configuration the GPU path was verified on (see docs/ENVIRONMENT.md).
# Usage on the GPU machine: bash scripts/env_report.sh | tee docs/runs/$(date +%H%M)-env-report.log
set -uo pipefail
row() { printf '%-26s %s\n' "$1" "$(eval "$2" 2>/dev/null | head -1 || true)"; }
echo "# Environment report $(date '+%F %T %Z')"
row "Commit" "git rev-parse --short HEAD"
row "Cloud instance type" "curl -s -m 2 http://169.254.169.254/latest/meta-data/instance-type"
row "Cloud region" "curl -s -m 2 http://169.254.169.254/latest/meta-data/placement/region"
row "OS" "lsb_release -ds || sed -n 's/^PRETTY_NAME=//p' /etc/os-release"
row "Kernel" "uname -r"
row "CPU cores" "nproc"
row "RAM" "free -g | awk '/Mem/{print \$2\" GB\"}'"
row "Free disk (repo)" "df -h . | awk 'NR==2{print \$4\" free of \"\$2}'"
row "GPU" "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader"
row "NVIDIA driver" "nvidia-smi --query-gpu=driver_version --format=csv,noheader"
row "CUDA (driver)" "nvidia-smi | grep -o 'CUDA Version: [0-9.]*'"
row "Docker" "docker --version"
row "Docker Compose" "docker compose version"
row "NVIDIA Container Toolkit" "nvidia-ctk --version"
row "uv" "uv --version"
row "Git" "git --version"
