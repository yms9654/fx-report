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
    rem = sum(1 for i in range((end - today).days)
              if (today + datetime.timedelta(days=i + 1)).weekday() < 5)
    total = sum(1 for i in range((end - d0).days)
                if (d0 + datetime.timedelta(days=i + 1)).weekday() < 5)
    elapsed = max(total - rem, 0)

    # D-0 분포에서 오늘 가격의 퍼센타일
    pct_rank = None
    t = max(elapsed, 1)
    sig = plan.get("sig_d") or 0.005
    if plan.get("spot0") and sig > 0:
        mu = math.log(plan.get("mu_month", 1.0)) / 21
        z = (math.log(px / plan["spot0"]) - mu * t) / (sig * math.sqrt(t))
        pct_rank = PHI(z) * 100

    # 진도: 창 안에서 도달한 눈금의 비중 합
    reached, pending = 0.0, []
    for r in plan["rungs"]:
        if any(c >= r["lo"] for c in closes):
            reached += r["w"]
        else:
            pending.append(r)
    pending.sort(key=lambda r: r["lo"])
    nxt = pending[0] if pending else None

    return {
        "px": px, "d0": plan["d0"], "deadline": plan["deadline"],
        "rem": rem, "total": total, "elapsed": elapsed,
        "time_pct": (elapsed / total * 100) if total else 0,
        "hi": hi, "hi_d": hi_d, "off_hi": px - hi,
        "pct_rank": pct_rank,
        "reached": reached * 100,
        "plan_w": sum(r["w"] for r in plan["rungs"]) * 100,
        "next": nxt, "stop": plan["stop"],
        "below_stop": px <= plan["stop"],
    }
