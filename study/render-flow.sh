#!/usr/bin/env bash
# 重新渲染流程图 PNG。源文件：images/agentscope-agent-flow.html
# 用法：./render-flow.sh
set -euo pipefail
cd "$(dirname "$0")"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME" --headless=new --disable-gpu --hide-scrollbars \
  --force-device-scale-factor=2 --window-size=1080,760 \
  --screenshot="images/agentscope-agent-flow.png" \
  "file://$(pwd)/images/agentscope-agent-flow.html"
echo "已更新 images/agentscope-agent-flow.png"
