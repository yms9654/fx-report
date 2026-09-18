#!/usr/bin/env python3
"""data.json + narrative.json -> docs/index.html"""
import json, sys, html, math, pathlib, datetime, statistics, zoneinfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from analysis import technicals, forecast, trigger_drift, sma
from plan_state import ensure as plan_ensure, state as plan_state

ROOT = pathlib.Path(__file__).resolve().parent.parent
KST = zoneinfo.ZoneInfo("Asia/Seoul")
E = lambda s: html.escape(str(s), quote=False)
NUM = lambda v: f"{float(v):,.0f}"



# ---------- 주간 확률 (실현변동성 + 분석 기대값 드리프트) ----------
PHI = lambda z: 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
TD_WEEK, TD_MONTH, Z80 = 5, 21, 1.2816


def _touch_up(b, mu, sig, T):
    """b>0 (로그거리). 기간 내 상단 배리어를 한 번이라도 건드릴 확률."""
    sT = sig * math.sqrt(T)
    if sT <= 0:
        return 1.0 if mu * T >= b else 0.0
    p = PHI((mu * T - b) / sT) + math.exp(min(2 * mu * b / sig ** 2, 700)) * PHI((-b - mu * T) / sT)
    return min(max(p, 0.0), 1.0)


def _touch_dn(b, mu, sig, T):
    """b<0. 기간 내 하단 배리어를 한 번이라도 건드릴 확률."""
    sT = sig * math.sqrt(T)
    if sT <= 0:
        return 1.0 if mu * T <= b else 0.0
    p = PHI((b - mu * T) / sT) + math.exp(min(2 * mu * b / sig ** 2, 700)) * PHI((b + mu * T) / sT)
    return min(max(p, 0.0), 1.0)


def weekly_probs(data, nar, px, mu_month=None, sig_override=None, vol_src=None, plan=None):
    closes = [r["c"] for r in data["series"]]
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    if len(rets) < 10:
        return None
    sig = statistics.stdev(rets)                     # 일간 실현변동성
    if sig_override:
        sig = sig_override                           # 예측 밴드와 같은 변동성을 쓴다
    if sig <= 0:
        return None
    ev = float(mu_month if mu_month else nar["scenario"]["ev"])
    mu = math.log(ev / px) / TD_MONTH                # 한 달 기준값 → 일간 드리프트

    # 도달 확률은 동결된 계획 눈금 기준. 서술이 매일 바뀌어도 확률의 기준은 고정.
    if plan:
        sells = sorted(({"lo": r["lo"], "pct": r["pct"]} for r in plan["rungs"]),
                       key=lambda z: float(z["lo"]))
        stop = float(plan["stop"])
    else:
        sells = sorted((z for z in nar["ladder"]["zones"] if z["kind"] == "sell"),
                       key=lambda z: float(z["lo"]))
        stop = float(nar["triggers"]["stop"])
    nxt = next((z for z in sells if float(z["lo"]) > px), sells[-1] if sells else None)
    b_up = math.log(float(nxt["lo"]) / px) if nxt else None
    b_dn = math.log(stop / px)

    weeks = []
    base = datetime.date.fromisoformat(data["latest"]["d"])
    for k in range(1, 5):
        T = TD_WEEK * k
        sT, mT = sig * math.sqrt(T), mu * T
        up = PHI(mT / sT)
        weeks.append({
            "k": k,
            "until": (base + datetime.timedelta(days=7 * k)).strftime("%m/%d"),
            "up": round(up * 100),
            "dn": round((1 - up) * 100),
            "lo": px * math.exp(mT - Z80 * sT),
            "hi": px * math.exp(mT + Z80 * sT),
            "t_up": round(_touch_up(b_up, mu, sig, T) * 100) if b_up and b_up > 0 else None,
            "t_dn": round(_touch_dn(b_dn, mu, sig, T) * 100) if b_dn < 0 else None,
        })
    return {"weeks": weeks, "sig_d": sig * 100, "sig_a": sig * math.sqrt(252) * 100,
            "vol_src": vol_src or "실현변동성",
            "mu_m": (math.exp(mu * TD_MONTH) - 1) * 100, "n": len(rets),
            "target": float(nxt["lo"]) if nxt else None, "target_pct": nxt["pct"] if nxt else None,
            "stop": stop}


