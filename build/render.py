#!/usr/bin/env python3
"""data.json + narrative.json -> docs/index.html"""
import json, sys, html, pathlib, datetime, zoneinfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
KST = zoneinfo.ZoneInfo("Asia/Seoul")
E = lambda s: html.escape(str(s), quote=False)
NUM = lambda v: f"{float(v):,.0f}"


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

    if hit_cut:
        return ("cut", "판다", "잔여 전량",
                f"손절선 <b>{NUM(stop)}</b>을 이탈했습니다. 계획대로라면 여기서는 "
                f"버티지 않고 남은 물량을 전부 정리합니다.",
                [("현재", f"<b>{px:,.2f}</b> — 손절선 대비 {px-stop:+,.1f}원", "", "dn")])

    if hit_sell:
        return ("sell", "판다", f"{hit_sell['pct']} 매도",
                f"{E(hit_sell['title'])} 구간(<b>{NUM(hit_sell['lo'])}–{NUM(hit_sell['hi'])}</b>)에 "
                f"들어왔습니다. 계획 비중 <b>{E(hit_sell['pct'])}</b>를 지금 집행합니다.",
                [("현재", f"<b>{px:,.2f}</b>", "", "up")])

    # 대기: 위로 가장 가까운 매도 구간과 아래 손절까지의 거리를 보여준다
    nxt = next((z for z in sells if float(z["lo"]) > px), None)
    rows = []
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
        f'{gauge(px, nar)}</div>')
    S["HEADLINE"] = (E(nar["headline"]) +
                     (f'<br><span class="thin">{E(nar["headline_thin"])}</span>'
                      if nar.get("headline_thin") else ""))
    S["SUB"] = E(nar["sub"])
    S["PXDATE"] = pxdate.replace("-", ".")
    ip, fp = f"{px:,.2f}".split(".")
    S["PXBIG"] = f'{ip}<span style="font-size:.5em">.{fp}</span>'
    S["PXROW"] = (
        f'<span>전일비 <b class="{chg_cls}">{chg:+.2f}</b></span>'
        f'<span>52주 <b>{data["w52"]["lo"]:,.2f} – {data["w52"]["hi"]:,.2f}</b></span>'
        f'<span>{data["span_days"]}영업일 <b>{data["span_pct"]:+.1f}%</b></span>')
    S["BAND"] = f'{NUM(nar["verdict"]["band_lo"])} – {NUM(nar["verdict"]["band_hi"])}'
    S["VERDICT"] = "".join(f"<p>{p}</p>" for p in nar["verdict"]["paras"])
    S["CHARTLEDE"] = E(nar.get("chart_lede", ""))
    S["NDAYS"] = str(data["span_days"])
    S["FORCELEDE"] = E(nar.get("force_lede", ""))

    def force(side, cls, title, direction):
        items = "".join(
            f'<li><span class="tag tag--{"new" if f.get("new") else "std"}">{E(f["tag"])}</span>'
            f'<span>{f["text"]}</span></li>' for f in nar["forces"][side])
        return (f'<div class="force force--{cls}"><h3>{title}</h3>'
                f'<div class="dir">{direction}</div><ul>{items}</ul></div>')

    S["FORCES"] = (force("down", "dn", "원화 강세", "환율 하락 압력") +
                   force("up", "up", "달러 강세", "환율 상승 압력"))

    sc = nar["scenario"]
    S["SCENLEDE"] = E(nar.get("scen_lede", ""))
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
    S["LADDERCAP"] = nar.get("ladder_caption", "")

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
