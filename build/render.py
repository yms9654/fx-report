#!/usr/bin/env python3
"""data.json + narrative.json -> docs/index.html"""
import json, sys, html, math, pathlib, datetime, statistics, zoneinfo

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


def weekly_probs(data, nar, px):
    closes = [r["c"] for r in data["series"]]
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    if len(rets) < 10:
        return None
    sig = statistics.stdev(rets)                     # 일간 실현변동성
    if sig <= 0:
        return None
    ev = float(nar["scenario"]["ev"])
    mu = math.log(ev / px) / TD_MONTH                # 한 달 기대값 → 일간 드리프트

    sells = sorted((z for z in nar["ladder"]["zones"] if z["kind"] == "sell"),
                   key=lambda z: float(z["lo"]))
    nxt = next((z for z in sells if float(z["lo"]) > px), sells[-1] if sells else None)
    stop = float(nar["triggers"]["stop"])
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
            "mu_m": (math.exp(mu * TD_MONTH) - 1) * 100, "n": len(rets),
            "target": float(nxt["lo"]) if nxt else None, "target_pct": nxt["pct"] if nxt else None,
            "stop": stop}


def probs_html(w):
    if not w:
        return '<p class="lede">확률 계산에 필요한 데이터가 부족합니다.</p>'
    rows = ""
    for x in w["weeks"]:
        lead = "up" if x["up"] >= x["dn"] else "dn"
        rows += f"""<div class="pw">
          <div class="pw__k">{x['k']}주<span>~{x['until']}</span></div>
          <div class="pw__bar">
            <div class="pw__seg s-up" style="flex:{max(x['up'],1)}"><span>{x['up']}%</span></div>
            <div class="pw__seg s-dn" style="flex:{max(x['dn'],1)}"><span>{x['dn']}%</span></div>
          </div>
        </div>"""
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
    return f"""<div class="probs">
      <div class="pw pw--hd"><div class="pw__k">기간</div>
        <div class="pw__bar"><span class="hd-up">오를 확률</span><span class="hd-dn">내릴 확률</span></div></div>
      {rows}
      <div class="probs__split"><div class="probs__splitk">누적 도달 확률 — 기간 안에 한 번이라도 닿을 확률</div>{touch}</div>
      <p class="probs__note">일간 실현변동성 <b>{w['sig_d']:.2f}%</b> (연율 {w['sig_a']:.1f}%, 최근 {w['n']}개 수익률)와
      분석 기대값(한 달 <b>{w['mu_m']:+.1f}%</b>)을 드리프트로 둔 로그정규 모델 추정치입니다.
      시장이 이 가정대로 움직인다는 보장은 없고, 이벤트 리스크는 반영되지 않습니다.</p>
    </div>"""


def decide(px, nar):
    """현재가를 계획(사다리 구간 + 트리거)과 대조해 오늘의 지시를 정한다.
    반환: (kind, verb, amount, why, rows) — kind 는 sell/cut/wait."""
    trg = nar["triggers"]
    stop, t1, t2 = float(trg["stop"]), float(trg["t1"]), float(trg["t2"])
    zones = nar["ladder"]["zones"]
    sells = sorted((z for z in zones if z["kind"] == "sell"), key=lambda z: float(z["lo"]))
    cuts = [z for z in zones if z["kind"] == "cut"]

    def zone_at(zs):
        return next((z for z in zs if float(z["lo"]) <= px <= float(z["hi"])), None)

    hit_cut = zone_at(cuts) or (cuts[0] if px <= stop and cuts else None)
    hit_sell = zone_at(sells)

    cur = ("현재", f"<b>{px:,.2f}</b>", "", "")

    if hit_cut:
        return ("cut", "판다", "잔여 전량",
                f"손절선 <b>{NUM(stop)}</b>을 이탈했습니다. 계획대로라면 여기서는 "
                f"버티지 않고 남은 물량을 전부 정리합니다.",
                [cur, ("손절", f"<b>{NUM(stop)}</b> 이탈함", f"{px-stop:+,.1f}원", "dn")])

    if hit_sell:
        return ("sell", "판다", f"{hit_sell['pct']} 매도",
                f"{E(hit_sell['title'])} 구간(<b>{NUM(hit_sell['lo'])}–{NUM(hit_sell['hi'])}</b>)에 "
                f"들어왔습니다. 계획 비중 <b>{E(hit_sell['pct'])}</b>를 지금 집행합니다.",
                [cur, ("구간", f"<b>{NUM(hit_sell['lo'])}–{NUM(hit_sell['hi'])}</b> 안", "", "up")])

    # 대기: 위로 가장 가까운 매도 구간과 아래 손절까지의 거리를 보여준다
    nxt = next((z for z in sells if float(z["lo"]) > px), None)
    rows = [cur]
    if nxt:
        d = float(nxt["lo"]) - px
        rows.append(("다음", f"<b>{NUM(nxt['lo'])}</b> 도달 → {E(nxt['pct'])} 매도",
                     f"+{d:,.1f}원", "up"))
    rows.append(("손절", f"<b>{NUM(stop)}</b> 이탈 → 잔여 전량 청산",
                 f"−{px-stop:,.1f}원", "dn"))
    why = ("아직 계획한 어느 가격대에도 닿지 않았습니다. "
           "<b>오늘은 아무것도 하지 않습니다.</b> 지정가만 걸어두고 기다립니다.")
    return ("wait", "기다린다", "", why, rows)


