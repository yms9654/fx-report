#!/usr/bin/env bash
# 차트를 실제로 렌더해서 눈으로 확인한다. 폰트·네트워크는 끊는다.
# 사용: ./build/shot.sh [출력디렉터리]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
OUT="${1:-/tmp/fx-shot}"; mkdir -p "$OUT"
python3 - "$OUT" <<'PY'
import re, sys, pathlib
h = pathlib.Path("docs/index.html").read_text(encoding="utf-8")
h = re.sub(r'<link[^>]*fonts\.(googleapis|gstatic)[^>]*>', '', h)
h = re.sub(r'<link rel="preconnect"[^>]*>', '', h)
h = h.replace("</body>", """<script>
document.querySelectorAll('.metabar,.hero,section').forEach(el=>{
  if(!el.querySelector||!el.querySelector('#svg')) el.style.display='none';});
document.querySelector('footer').style.display='none';
document.querySelector('.wrap').style.paddingTop='0';
</script></body>""")
pathlib.Path(sys.argv[1], "chartonly.html").write_text(h, encoding="utf-8")
PY
for cfg in "desktop 1400 700" "mobile 390 560"; do
  set -- $cfg
  timeout 70 google-chrome --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
    --disable-remote-fonts --virtual-time-budget=3000 --window-size="$2,$3" \
    --screenshot="$OUT/$1.png" "file://$OUT/chartonly.html" >/dev/null 2>&1
  echo "  $1 → $OUT/$1.png"
done
