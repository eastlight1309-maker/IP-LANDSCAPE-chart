# -*- coding: utf-8 -*-
"""
metrics.py — 공통 지표 계산 모듈.

포함 지표와 계산식:
- lift(a,b)  = P(A∩B) / (P(A)·P(B))                    (독립 대비 동시출현 배수)
- pmi(a,b)   = log2( P(A∩B) / (P(A)·P(B)) )
- npmi(a,b)  = pmi / (-log2 P(A∩B))                     (정규화 PMI, [-1,1])
- jaccard    = |A∩B| / |A∪B|
- hhi        = Σ share_i^2                              (허핀달 집중도, [0,1])
- shannon_entropy = -Σ p_i log2 p_i                     (다양성)
- CAGR 대체지표 사다리 (robust_growth):
    ① CAGR = (end/start)^(1/y) - 1  (start>0, end>0 일 때만)
    ② 최근 N년 선형회귀 기울기(연평균 건수 대비 비율)
    ③ 과거 N년 대비 최근 N년 증가율
    ④ Poisson trend (log-link GLM 근사: log1p 회귀 기울기)
    ⑤ log1p slope
  각 단계는 데이터 조건이 안 되면 다음 단계로 폴백하며 사용한 방법명을 함께 반환.
- 정규화 파이프라인 (normalize_series):
    log1p 변환(옵션) → Winsorization(양측 pct) → Robust scaling(IQR) 또는 Min-Max
    → [0,1] 클리핑. 분모 0(상수 시리즈)이면 전체 0.5 반환.
- weighted_geometric_mean: Π x_i^{w_i} ^ (1/Σw), x는 [0,1]+ε 클리핑 (점수 지배 방지)

예외처리: 분모 0, 결측, 표본<2 등은 모두 명시적으로 처리하고 None 또는 폴백 반환.
"""
import math

import numpy as np
import pandas as pd


def safe_div(a, b, default=0.0):
    """0 나눗셈 방지 나눗셈."""
    try:
        b = float(b)
        if b == 0 or math.isnan(b):
            return default
        return float(a) / b
    except (TypeError, ValueError):
        return default


def lift(n_ab, n_a, n_b, n_total):
    """Lift = (n_ab/N) / ((n_a/N)(n_b/N)). 분모 0 이면 0."""
    if min(n_a, n_b, n_total) <= 0:
        return 0.0
    return safe_div(n_ab * n_total, n_a * n_b, 0.0)


def pmi(n_ab, n_a, n_b, n_total):
    """PMI(log2). P(A∩B)=0 이면 None."""
    if n_ab <= 0 or min(n_a, n_b, n_total) <= 0:
        return None
    val = safe_div(n_ab * n_total, n_a * n_b, 0.0)
    return math.log2(val) if val > 0 else None


def npmi(n_ab, n_a, n_b, n_total):
    """정규화 PMI = pmi / (-log2 P(A∩B)), 범위 [-1,1]. 계산 불가 시 None."""
    p = pmi(n_ab, n_a, n_b, n_total)
    if p is None:
        return None
    p_ab = safe_div(n_ab, n_total, 0.0)
    if p_ab <= 0 or p_ab >= 1:
        return None
    denom = -math.log2(p_ab)
    return p / denom if denom > 0 else None


def jaccard(n_ab, n_a, n_b):
    """Jaccard = |A∩B| / |A∪B|."""
    union = n_a + n_b - n_ab
    return safe_div(n_ab, union, 0.0)


def hhi(counts):
    """허핀달-허쉬만 지수: Σ(share^2). 빈 입력이면 None."""
    arr = np.asarray([c for c in counts if c and c > 0], dtype=float)
    if arr.size == 0:
        return None
    shares = arr / arr.sum()
    return float(np.sum(shares ** 2))