def gauge(px, nar):
    """손절 ~ 최상단 매도구간 사이에서 현재가 위치를 보여주는 가로 게이지."""
    trg = nar["triggers"]
    stop, t2 = float(trg["stop"]), float(trg["t2"])
    sells = sorted((z for z in nar["ladder"]["zones"] if z["kind"] == "sell"),
                   key=lambda z: float(z["lo"]))
    top = max([t2] + [float(z["hi"]) for z in sells])
    g_lo, g_hi = min(stop, px) - 6, max(top, px) + 6
    span = g_hi - g_lo
    P = lambda v: (float(v) - g_lo) / span * 100

    parts = [f'<div class="gauge__track"></div>']
    parts.append(f'<div class="gauge__seg s-cut" style="left:0; width:{P(stop):.1f}%"></div>')
    for z in sells:
        l, w = P(z["lo"]), P(z["hi"]) - P(z["lo"])
        parts.append(f'<div class="gauge__seg s-sell" style="left:{l:.1f}%; width:{w:.1f}%"></div>')
    for v, cls in [(stop, "at-dn")] + [(float(z["lo"]), "at-up") for z in sells]:
        parts.append(f'<div class="gauge__mk" style="left:{P(v):.1f}%"></div>')
        parts.append(f'<div class="gauge__lb {cls}" style="left:{P(v):.1f}%">{NUM(v)}</div>')
    parts.append(f'<div class="gauge__now" style="left:{P(px):.1f}%"></div>')
    parts.append(f'<div class="gauge__nowlb" style="left:{P(px):.1f}%">{px:,.2f}</div>')
    return '<div class="gauge">' + "".join(parts) + "</div>"


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

    kind, verb, amt, why, rows = decide(px, nar)
    chg_cls = "chg-up" if chg > 0 else "chg-dn"
    S = {}

    S["METAPX"] = (f'{px:,.2f} <span class="{chg_cls}">{chg:+.2f}</span> · '
                   f'{pxdate.replace("-", ".")}')
    S["EYEBROW"] = E(nar.get("eyebrow", "매도 전략")) + f" · 자동 갱신 {now:%Y.%m.%d}"
    verb_cls = {"sell": "v-sell", "cut": "v-cut", "wait": ""}[kind]
    S["METAVERB"] = f'<span class="metabar__verb {verb_cls}">{verb}</span>'
    rows_html = "".join(
        f'<div class="now__row"><span class="rk">{rk}</span>'
        f'<span class="rv">{rv}</span>'
        + (f'<span class="rd chg-{cc}">{rd}</span>' if rd else "")
        + '</div>'
        for rk, rv, rd, cc in rows)
    S["VERDICTNOW"] = (
        f'<div class="now now--{kind}">'
        f'<div class="now__k">오늘의 지시 · {pxdate.replace("-", ".")}</div>'
        f'<div class="now__verb">{verb}'
        + (f'<span class="now__amt">{amt}</span>' if amt else "")
        + f'</div><p class="now__why">{why}</p>'
        f'<div class="now__rows">{rows_html}</div>'
        f'</div>')
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

    S["PROBS"] = probs_html(weekly_probs(data, nar, px))

    lad = nar["ladder"]
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

    S["PAYLOAD"] = json.dumps({
        "series": data["series"],
        "events": nar.get("events", {}),
        "year": pxdate[:4],
        "ladder": {"lo": alo, "hi": ahi, "step": int(lad.get("step", 10))},
        "fb": {
            "repo": "yms9654/fx-report",
            "endpoint": cfg.get("feedback_endpoint", ""),
            "date": pxdate,
            "px": f"{px:,.2f}",
            "chg": f"{chg:+.2f}",
            "verb": verb,
            "amt": amt,
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
    print(f"OK rendered {len(out):,} bytes | px {px:,.2f} | 지시 {verb} {amt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
