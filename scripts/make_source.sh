#!/bin/bash
set -eou pipefail

git2md naive_backlink \
  --ignore __pycache__ \
  --output SOURCE.md