def shannon_entropy(counts, normalize=False):
    """샤논 엔트로피(-Σ p log2 p). normalize=True 면 log2(k)로 나눠 [0,1]."""
    arr = np.asarray([c for c in counts if c and c > 0], dtype=float)
    if arr.size == 0:
        return None
    p = arr / arr.sum()
    ent = float(-np.sum(p * np.log2(p)))
    if normalize:
        return ent / math.log2(len(p)) if len(p) > 1 else 0.0
    return ent


def year_counts(years, weights=None, year_min=None, year_max=None):
    """연도 배열 → 연속 연도 인덱스의 건수 Series (누락 연도 0 채움)."""
    s = pd.Series(years).dropna().astype(int)
    if weights is not None:
        w = pd.Series(weights)
        w = w[s.index] if len(w) == len(pd.Series(years)) else None
    else:
        w = None
    if not len(s):
        return pd.Series(dtype=float)
    counts = (pd.Series(1.0, index=s.index).groupby(s.values).sum() if w is None
              else w.groupby(s.values).sum())
    lo = int(year_min) if year_min is not None else int(counts.index.min())
    hi = int(year_max) if year_max is not None else int(counts.index.max())
    full = pd.Series(0.0, index=range(lo, hi + 1))
    full.update(counts)
    return full


def cagr(series):
    """CAGR = (end/start)^(1/years)-1. start<=0 또는 end<=0 또는 기간<1 이면 None."""
    s = pd.Series(series).dropna()
    if len(s) < 2:
        return None
    start, end = float(s.iloc[0]), float(s.iloc[-1])
    years = len(s) - 1
    if start <= 0 or end <= 0 or years < 1:
        return None
    return (end / start) ** (1.0 / years) - 1.0


def linreg_slope(series):
    """최소제곱 선형회귀 기울기 (x=0..n-1). 표본<2 이면 None."""
    s = pd.Series(series).dropna().astype(float)
    if len(s) < 2:
        return None
    x = np.arange(len(s), dtype=float)
    return float(np.polyfit(x, s.values, 1)[0])


def robust_growth(counts_by_year, recent_years=3):
    """최근 성장률 계산 (CAGR 대체지표 사다리). 반환: (growth, method).

    ① 최근 recent_years 구간 CAGR
    ② 최근 구간 선형회귀 기울기 ÷ 구간 평균 (비율화)
    ③ 과거 recent_years 대비 최근 recent_years 증가율
    ④ Poisson trend: log(count+1) 회귀 기울기 → exp(slope)-1
    ⑤ log1p slope (그대로)
    계산 가능한 첫 방법을 사용. 전부 불가하면 (None, "insufficient").
    """
    s = pd.Series(counts_by_year).dropna().astype(float)
    if len(s) == 0:
        return None, "insufficient"
    recent = s.iloc[-recent_years:] if len(s) >= recent_years else s
    # ① CAGR
    val = cagr(recent)
    if val is not None:
        return float(val), "cagr"
    # ② 선형회귀 기울기 / 평균
    slope = linreg_slope(recent)
    mean = float(recent.mean()) if len(recent) else 0.0
    if slope is not None and mean > 0:
        return float(slope / mean), "linreg_slope_ratio"
    # ③ 기간 대비 증가율
    if len(s) >= 2 * recent_years:
        prev = float(s.iloc[-2 * recent_years:-recent_years].sum())
        cur = float(s.iloc[-recent_years:].sum())
        if prev > 0:
            return (cur - prev) / prev, "period_over_period"
        if cur > 0:
            return 1.0, "period_over_period_newzero"
    # ④ Poisson trend 근사: log1p 회귀 기울기 → exp-1
    log_slope = linreg_slope(np.log1p(recent.values))
    if log_slope is not None:
        return float(math.exp(log_slope) - 1.0), "poisson_trend_approx"
    # ⑤ log1p slope
    if len(s) >= 2:
        log_slope_all = linreg_slope(np.log1p(s.values))
        if log_slope_all is not None:
            return float(log_slope_all), "log1p_slope"
    return None, "insufficient"


