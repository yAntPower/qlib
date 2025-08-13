#!/bin/bash
# 停止生产级ML策略

echo "正在停止生产级ML策略..."

# 查找并终止进程
PIDS=$(pgrep -f "production_ml_strategy.py")

if [ -z "$PIDS" ]; then
    echo "❌ 生产级ML策略未运行"
else
    for PID in $PIDS; do
        kill $PID
        echo "✅ 已停止进程 PID: $PID"
    done
fi