def probs_html(w, fwd=None):
    if not w:
        return '<p class="lede">확률 계산에 필요한 데이터가 부족합니다.</p>'
    rows = ""
    tgt = w["target"]
    trow = lambda key, cls, label, vals: (
        f'<div class="pt"><div class="pt__k {cls}">{label}</div>'
        + "".join(f'<div class="pt__v"><span>{x["k"]}주</span>'
                  f'<b>{x[key]}%</b></div>' for x in w["weeks"]) + '</div>')
    touch = ""
    if tgt and w["weeks"][0]["t_up"] is not None:
        touch += trow("t_up", "up", f'{NUM(tgt)} 터치<span>{E(w["target_pct"])} 매도</span>', None)
    if w["weeks"][0]["t_dn"] is not None:
        touch += trow("t_dn", "dn", f'{NUM(w["stop"])} 이탈<span>전량 청산</span>', None)
    basis = (f'중앙값은 시장 선도환율(한 달 <b>{w["mu_m"]:+.2f}%</b>, '
             f'{fwd["krw"]["source"].split()[0]} {fwd["krw"]["rate"]*100:.2f}% vs '
             f'SOFR {fwd["usd"]["rate"]*100:.2f}%)을 따르고,') if fwd else \
            (f'중앙값은 분석 기대값(한 달 <b>{w["mu_m"]:+.2f}%</b>)을 따르고,')
    return f"""<div class="probs">
      <div class="probs__split" style="margin-top:0;padding-top:0;border-top:0">
      <div class="probs__splitk">계획 가격에 기간 안에 한 번이라도 닿을 확률</div>{touch}</div>
      <p class="probs__note">{basis} 폭은 {w['vol_src']} <b>일간 {w['sig_d']:.2f}%</b>
      (연율 {w['sig_a']:.1f}%)로 잡은 로그정규 모델 추정치입니다.
      이벤트 점프는 반영되지 않아 FOMC 전후 실제 분포는 이보다 꼬리가 두껍습니다.</p>
    </div>"""


def tech_html(t, dxy=None, kchg=None):
    if not t:
        return ""
    cls = {"down": "dn", "up": "up", "flat": ""}[t["trend"]]
    momcls = "dn" if t["mom"] == "과매도" else "up" if t["mom"] == "과매수" else ""
    cells = [
        ("추세", f'<b class="t-{cls}">{t["tlabel"]}</b>',
         f'{sum(1 for _, v in t["signals"] if v < 0)}/{len(t["signals"])} 하락 신호'),
        ("RSI(14)", f'<b class="t-{momcls}">{t["rsi"]:.0f}</b>', t["mom"] or ""),
        ("MA20 대비", f'<b class="t-{"dn" if t["vs20"] < 0 else "up"}">{t["vs20"]:+.1f}%</b>',
         f'MA20 {t["ma20"]:,.0f}'),
        ("MA60 대비", f'<b class="t-{"dn" if t["vs60"] < 0 else "up"}">{t["vs60"]:+.1f}%</b>',
         f'MA60 {t["ma60"]:,.0f}'),
    ]
    if dxy is not None and kchg is not None:
        own = kchg - dxy["chg20"]
        cells.append(("달러지수", f'<b class="t-{"dn" if dxy["chg20"] < 0 else "up"}">'
                                  f'{dxy["chg20"]:+.1f}%</b>',
                      f'{dxy["last"]:.1f} · 원화 고유 {own:+.1f}%p'))
    if t["bb"]:
        b = t["bb"]
        where = "하단 이탈" if b["pctb"] < 0 else "하단권" if b["pctb"] < 0.2 \
            else "상단권" if b["pctb"] > 0.8 else "중앙권"
        cells.append(("볼린저 %B", f'<b>{b["pctb"]:.2f}</b>', where))
    return '<div class="tech">' + "".join(
        f'<div class="tech__c"><div class="tech__k">{k}</div>'
        f'<div class="tech__v">{v}</div><div class="tech__s">{E(sub)}</div></div>'
        for k, v, sub in cells) + '</div>'


