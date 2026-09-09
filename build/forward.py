#!/usr/bin/env python3
"""시장 선도환율(금리평형) 계산.

과거 변동성으로 만든 랜덤워크 중앙선은 "미래 예측"이 아니라 "현재값 유지"에 가깝다.
시장이 실제로 매긴 값은 선도환율이고, 그것은 두 통화의 금리차에서 나온다.

  F(t) = S x (1 + r_KRW x t) / (1 + r_USD x t)

r_USD = SOFR (뉴욕연은 공개 API, 무키)
r_KRW = CD(91일) (한국은행 ECOS, sample 키로도 조회 가능)

2026-09-09 검증: 서울외국환중개 고시 SWAP POINT 대비 1개월물 오차 0.05원.
"""
import json, sys, urllib.request, datetime, pathlib, os, zoneinfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "forward.json"
KST = zoneinfo.ZoneInfo("Asia/Seoul")
UA = {"User-Agent": "fx-report/1.0"}
ECOS_KEY = os.environ.get("FX_ECOS_KEY", "sample")

TENORS = [("1주", 7 / 365), ("2주", 14 / 365), ("1개월", 1 / 12),
          ("2개월", 2 / 12), ("3개월", 0.25), ("6개월", 0.5), ("1년", 1.0)]

# 2026-08-31 서울외국환중개 고시 스왑포인트 (검증 기준선)
MARKET_REF = {"asof": "2026-08-31",
              "swap": {"1주": -0.12, "1개월": -0.53, "2개월": -1.10,
                       "3개월": -1.80, "6개월": -4.14, "1년": -8.50}}


def get(url, timeout=20):
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=timeout).read())


def sofr():
    d = get("https://markets.newyorkfed.org/api/rates/secured/sofr/last/1.json")
    r = d["refRates"][0]
    return float(r["percentRate"]) / 100, r["effectiveDate"], "SOFR (뉴욕연은)"


def cd91():
    end = datetime.date.today()
    start = end - datetime.timedelta(days=14)
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_KEY}/json/kr/1/10/"
           f"817Y002/D/{start:%Y%m%d}/{end:%Y%m%d}/010502000")
    d = get(url)
    if "StatisticSearch" not in d:
        raise ValueError(str(d)[:120])
    rows = [r for r in d["StatisticSearch"]["row"] if r.get("DATA_VALUE")]
    last = rows[-1]
    return float(last["DATA_VALUE"]) / 100, last["TIME"], "CD(91일) (한국은행 ECOS)"


def main():
    try:
        spot = float(json.loads((ROOT / "data.json").read_text(encoding="utf-8"))["latest"]["c"])
    except Exception as e:                                   # noqa: BLE001
        print("data.json 없음:", e, file=sys.stderr)
        return 1

    warn = []
    try:
        ru, du, su = sofr()
    except Exception as e:                                   # noqa: BLE001
        print("SOFR 실패:", e, file=sys.stderr)
        return 1
    try:
        rk, dk, sk = cd91()
    except Exception as e:                                   # noqa: BLE001
        warn.append(f"CD91 조회 실패({e}) — 한은 기준금리 3.00% 로 대체")
        rk, dk, sk = 0.0300, "-", "한국은행 기준금리 (대체값)"

    curve = []
    for lab, t in TENORS:
        f = spot * (1 + rk * t) / (1 + ru * t)
        row = {"tenor": lab, "t": round(t, 5), "rate": round(f, 2), "swap": round(f - spot, 2)}
        if lab in MARKET_REF["swap"]:
            row["mkt_swap"] = MARKET_REF["swap"][lab]
            row["err"] = round(abs(row["swap"] - row["mkt_swap"]), 3)
        curve.append(row)

    m1 = next(c for c in curve if c["tenor"] == "1개월")
    doc = {
        "computed_at": datetime.datetime.now(KST).isoformat(timespec="seconds"),
        "spot": spot,
        "krw": {"rate": rk, "asof": dk, "source": sk},
        "usd": {"rate": ru, "asof": du, "source": su},
        "curve": curve,
        "m1": m1["rate"],
        "drift_month_pct": round((m1["rate"] / spot - 1) * 100, 4),
        "validation": MARKET_REF,
        "warnings": warn,
    }
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(OUT)
    errs = [c["err"] for c in curve if "err" in c and c["t"] <= 0.25]
    print(f"OK 선도환율 | 현물 {spot:,.2f} | KRW {rk*100:.2f}%({dk}) USD {ru*100:.2f}%({du}) "
          f"| 1개월 {m1['rate']:,.2f} ({m1['swap']:+.2f}) | 3개월 이하 최대오차 {max(errs):.2f}원")
    for w in warn:
        print("  WARN", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
