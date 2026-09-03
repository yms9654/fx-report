#!/usr/bin/env bash
# 익명 피드백 Worker 배포. 브라우저 로그인과 토큰 입력만 직접 하면 된다.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
W="npx --yes wrangler@latest"

echo "═══ 1/5  Cloudflare 로그인 ═══"
if [ -d "$HOME/.wrangler/config" ]; then
  echo "  이미 로그인됨 — 건너뜁니다."
else
  echo "  브라우저가 열립니다. Cloudflare 계정으로 로그인하세요 (무료)."
  (cd worker && $W login)
fi

echo
echo "═══ 2/5  레이트리밋용 KV 생성 (시간당 5건 제한) ═══"
if grep -q '^\[\[kv_namespaces\]\]' worker/wrangler.toml; then
  echo "  이미 설정됨 — 건너뜁니다."
else
  OUT=$(cd worker && $W kv namespace create RL 2>&1) || { echo "$OUT"; echo "  KV 생성 실패 — 레이트리밋 없이 진행합니다."; OUT=""; }
  ID=$(echo "$OUT" | grep -oE '"?id"?\s*[:=]\s*"[a-f0-9]{32}"' | grep -oE '[a-f0-9]{32}' | head -1)
  if [ -n "$ID" ]; then
    printf '\n[[kv_namespaces]]\nbinding = "RL"\nid = "%s"\n' "$ID" >> worker/wrangler.toml
    echo "  KV 연결: $ID"
  else
    echo "  id 를 자동으로 못 읽었습니다. 레이트리밋 없이 진행합니다."
  fi
fi

echo
echo "═══ 3/5  GitHub 토큰 등록 ═══"
echo "  아래에서 fine-grained 토큰을 만드세요:"
echo "    https://github.com/settings/personal-access-tokens/new"
echo "    Repository access : Only select repositories → yms9654/fx-report"
echo "    Permissions       : Issues → Read and write"
echo "  만든 토큰을 다음 프롬프트에 붙여넣으세요 (화면에 표시되지 않습니다)."
(cd worker && $W secret put GH_TOKEN)

echo
echo "═══ 4/5  Worker 배포 ═══"
DEP=$(cd worker && $W deploy 2>&1 | tee /dev/stderr)
URL=$(echo "$DEP" | grep -oE 'https://[a-z0-9.-]+\.workers\.dev' | head -1)
if [ -z "$URL" ]; then
  read -rp "  배포 URL 을 자동으로 못 읽었습니다. 직접 붙여넣으세요: " URL
fi
echo "  엔드포인트: $URL"

echo
echo "═══ 5/5  페이지에 연결 ═══"
python3 - "$URL" <<'PY'
import json, pathlib, sys
p = pathlib.Path("config.json")
c = json.loads(p.read_text()) if p.exists() else {}
c["feedback_endpoint"] = sys.argv[1].rstrip("/")
p.write_text(json.dumps(c, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("  config.json 갱신:", c["feedback_endpoint"])
PY
python3 build/render.py
git add -A && git commit -qm "익명 피드백 엔드포인트 연결" && git push -q origin main
echo
echo "완료. 익명 제출 확인:"
echo "  curl -X POST $URL -H 'content-type: application/json' \\"
echo "    -d '{\"kind\":\"제안\",\"text\":\"테스트\",\"ctx\":[[\"리포트\",\"수동확인\"]],\"width\":1440}'"