def drift_html(d):
    if not d:
        return ""
    return (f'<div class="warn"><span class="warn__k">계획 점검</span>'
            f'<span class="warn__t">최근 {d["days"]}회 중 <b>{d["n"]}번</b> 손절선이 낮아졌습니다 '
            f'(<b>{NUM(d["from"])} → {NUM(d["to"])}</b>, {NUM(d["drop"])}원). '
            f'가격을 따라 손절이 내려가면 계획은 영원히 발동하지 않습니다. '
            f'지금 값이 아니라 <b>처음 정한 {NUM(d["from"])}</b>을 기준으로 판단하세요.</span></div>')


def action_html(st, plan):
    """오늘 할 일만 말한다.

    보유 비중·매도 내역·평균단가는 전부 제거했다. 시스템은 사용자가 무엇을
    얼마나 들고 있는지 모르고, 실제로 팔았는지도 모른다. 모르는 것을 아는 척하면
    화면 전체가 허구 위에 선다. 규칙은 '무엇을 하라'로만 말하고, 비중 계산은
    사용자가 자기 보유분에 적용한다.
    """
    px, lo = st["px"], st["stop"]
    dd = lambda x: x.replace("-", ".")[5:]
    rungs = sorted(plan["rungs"], key=lambda r: float(r["lo"]))
    above = [r for r in rungs if float(r["lo"]) > px]        # 아직 위에 있는 구간
    nx = above[0] if above else None
    inz = next((r for r in rungs if float(r["lo"]) <= px <= float(r["hi"])), None)

    if px <= lo:
        kind, act = "cut", "보유분의 1/4를 파세요"
        how = (f'종가가 하한 분할선 <b>{NUM(lo)}</b> 아래입니다. '
               f'남아 있는 물량의 <b>1/4</b>를 오늘 정리하고, 나머지는 계속 들고 갑니다.')
    elif inz:
        kind, act = "sell", f'{E(inz["pct"])}를 파세요'
        how = f'가격이 매도 구간 <b>{NUM(inz["lo"])} – {NUM(inz["hi"])}</b> 안에 있습니다.'
    elif st["rem"] <= 1:
        kind, act = "cut", "남은 전부를 파세요"
        how = '마지막 거래일입니다. 남아 있는 물량을 정리합니다.'
    elif nx:
        kind, act = "wait", "오늘은 팔지 않습니다"
        how = (f'다음 매도 구간은 <b>{NUM(nx["lo"])} – {NUM(nx["hi"])}</b>, '
               f'지금보다 <b>{nx["lo"]-px:+,.0f}원</b>입니다. '
               f'지정가를 걸어두면 닿는 순간 체결됩니다.')
    else:
        kind, act = "wait", "오늘은 팔지 않습니다"
        how = f'가격이 계획 구간을 모두 넘어섰습니다. 마감({dd(st["deadline"])})까지 남은 물량을 정리하세요.'

    passed = [r for r in rungs if float(r["hi"]) < px]
    rows = [("현재", f'{px:,.2f}', f'{st["chg"]:+.2f} · {dd(st["today"])}')]
    if nx:
        rows.append(("매도 구간", f'{NUM(nx["lo"])}<span class="u">–{NUM(nx["hi"])}</span>',
                     f'{nx["lo"]-px:+,.0f}원 · 닿으면 {E(nx["pct"])}'))
    rows.append(("하한 분할선", f'{NUM(lo)}', f'{px-lo:+,.0f}원 · 아래로 마감하면 보유분의 1/4 정리'))
    if passed:
        rows.append(("지나간 구간",
                     " · ".join(NUM(r["lo"]) for r in passed),
                     "이미 통과했습니다"))
    body = "".join(f'<div class="tl"><span class="tl__d">{k}</span>'
                   f'<span class="tl__p">{v}</span><span class="tl__y">{sub}</span></div>'
                   for k, v, sub in rows)
    gap = ""
    if st.get("gap"):
        gap = (f'<p class="act__note">추석 휴장으로 {dd(st["gap"]["until"])}까지 '
               f'{st["gap"]["days"]}일 공백. 거래일이 그 앞뒤로 몰립니다.</p>')
    return (f'<div class="now now--{kind}">'
            f'<div class="now__k">오늘 할 일 · {dd(st["deadline"]).replace(".", "/")} 마감'
            f'<span class="dcount">D-{st["rem"]}</span></div>'
            f'<div class="act">{act}</div>'
            f'<p class="act__how">{how}</p>'
            f'<div class="tl__box">{body}</div>{gap}')

