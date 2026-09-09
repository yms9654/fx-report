#!/usr/bin/env python3
"""claude -p 로 분석(narrative.json)을 재작성. 실패하면 직전 분석을 그대로 유지한다."""
import json, os, subprocess, sys, pathlib, datetime, zoneinfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from analysis import technicals

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAR = ROOT / "narrative.json"
KST = zoneinfo.ZoneInfo("Asia/Seoul")
MODEL = os.environ.get("FX_MODEL", "sonnet")
TIMEOUT = int(os.environ.get("FX_TIMEOUT", "600"))

REQUIRED = ["headline", "sub", "verdict", "forces", "scenario",
            "ladder", "calendar", "tips", "sources", "triggers"]


def build_prompt(data, prev, tlog):
    s = data["series"]
    recent = " ".join(f"{r['d'][5:]}:{r['c']:.2f}" for r in s[-15:])
    t = technicals(data.get("history") or s)
    tech = (f"- 추세: {t['tlabel']} (하락신호 "
            f"{sum(1 for _, v in t['signals'] if v < 0)}/{len(t['signals'])})\n"
            f"- MA20 {t['ma20']:,.1f} (종가 대비 {t['vs20']:+.2f}%) · "
            f"MA60 {t['ma60']:,.1f} ({t['vs60']:+.2f}%)\n"
            f"- RSI(14) {t['rsi']:.1f} ({t['mom']})"
            + (f" · 볼린저 %B {t['bb']['pctb']:.2f}" if t['bb'] else ""))
    hist = "\n".join(
        f"  {e['d']}  종가 {e['px']:,.2f}  손절 {e['stop']:,.0f}  1차 {e['t1']:,.0f}"
        for e in tlog[-6:]) or "  (이력 없음)"
    return f"""너는 원/달러 환율 매도 타이밍 리포트를 매일 갱신하는 애널리스트다.
오늘은 {datetime.datetime.now(KST):%Y-%m-%d}이다.

## 확정 데이터 (이 숫자는 신뢰하고 그대로 쓸 것)
- 출처: {data['source']}
- 최신 종가: {data['latest']['d']} = {data['latest']['c']:,.2f} (전일비 {data['latest']['chg']:+.2f})
- 52주 범위: {data['w52']['lo']:,.2f} ~ {data['w52']['hi']:,.2f}
- 최근 {data['span_days']}영업일 변화: {data['span_pct']:+.2f}%
- 최근 15영업일 종가: {recent}

## 기술적 지표 (가격에서만 계산됨, 반박 불가)
{tech}

## 내가 지난 며칠 제시한 계획
{hist}

## 계획은 이미 동결되어 있다
사다리 눈금·손절선·도달확률은 계획 시작일에 고정된 plan.json 에서 나오고,
네가 쓰는 숫자는 페이지의 계획 섹션을 바꾸지 않는다. 참고 견해로만 표시된다.
그러니 "계획을 지금 가격에 맞춘다"는 동기로 숫자를 움직이지 마라.

## 반드시 지킬 것 — 손절선을 가격에 맞춰 내리지 말 것
위 이력에서 손절선이 계속 낮아졌다면 그것은 잘못이다. 손절은 "여기까지 오면 판단이 틀린
것으로 보고 정리한다"는 선이므로, 가격이 그쪽으로 갔다고 선을 옮기면 아무 의미가 없다.
- 직전 손절선이 이미 닿았거나 뚫렸다면, 낮추지 말고 그 사실을 결론에 명시하라.
- 손절선을 내리려면 가격이 내렸다는 것 말고 **새로운 근거**가 있어야 한다. 없으면 유지하라.
- 기술적 추세가 하락인데 "기다린다"를 반복하고 있다면, 계획 자체가 틀렸을 가능성을 검토하라.

## 할 일
1. WebSearch/WebFetch로 원/달러 환율, 연준·한국은행 정책, 국내 수급을 오늘 기준으로 조사한다.
   위 기술적 지표와 뉴스가 어긋나면 그 사실을 결론에 반영한다.
2. 아래 '직전 분석'을 오늘의 가격과 새 뉴스에 맞게 고쳐 쓴다. 가격이 크게 움직였거나 전제가 깨졌으면 결론·트리거·사다리 숫자를 실제로 바꿔라. 변한 게 없으면 유지해도 된다.
3. 결과를 JSON 하나로만 출력한다.

## 직전 분석
{json.dumps(prev, ensure_ascii=False)}

## 출력 규칙 (엄수)
- 출력은 JSON 객체 하나뿐. 설명·인사·마크다운 코드펜스 금지.
- 스키마·키 이름·구조는 직전 분석과 완전히 동일하게 유지한다. 값만 바꾼다.
- 문자열 값 안에서는 <b> <span class="cut"> 만 허용. 다른 태그 금지.
- triggers.stop < triggers.t1 < triggers.t2 여야 한다.
- ladder.lo < 모든 zone.lo, ladder.hi > 모든 zone.hi. 현재가가 ladder 범위 안에 들어와야 한다.
- ladder.zones 의 kind 는 "sell" 또는 "cut" 만.
- events 는 차트 주석이며 키는 "MM/DD" 형식이고, 위 15영업일 목록에 있는 날짜만 쓴다. 최대 4개.
- scenario.up_prob 는 0~100 정수.
- 숫자는 문자열이 아니라 숫자로 쓴다.
- sources 는 실제로 확인한 URL 3~8개.
- 톤: 단정하고 구체적으로. 실행 가능한 가격과 날짜를 반드시 포함.

## 분량 제한 (페이지가 복잡해지지 않도록 엄수)
- ladder.zones[].note: 각 **60자 이내** 한 문장. 페이지에서 2줄로 잘린다.
- forces.down / forces.up: 각 **최대 4개**. 항목당 60자 이내.
- calendar: **최대 4개**. note 는 40자 이내.
- tips: **최대 3개**.
- scenario.up_text / dn_text: 각 80자 이내.
- sub, headline: headline 은 20자 이내, sub 는 90자 이내.
"""


