#!/usr/bin/env bash
# 由 .py 源生成 .ipynb，并执行以嵌入输出。
#
#   ./build.sh          # 全部课件
#   ./build.sh 01       # 只处理 01-*
#
# 注意：jupytext 从 .py 重新生成会**丢掉已嵌入的输出**，所以每次都跟着执行一遍。
set -euo pipefail
cd "$(dirname "$0")"

PROJ=..                      # study/ 这个 uv 项目
prefix="${1:-}"

shopt -s nullglob
py_files=( ${prefix}*.py )
if [ ${#py_files[@]} -eq 0 ]; then
  echo "没有匹配的 .py 源（prefix='${prefix}'）" >&2
  exit 1
fi

echo "==> jupytext: .py → .ipynb  (${#py_files[@]} 个)"
uv run --project "$PROJ" jupytext --to notebook "${py_files[@]}"

shopt -s nullglob
nb_files=( ${prefix}*.ipynb )
echo "==> 执行以嵌入输出 (${#nb_files[@]} 个)"
uv run --project "$PROJ" jupyter nbconvert \
  --to notebook --execute --inplace "${nb_files[@]}"

echo "==> 完成"