def winsorize(arr, pct=0.02):
    """양측 pct 백분위 Winsorization."""
    a = np.asarray(arr, dtype=float)
    if a.size == 0:
        return a
    lo, hi = np.nanpercentile(a, pct * 100), np.nanpercentile(a, (1 - pct) * 100)
    return np.clip(a, lo, hi)


def normalize_series(values, log=True, winsor_pct=0.02, method="robust"):
    """정규화 파이프라인: log1p → winsorize → robust(IQR) 또는 minmax → [0,1] 클립.

    상수 시리즈(분모 0)는 전체 0.5. NaN 은 0.0 으로 치환.
    """
    a = np.asarray(values, dtype=float)
    if a.size == 0:
        return a
    a = np.where(np.isnan(a), 0.0, a)
    if log:
        a = np.log1p(np.clip(a, a.min() if a.min() < 0 else 0, None) - min(a.min(), 0.0)) \
            if a.min() < 0 else np.log1p(a)
    a = winsorize(a, winsor_pct)
    if method == "robust":
        med = np.median(a)
        q1, q3 = np.percentile(a, 25), np.percentile(a, 75)
        iqr = q3 - q1
        if iqr <= 1e-12:
            return _minmax(a)
        scaled = (a - med) / iqr
        return _minmax(scaled)
    return _minmax(a)


def _minmax(a):
    lo, hi = float(np.min(a)), float(np.max(a))
    if hi - lo <= 1e-12:
        return np.full_like(a, 0.5, dtype=float)
    return (a - lo) / (hi - lo)


def weighted_geometric_mean(components, weights):
    """가중 기하평균: Π max(x,ε)^w ^ (1/Σw). components/weights: {name: value/weight}.

    특정 변수의 점수 지배를 방지하기 위해 각 성분은 [ε,1] 로 클리핑된 정규화 점수를
    가정한다. 가중치 합이 0 이면 None.
    """
    eps = 1e-6
    total_w = sum(w for w in weights.values() if w > 0)
    if total_w <= 0:
        return None
    log_sum = 0.0
    for name, w in weights.items():
        if w <= 0:
            continue
        x = components.get(name)
        x = eps if x is None else min(max(float(x), eps), 1.0)
        log_sum += w * math.log(x)
    return math.exp(log_sum / total_w)


def percentile_rank(values, value):
    """value 의 백분위(0~100). 빈 배열이면 None."""
    a = np.asarray([v for v in values if v is not None and not
                    (isinstance(v, float) and math.isnan(v))], dtype=float)
    if a.size == 0 or value is None:
        return None
    return float((a <= float(value)).mean() * 100.0)


def cross_correlation_lag(series_a, series_b, max_lag=3, min_overlap=4):
    """두 연도 시계열의 lagged correlation.

    lag>0: A 가 B 를 lag 년 선행(A[t] ~ B[t+lag]).
    반환: (best_lag, best_corr) — |corr| 최대 lag. 표본 부족 시 (None, None).
    """
    a = pd.Series(series_a).astype(float)
    b = pd.Series(series_b).astype(float)
    idx = a.index.intersection(b.index)
    if len(idx) < min_overlap:
        return None, None
    best_lag, best_corr = None, None
    for lag in range(-max_lag, max_lag + 1):
        a_idx = [i for i in idx if (i + lag) in b.index]
        if len(a_idx) < min_overlap:
            continue
        x = a.loc[a_idx].values
        y = b.loc[[i + lag for i in a_idx]].values
        if np.std(x) < 1e-12 or np.std(y) < 1e-12:
            continue
        corr = float(np.corrcoef(x, y)[0, 1])
        if best_corr is None or abs(corr) > abs(best_corr):
            best_lag, best_corr = lag, corr
    return best_lag, best_corr


def cosine_sim_vec(u, v):
    """두 벡터의 코사인 유사도. 영벡터면 0."""
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    nu, nv = np.linalg.norm(u), np.linalg.norm(v)
    if nu <= 1e-12 or nv <= 1e-12:
        return 0.0
    return float(np.dot(u, v) / (nu * nv))
