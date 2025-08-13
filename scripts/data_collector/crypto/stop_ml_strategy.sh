#!/bin/bash
# 停止ML智能策略

echo "正在停止ML智能策略..."

# 查找并终止进程
PIDS=$(pgrep -f "ml_strategy_analyzer.py")

if [ -z "$PIDS" ]; then
    echo "❌ ML智能策略未运行"
else
    for PID in $PIDS; do
        kill $PID
        echo "✅ 已停止进程 PID: $PID"
    done
fi