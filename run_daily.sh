#!/usr/bin/env bash
# 원/달러 리포트 일일 갱신. cron 에서 호출된다.
# 환경변수: FX_SKIP_CLAUDE=1 분석 재작성 생략 · FX_MODEL 분석 모델(기본 sonnet)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export HOME="${HOME:-/home/yms}"

mkdir -p logs
LOG="logs/$(date +%Y-%m).log"
say(){ printf '%s  %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }

say "===== run start ====="
rc_data=0; rc_nar=0

python3 build/fetch_data.py >> "$LOG" 2>&1 || rc_data=$?
[ $rc_data -ne 0 ] && say "WARN 데이터 수집 실패 (rc=$rc_data) — 직전 data.json 유지"

if [ "${FX_SKIP_CLAUDE:-0}" != "1" ]; then
  python3 build/update_narrative.py >> "$LOG" 2>&1 || rc_nar=$?
  [ $rc_nar -ne 0 ] && say "WARN 분석 재작성 실패 (rc=$rc_nar) — 직전 narrative.json 유지"
else
  say "SKIP 분석 재작성 (FX_SKIP_CLAUDE=1)"
fi

if ! python3 build/render.py >> "$LOG" 2>&1; then
  say "FATAL 렌더 실패 — 배포 중단"; say "===== run end (fatal) ====="; exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -qm "일일 갱신 $(date '+%Y-%m-%d') — $(python3 -c "
import json;d=json.load(open('data.json'));print(f\"{d['latest']['c']:,.2f} ({d['latest']['chg']:+.2f})\")")"
  if git push -q origin main 2>>"$LOG"; then
    say "OK 배포 완료 → https://yms9654.github.io/fx-report/"
  else
    say "ERROR git push 실패 — 다음 실행에서 재시도"
  fi
else
  say "변경 없음 — 커밋 생략"
fi

say "===== run end ====="
