#!/usr/bin/env python3
"""계획 기준점(D-0)과 현재 상태를 계산한다.

게이지가 말하려면 기준이 있어야 한다. "몇 퍼센타일", "D-n", "진도"는
전부 '계획을 세운 시점' 대비 값이다. 그 시점을 plan.json 에 고정한다.
이 파일은 자동으로 덮어쓰지 않는다 — 새 창을 열려면 명시적으로 재설정한다.
"""
import json, math, pathlib, datetime, zoneinfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLAN = ROOT / "plan.json"
KST = zoneinfo.ZoneInfo("Asia/Seoul")
PHI = lambda z: 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
WINDOW_DAYS = 30                       # 매도 창: 달력 30일
LATCH_FRAC = 0.25                      # 하한선 이탈일마다 잔여의 1/4 매도

# 22년 252개 창 백테스트 (하한선 -1.04%, 눈금 +0.43%/+2.27%):
#   무대응   중앙값 1,136.3 · 포착 49.8% · 최악 -10.77%
#   전량래치 중앙값 1,139.0 · 포착 47.8% · 최악  -3.57%
#   부분 1/4 중앙값 1,139.8 · 포착 48.7% · 최악  -5.37%  ← 채택
# 평균은 셋 다 같다(편차 0.07%). 1/4 가 중앙값·포착률 최고면서 꼬리는 무대응의 절반.

# 한국 외환시장 휴장일. 주말만 빼면 추석 같은 연휴가 통째로 누락돼
# 남은 거래일이 과대 표시된다. 마감이 휴장일이면 직전 거래일로 당긴다.
HOLIDAYS = {
    "2026-09-24", "2026-09-25",              # 추석
    "2026-10-09",                            # 한글날
    "2026-12-25",
    "2027-01-01",
}


def is_trading(d):
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS


def trading_days(a, b):
    """a 다음날부터 b 까지의 거래일 수."""
    n, cur = 0, a
    while cur < b:
        cur += datetime.timedelta(days=1)
        if is_trading(cur):
            n += 1
    return n


def last_trading_on_or_before(d):
    for _ in range(10):
        if is_trading(d):
            return d
        d -= datetime.timedelta(days=1)
    return d


def ensure(data, nar, fwd, sig_d):
    """plan.json 이 없거나 창이 끝났으면 새로 연다."""
    today = data["latest"]["d"]
    cur = None
    if PLAN.exists():
        try:
            cur = json.loads(PLAN.read_text(encoding="utf-8"))
        except Exception:                                    # noqa: BLE001
            cur = None
    if cur:
        end = datetime.date.fromisoformat(cur["deadline"])
        if datetime.date.fromisoformat(today) <= end:
            return cur, False                                # 진행 중
    d0 = datetime.date.fromisoformat(today)
    px = float(data["latest"]["c"])
    doc = {
        "d0": today,
        "deadline": (d0 + datetime.timedelta(days=WINDOW_DAYS)).isoformat(),
        "spot0": px,
        "sig_d": sig_d,                                      # D-0 시점 일간 변동성
        "mu_month": float(fwd["m1"]) / px if fwd else 1.0,   # D-0 시점 시장 선도 배율
        "rungs": [{"lo": float(z["lo"]), "hi": float(z["hi"]), "pct": z["pct"],
                   "w": _wgt(z["pct"]), "title": z["title"]}
                  for z in nar["ladder"]["zones"] if z["kind"] == "sell"],
        "stop": float(nar["triggers"]["stop"]),
        "opened_at": datetime.datetime.now(KST).isoformat(timespec="seconds"),
    }
    PLAN.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc, True


def _wgt(pct):
    try:
        return float(str(pct).replace("%", "")) / 100
    except ValueError:
        return 0.0


def state(plan, data):
    """오늘의 상태. 계획 대비 어디에 있는가."""
    ser = data["series"]
    px = float(data["latest"]["c"])
    today = datetime.date.fromisoformat(data["latest"]["d"])
    d0 = datetime.date.fromisoformat(plan["d0"])
    end = datetime.date.fromisoformat(plan["deadline"])

    # 창 안의 실제 종가들
    win = [r for r in ser if plan["d0"] <= r["d"] <= data["latest"]["d"]]
    closes = [r["c"] for r in win] or [px]
    hi = max(closes)
    hi_d = next((r["d"] for r in win if r["c"] == hi), plan["d0"])

    # 남은 영업일 (주말만 제외한 근사)
    end = last_trading_on_or_before(end)     # 마감이 휴장이면 직전 거래일
    rem = trading_days(today, end)
    total = trading_days(d0, end)
    elapsed = max(total - rem, 0)

    # 남은 구간에 3일 이상 공백(연휴)이 있으면 알린다
    gap = None
    cur, run = today, 0
    while cur < end:
        cur += datetime.timedelta(days=1)
        if is_trading(cur):
            if run >= 3:
                gap = {"until": cur.isoformat(), "days": run}
                break
            run = 0
        else:
            run += 1

    # D-0 분포에서 오늘 가격의 퍼센타일
    pct_rank = None
    t = max(elapsed, 1)
    sig = plan.get("sig_d") or 0.005
    if plan.get("spot0") and sig > 0:
        mu = math.log(plan.get("mu_month", 1.0)) / 21
        z = (math.log(px / plan["spot0"]) - mu * t) / (sig * math.sqrt(t))
        pct_rank = PHI(z) * 100

    # 진도: 눈금 체결 + 하한선 이탈 분할매도를 날짜순으로 재생한다
    lo_line = plan["stop"]
    left, sold, hits, rung_hit = 1.0, 0.0, 0, set()
    log, cost = [], 0.0                                  # 계획이 시킨 매도 내역
    for r in win:
        c = r["c"]
        for j, g in enumerate(plan["rungs"]):
            if j not in rung_hit and c >= g["lo"] and left > 1e-9:
                a = min(g["w"], left); sold += a; left -= a; rung_hit.add(j)
                cost += a * c
                log.append({"d": r["d"], "why": f'{g["pct"]} 눈금 {g["lo"]:,.0f} 도달',
                            "w": a * 100, "px": c})
        if c <= lo_line and left > 1e-9:                 # 하한 분할선 이탈일
            a = min(left * LATCH_FRAC, left); sold += a; left -= a; hits += 1
            cost += a * c
            log.append({"d": r["d"], "why": f'하한선 {lo_line:,.0f} 이탈',
                        "w": a * 100, "px": c})
    pending = [r for j, r in enumerate(plan["rungs"]) if j not in rung_hit]
    pending.sort(key=lambda r: r["lo"])
    nxt = pending[0] if pending else None
    reached = sold

    return {
        "px": px, "d0": plan["d0"], "deadline": end.isoformat(), "gap": gap,
        "rem": rem, "total": total, "elapsed": elapsed,
        "time_pct": (elapsed / total * 100) if total else 0,
        "hi": hi, "hi_d": hi_d, "off_hi": px - hi,
        "pct_rank": pct_rank,
        "reached": reached * 100, "left": left * 100,
        "log": log, "avg": (cost / sold) if sold > 1e-9 else None,
        "latch_hits": hits, "latch_frac": LATCH_FRAC,
        "plan_w": 100.0,
        "next": nxt, "stop": plan["stop"],
        "below_stop": px <= plan["stop"],
        "today_breach": px <= plan["stop"] and left > 1e-9,
    }
