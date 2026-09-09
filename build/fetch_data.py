#!/usr/bin/env python3
"""USD/KRW 일별 종가 수집. 네이버 매매기준율(서울) 우선, ECB(frankfurter) 폴백."""
import json, sys, urllib.request, datetime, pathlib, zoneinfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data.json"
HIST = ROOT / "history.json"
KST = zoneinfo.ZoneInfo("Asia/Seoul")
UA = {"User-Agent": "Mozilla/5.0 (fx-report daily updater)"}
DAYS = 60          # 차트에 담을 영업일 수
PAGE_SIZE = 60     # 네이버 API 한 장 최대
PAGES = 4          # 4장 = 약 1년치 (지표·52주 계산용)


def get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def from_naver():
    """네이버 매매기준율. 페이지당 60건씩 여러 장을 받아 1년치를 모은다."""
    rows = {}
    for pg in range(1, PAGES + 1):
        url = ("https://m.stock.naver.com/front-api/marketIndex/prices"
               f"?category=exchange&reutersCode=FX_USDKRW&page={pg}&pageSize={PAGE_SIZE}")
        try:
            raw = get(url)
        except Exception:                                # noqa: BLE001
            break                                        # 받은 데까지만 쓴다
        page = raw.get("result") or raw.get("datas") or raw
        if isinstance(page, dict):
            page = page.get("prices") or next(iter(page.values()))
        if not page:
            break
        before = len(rows)
        for x in page:
            d, c = x.get("localTradedAt"), x.get("closePrice")
            if d and c:
                rows[d[:10]] = float(str(c).replace(",", ""))
        if len(rows) == before:
            break                                        # 새 데이터가 없으면 중단
    out = [{"d": d, "c": c} for d, c in sorted(rows.items())]
    if len(out) < 10:
        raise ValueError(f"naver returned only {len(out)} rows")
    return out, "네이버 매매기준율 (서울 종가)"


def from_ecb():
    start = (datetime.date.today() - datetime.timedelta(days=400)).isoformat()
    raw = get(f"https://api.frankfurter.dev/v1/{start}..?base=USD&symbols=KRW")
    out = [{"d": d, "c": float(v["KRW"])} for d, v in sorted(raw["rates"].items())]
    if len(out) < 10:
        raise ValueError(f"ecb returned only {len(out)} rows")
    return out, "ECB 참고환율 (CET 16:00)"


def main():
    errs = []
    series = source = None
    for fn in (from_naver, from_ecb):
        try:
            series, source = fn()
            break
        except Exception as e:                      # noqa: BLE001
            errs.append(f"{fn.__name__}: {e}")
    if series is None:
        print("FETCH FAILED:", " | ".join(errs), file=sys.stderr)
        return 1

    full = series
    series = full[-DAYS:]
    closes = [r["c"] for r in series]
    latest = series[-1]
    prev = series[-2]["c"] if len(series) > 1 else latest["c"]

    # 52주 범위: 누적 히스토리에서 계산 (API가 40일치만 주므로 매 실행마다 병합)
    hist = {}
    if HIST.exists():
        try:
            hist = json.loads(HIST.read_text(encoding="utf-8"))
        except Exception:                            # noqa: BLE001
            hist = {}
    hist.update({r["d"]: r["c"] for r in full})
    cutoff = (datetime.date.fromisoformat(latest["d"]) - datetime.timedelta(days=365)).isoformat()
    hist = {d: c for d, c in hist.items() if d >= cutoff}   # 365일 지난 값은 버린다
    tmp_h = HIST.with_suffix(".json.tmp")
    tmp_h.write_text(json.dumps(dict(sorted(hist.items())), indent=0), encoding="utf-8")
    tmp_h.replace(HIST)
    lo, hi = min(hist.values()), max(hist.values())

    first = closes[0]
    doc = {
        "fetched_at": datetime.datetime.now(KST).isoformat(timespec="seconds"),
        "source": source,
        "warnings": errs,
        "series": series,
        "history": [{"d": d, "c": c} for d, c in sorted(hist.items())],
        "latest": {"d": latest["d"], "c": latest["c"], "chg": round(latest["c"] - prev, 2)},
        "w52": {"lo": round(lo, 2), "hi": round(hi, 2)},
        "span_pct": round((latest["c"] - first) / first * 100, 2),
        "span_days": len(series),
        "hist_days": len(hist),
    }
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(OUT)
    print(f"OK {source} | {len(series)}건 | 최신 {latest['d']} {latest['c']:,.2f} "
          f"({doc['latest']['chg']:+.2f}) | 52w {lo:,.2f}-{hi:,.2f}")
    if errs:
        print("  fallback used, errors:", " | ".join(errs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
