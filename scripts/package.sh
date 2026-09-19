#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p output
COPYFILE_DISABLE=1 tar --no-xattrs --exclude='__pycache__' --exclude='*.pyc' --exclude='node_modules' --exclude='dashboard.sh' --exclude='enable-ax41-dashboard.sh' -czf output/crypto-oracle-server.tar.gz \
  pyproject.toml uv.lock .python-version .env.example .dockerignore Dockerfile compose.yaml \
  oracle jev tests scripts README.md PAPER.md LEARNING.md RESEARCH_FORECAST_LEARNING.md
printf '%s\n' 'Created output/crypto-oracle-server.tar.gz (source only, no secrets or research data).'