def main():
    cfg = {}
    cfgp = ROOT / "config.json"
    if cfgp.exists():
        try:
            cfg = json.loads(cfgp.read_text(encoding="utf-8"))
        except Exception:                                    # noqa: BLE001
            cfg = {}
    data = json.loads((ROOT / "data.json").read_text(encoding="utf-8"))
    nar = json.loads((ROOT / "narrative.json").read_text(encoding="utf-8"))
    tmpl = (ROOT / "build" / "template.html").read_text(encoding="utf-8")

    px = float(data["latest"]["c"])
    chg = float(data["latest"]["chg"])
    pxdate = data["latest"]["d"]
    now = datetime.datetime.now(KST)

    # 데이터 신선도
    age = (now.date() - datetime.date.fromisoformat(data["fetched_at"][:10])).days
    stale = age >= 2

    hist = data.get("history") or data["series"]
    tech = technicals(hist)
    fwd = None
    fp = ROOT / "forward.json"
    if fp.exists():
        try:
            fwd = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:                                    # noqa: BLE001
            fwd = None
    # 중앙선은 시장 선도환율, 비교선은 분석 기대값
    mu_month = float(fwd["m1"]) if fwd else float(nar["scenario"]["ev"])
    fc = forecast(hist, px, mu_month, alt_month=float(nar["scenario"]["ev"]))

    # 트리거 이력 — 손절선이 가격을 따라 내려가는지 감시
    tlog_p = ROOT / "triggers_log.json"
    tlog = []
    if tlog_p.exists():
        try:
            tlog = json.loads(tlog_p.read_text(encoding="utf-8"))
        except Exception:                                    # noqa: BLE001
            tlog = []
    tg = nar["triggers"]
    entry = {"d": pxdate, "px": px, "stop": float(tg["stop"]),
             "t1": float(tg["t1"]), "t2": float(tg["t2"])}
    if not tlog or tlog[-1].get("d") != pxdate:
        tlog.append(entry)
    else:
        tlog[-1] = entry
    tlog = tlog[-60:]
    tlog_p.write_text(json.dumps(tlog, ensure_ascii=False, indent=0), encoding="utf-8")
    drift = trigger_drift(tlog, float(tg["stop"]))

    plan, opened = plan_ensure(data, nar, fwd, (fc["sig_d"] / 100) if fc else 0.005)
    st = plan_state(plan, data)
    chg_cls = "chg-up" if chg > 0 else "chg-dn"
    S = {}

    S["METAPX"] = (f'{px:,.2f} <span class="{chg_cls}">{chg:+.2f}</span> · '
                   f'{pxdate.replace("-", ".")}')
    S["EYEBROW"] = E(nar.get("eyebrow", "매도 전략")) + f" · 자동 갱신 {now:%Y.%m.%d}"
    S["METAVERB"] = (f'<span class="metabar__verb '
                     + ("v-cut" if st["below_stop"] else "") + f'">D-{st["rem"]}</span>')
    S["VERDICTNOW"] = action_html(st, plan) + "</div>"
    ser = data["series"]
    kchg = ((ser[-1]["c"] / ser[-21]["c"] - 1) * 100) if len(ser) > 21 else None
    S["TECH"] = tech_html(tech, data.get("dxy"), kchg)
    ip, fp = f"{px:,.2f}".split(".")
    S["NDAYS"] = str(data["span_days"])

    def force(side, cls, title, direction):
        items = "".join(
            f'<li><span class="tag tag--{"new" if f.get("new") else "std"}">{E(f["tag"])}</span>'
            f'<span>{f["text"]}</span></li>' for f in nar["forces"][side])
        return (f'<div class="force force--{cls}"><h3>{title}</h3>'
                f'<div class="dir">{direction}</div><ul>{items}</ul></div>')

    S["FORCES"] = (force("down", "dn", "원화 강세", "환율 하락 압력") +
                   force("up", "up", "달러 강세", "환율 상승 압력"))

    sc = nar["scenario"]
    S["SCENARIO"] = f"""<div class="scen">
      <div class="probbar" role="img" aria-label="{E(sc['up_label'])} {sc['up_prob']}퍼센트, {E(sc['dn_label'])} {100-sc['up_prob']}퍼센트">
        <div class="p-up" style="flex:{sc['up_prob']}">{sc['up_prob']}% {E(sc['up_label'])}</div>
        <div class="p-dn" style="flex:{100-sc['up_prob']}">{100-sc['up_prob']}% {E(sc['dn_label'])}</div>
      </div>
      <div class="scen__grid">
        <div class="scen__col up"><h4>{E(sc['up_label'])}</h4>
          <span class="rng">{NUM(sc['up_lo'])} – {NUM(sc['up_hi'])}</span><p>{sc['up_text']}</p></div>
        <div class="scen__col dn"><h4>{E(sc['dn_label'])}</h4>
          <span class="rng">{NUM(sc['dn_lo'])} – {NUM(sc['dn_hi'])}</span><p>{sc['dn_text']}</p></div>
      </div>
      <div class="ev">
        <div><div class="k">확률가중 기대값</div><div class="v">{NUM(sc['ev'])}원</div></div>
        <div><div class="k">한 달 예상 범위</div><div class="v">{NUM(sc['range_lo'])} – {NUM(sc['range_hi'])}</div></div>
        <div><div class="k">현재가 대비</div><div class="v" style="color:var(--{'up' if sc['ev']>=px else 'down'})">{sc['ev']-px:+,.0f}원</div></div>
      </div></div>"""

    S["PROBS"] = probs_html(
        weekly_probs(data, nar, px, mu_month,
                     sig_override=(fc["sig_d"] / 100) if fc else None,
                     vol_src=fc["vol_src"] if fc else None, plan=plan), fwd)

    # 사다리는 동결된 계획에서 그린다. 서술은 매일 바뀌어도 계획은 안 바뀐다.
    plan_zones = ([{"kind": "sell", "lo": r["lo"], "hi": r["hi"], "pct": r["pct"],
                    "title": r["title"], "note": ""} for r in plan["rungs"]]
                  + [{"kind": "cut", "lo": plan["stop"] - 40, "hi": plan["stop"],
                      "pct": "전량", "title": "손절 — 계획 종료",
                      "note": "여기 닿으면 판단이 틀린 것으로 보고 정리한다."}])
    for z in plan_zones:                                     # 서술만 오늘 분석에서 빌려온다
        for nz in nar["ladder"]["zones"]:
            if abs(float(nz["lo"]) - z["lo"]) < 12 and nz["kind"] == z["kind"]:
                z["note"] = nz.get("note", z["note"])
    lad = {"lo": min(z["lo"] for z in plan_zones) - 10,
           "hi": max(z["hi"] for z in plan_zones) + 15,
           "step": 10, "zones": plan_zones}
    alo, ahi = float(lad["lo"]), float(lad["hi"])
    span = ahi - alo
    pos = lambda v: (float(v) - alo) / span * 100
    zones = ""
    for z in lad["zones"]:
        cls = "cut" if z["kind"] == "cut" else "t2"
        zlo, zhi = float(z["lo"]), float(z["hi"])
        b, h = max(0, pos(zlo)), min(100, pos(zhi)) - max(0, pos(zlo))
        zones += (f'<div class="zone zone--{cls}" style="bottom:{b:.1f}%; height:{h:.1f}%">'
                  f'<div class="zone__in"><div class="zone__hd">'
                  f'<span class="zone__pct">{E(z["pct"])}</span>'
                  f'<span class="zone__ttl">{E(z["title"])}</span>'
                  f'<span class="zone__px">{NUM(zlo)} – {NUM(zhi)}</span></div>'
                  f'<div class="zone__note">{z["note"]}</div></div></div>')
    npos = min(99.4, max(0.6, pos(px)))
    S["LADDER"] = (f'<div class="ladder"><div class="ladder__axis" id="axis"></div>'
                   f'<div class="ladder__field" id="field">{zones}'
                   f'<div class="nowline" style="bottom:{npos:.1f}%">'
                   f'<span class="nowline__tag">현재 {px:,.2f}</span></div></div></div>')

    S["CALENDAR"] = "".join(
        f'<li{" class=\"key\"" if c.get("key") else ""}><span class="d">{E(c["d"])}</span>'
        f'<span class="t"><b>{E(c["t"])}</b><span>{E(c.get("note",""))}</span></span></li>'
        for c in nar["calendar"])
    S["TIPS"] = "".join(f"<li>{t}</li>" for t in nar["tips"])
    S["SOURCES"] = "".join(
        f'<li><a href="{html.escape(s["u"], quote=True)}" rel="noopener">{E(s["t"])}</a></li>'
        for s in nar["sources"])

    stamp = (f'데이터 <b>{E(data["source"])}</b> · 수집 {data["fetched_at"][:16].replace("T"," ")} KST'
             f' · 분석 갱신 {E(nar.get("generated_at","?")[:16].replace("T"," "))} KST')
    if stale:
        stamp += f' · <span class="stale">데이터가 {age}일 지났습니다</span>'
    if nar.get("degraded"):
        stamp += ' · <span class="stale">분석 재작성 실패, 직전 분석 유지</span>'
    S["STAMP"] = stamp

    hc = [r["c"] for r in hist]
    hidx = {r["d"]: i for i, r in enumerate(hist)}
    ma20_series = []
    for r in data["series"]:
        i = hidx.get(r["d"])
        ma20_series.append(round(sma(hc[:i + 1], 20), 2) if i is not None and i >= 19 else None)

    S["PAYLOAD"] = json.dumps({
        "series": data["series"],
        "ma20": ma20_series,
        "fc": [{k: round(v, 2) for k, v in p.items()} for p in fc["pts"]] if fc else None,
        "levels": {"stop": float(tg["stop"]), "t1": float(tg["t1"]), "t2": float(tg["t2"])},
        "events": nar.get("events", {}),
        "year": pxdate[:4],
        "ladder": {"lo": alo, "hi": ahi, "step": int(lad.get("step", 10))},
        "fb": {
            "repo": "yms9654/fx-report",
            "endpoint": cfg.get("feedback_endpoint", ""),
            "date": pxdate,
            "px": f"{px:,.2f}",
            "chg": f"{chg:+.2f}",
            "verb": f"D-{st['rem']}",
            "amt": f"하한선 {st['stop']:,.0f}",
            "stop": NUM(nar["triggers"]["stop"]),
            "t1": NUM(nar["triggers"]["t1"]),
            "t2": NUM(nar["triggers"]["t2"]),
            "dataAt": data["fetched_at"][:16].replace("T", " ") + " KST",
        },
    }, ensure_ascii=False)

    out = tmpl
    for k, v in S.items():
        out = out.replace(f"<!--SLOT:{k}-->", v)
    left = [ln for ln in out.split("\n") if "<!--SLOT:" in ln]
    if left:
        print("WARN unfilled slots:", left[:3], file=sys.stderr)

    dst = ROOT / "docs" / "index.html"
    dst.parent.mkdir(exist_ok=True)
    dst.write_text(out, encoding="utf-8")
    (ROOT / "docs" / ".nojekyll").touch()
    print(f"OK rendered {len(out):,} bytes | px {px:,.2f} | D-{st['rem']} | {tech['tlabel']} RSI {tech['rsi']:.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
