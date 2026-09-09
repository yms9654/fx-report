#!/usr/bin/env python3
"""가격에서만 계산되는 기술적 지표와 예측 밴드. 서술과 무관하게 결정론적이다."""
import math, statistics

PHI = lambda z: 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
Z50, Z80 = 0.6745, 1.2816


def sma(c, n):
    return sum(c[-n:]) / n if len(c) >= n else None


def rsi(c, n=14):
    """Wilder RSI."""
    if len(c) < n + 1:
        return None
    d = [b - a for a, b in zip(c, c[1:])]
    g = sum(x for x in d[:n] if x > 0) / n
    l = sum(-x for x in d[:n] if x < 0) / n
    for x in d[n:]:
        g = (g * (n - 1) + max(x, 0)) / n
        l = (l * (n - 1) + max(-x, 0)) / n
    if l == 0:
        return 100.0
    return 100 - 100 / (1 + g / l)


def bollinger(c, n=20, k=2.0):
    if len(c) < n:
        return None
    m = sma(c, n)
    sd = statistics.pstdev(c[-n:])
    if sd == 0:
        return None
    up, lo = m + k * sd, m - k * sd
    return {"mid": m, "up": up, "lo": lo,
            "pctb": (c[-1] - lo) / (up - lo), "width": (up - lo) / m * 100}


def technicals(hist):
    """추세·모멘텀 판정. 신호는 가격에서만 나온다."""
    c = [r["c"] for r in hist]
    px = c[-1]
    ma20, ma60, ma120 = sma(c, 20), sma(c, 60), sma(c, 120)
    r = rsi(c)
    bb = bollinger(c)

    sig = []                                   # (설명, 방향) 방향: -1 하락 / +1 상승
    if ma20:
        sig.append((f"종가 < MA20" if px < ma20 else "종가 > MA20", -1 if px < ma20 else 1))
    if ma20 and ma60:
        sig.append(("MA20 < MA60" if ma20 < ma60 else "MA20 > MA60", -1 if ma20 < ma60 else 1))
    if ma60:
        sig.append((f"종가 < MA60" if px < ma60 else "종가 > MA60", -1 if px < ma60 else 1))
    score = sum(v for _, v in sig)

    if score <= -3:
        trend, tlabel = "down", "하락추세"
    elif score < 0:
        trend, tlabel = "down", "약세"
    elif score >= 3:
        trend, tlabel = "up", "상승추세"
    elif score > 0:
        trend, tlabel = "up", "강세"
    else:
        trend, tlabel = "flat", "혼조"

    mom = None
    if r is not None:
        mom = "과매도" if r < 30 else "과매수" if r > 70 else "중립"

    return {"px": px, "ma20": ma20, "ma60": ma60, "ma120": ma120,
            "rsi": r, "mom": mom, "bb": bb, "score": score,
            "trend": trend, "tlabel": tlabel, "signals": sig,
            "vs20": (px / ma20 - 1) * 100 if ma20 else None,
            "vs60": (px / ma60 - 1) * 100 if ma60 else None}


def forecast(hist, px, mu_month, alt_month=None, days=20, vol_win=60):
    """로그정규 예측 밴드.

    변동성은 실측, 중앙선 드리프트(mu_month)는 시장 선도환율에서 온다.
    alt_month 를 주면 그 경로(분석 기대값)를 비교선으로 함께 낸다."""
    c = [r["c"] for r in hist][-vol_win:]
    rets = [math.log(b / a) for a, b in zip(c, c[1:]) if a > 0 and b > 0]
    if len(rets) < 10:
        return None
    sig = statistics.stdev(rets)
    if sig <= 0:
        return None
    mu = math.log(float(mu_month) / px) / 21
    mu_alt = math.log(float(alt_month) / px) / 21 if alt_month else None
    pts = []
    for t in range(1, days + 1):
        s, m = sig * math.sqrt(t), mu * t
        row = {"t": t,
               "mid": px * math.exp(m),
               "lo50": px * math.exp(m - Z50 * s), "hi50": px * math.exp(m + Z50 * s),
               "lo80": px * math.exp(m - Z80 * s), "hi80": px * math.exp(m + Z80 * s)}
        if mu_alt is not None:
            row["alt"] = px * math.exp(mu_alt * t)
        pts.append(row)
    return {"pts": pts, "sig_d": sig * 100, "sig_a": sig * math.sqrt(252) * 100,
            "mu_m": (math.exp(mu * 21) - 1) * 100, "mu": mu,
            "alt_m": (math.exp(mu_alt * 21) - 1) * 100 if mu_alt is not None else None,
            "n": len(rets)}


def trigger_drift(log, cur_stop, lookback=5):
    """손절선이 가격을 따라 내려가고 있는지 감시한다.
    계획을 매일 다시 쓰면 손절이 영원히 발동하지 않는 문제를 잡기 위한 것."""
    prev = [e for e in log[-lookback - 1:-1] if "stop" in e]
    if len(prev) < 2:
        return None
    downs = sum(1 for a, b in zip(prev, prev[1:]) if b["stop"] < a["stop"])
    if prev[-1]["stop"] > cur_stop:
        downs += 1
    if downs < 2:
        return None
    first = prev[0]
    return {"n": downs, "from": first["stop"], "to": cur_stop,
            "days": len(prev), "since": first.get("d", "?"),
            "px_from": first.get("px"), "drop": first["stop"] - cur_stop}
