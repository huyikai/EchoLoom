#!/usr/bin/env bash
# push 重试：DNS/网络抖动时循环重试，成功或 8 轮后退出
cd /d/develop/EchoLoom || exit 1
for i in 1 2 3 4 5 6 7 8; do
  out=$(git push https://github.com/huyikai/EchoLoom.git main 2>&1 | tail -1)
  echo "[$i] $out"
  case "$out" in
    *"main -> main"*|*Everything*|*up-to-date*) echo PUSH_OK; exit 0 ;;
  esac
  sleep 90
done
echo PUSH_FAILED_ALL
