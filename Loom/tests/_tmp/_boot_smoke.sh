#!/bin/bash
cd "/d/my-project - 副本/Loom(py源代码-工作区)/Loom" || exit 9
LOG=/tmp/loom_boot.log
> "$LOG"
py -3.12 Loom.py --ui qt > "$LOG" 2>&1 &
PID=$!
sleep 15
if kill -0 $PID 2>/dev/null; then
  echo "RESULT=ALIVE (引擎启动成功, 15 秒内未退出)"
  kill -9 $PID 2>/dev/null
  wait $PID 2>/dev/null
else
  wait $PID
  echo "RESULT=DIED (退出码 $?)"
fi
echo "--- 日志尾部 ---"
tail -30 "$LOG"