def validate(n, px):
    for k in REQUIRED:
        if k not in n:
            raise ValueError(f"missing key: {k}")
    t = n["triggers"]
    stop, t1, t2 = float(t["stop"]), float(t["t1"]), float(t["t2"])
    if not stop < t1 < t2:
        raise ValueError(f"trigger order broken: {stop}/{t1}/{t2}")
    lad = n["ladder"]
    lo, hi = float(lad["lo"]), float(lad["hi"])
    if not lo < hi:
        raise ValueError("ladder range broken")
    if not lo <= px <= hi:
        raise ValueError(f"current price {px} outside ladder {lo}-{hi}")
    if not lad.get("zones"):
        raise ValueError("no ladder zones")
    for z in lad["zones"]:
        if z.get("kind") not in ("sell", "cut"):
            raise ValueError(f"bad zone kind: {z.get('kind')}")
        if not lo <= float(z["lo"]) < float(z["hi"]) <= hi:
            raise ValueError(f"zone outside ladder: {z['lo']}-{z['hi']}")
    p = n["scenario"]["up_prob"]
    if not isinstance(p, int) or not 0 <= p <= 100:
        raise ValueError(f"bad up_prob: {p}")
    if len(n["sources"]) < 3:
        raise ValueError("too few sources")
    return n


def main():
    data = json.loads((ROOT / "data.json").read_text(encoding="utf-8"))
    prev = json.loads(NAR.read_text(encoding="utf-8"))
    px = float(data["latest"]["c"])
    tlp = ROOT / "triggers_log.json"
    tlog = []
    if tlp.exists():
        try:
            tlog = json.loads(tlp.read_text(encoding="utf-8"))
        except Exception:                                    # noqa: BLE001
            tlog = []

    env = {"HOME": os.path.expanduser("~"),
           "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "LANG": "ko_KR.UTF-8"}
    cmd = ["claude", "-p", build_prompt(data, prev, tlog),
           "--output-format", "json", "--model", MODEL,
           "--allowedTools", "WebSearch", "WebFetch"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=TIMEOUT, env=env, cwd=str(ROOT))
        if r.returncode != 0:
            raise RuntimeError(f"claude exit {r.returncode}: {r.stderr[-400:]}")
        env_out = json.loads(r.stdout)
        txt = (env_out.get("result") or "").strip()
        if txt.startswith("```"):
            txt = txt.split("```")[1]
            txt = txt[4:] if txt.lower().startswith("json") else txt
        txt = txt[txt.index("{"):txt.rindex("}") + 1]
        new = validate(json.loads(txt), px)
    except Exception as e:                                   # noqa: BLE001
        print(f"NARRATIVE FAILED ({type(e).__name__}): {e}", file=sys.stderr)
        prev["degraded"] = True
        NAR.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
        return 2                                             # 렌더는 계속 진행

    new["generated_at"] = datetime.datetime.now(KST).isoformat(timespec="seconds")
    new.pop("degraded", None)
    tmp = NAR.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(NAR)
    cost = env_out.get("total_cost_usd")
    print(f"OK narrative updated | model={MODEL} | "
          f"band {new['verdict']['band_lo']}-{new['verdict']['band_hi']} | "
          f"triggers {new['triggers']} | cost ${cost:.3f}" if cost else "OK narrative updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
