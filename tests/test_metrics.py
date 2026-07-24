# -*- coding: utf-8 -*-
"""공통 지표: Lift/PMI/HHI/entropy/성장률 사다리/정규화/기하평균."""
import math

import numpy as np
import pandas as pd

from src.metrics import (lift, pmi, npmi, jaccard, hhi, shannon_entropy, cagr,
                         robust_growth, normalize_series, weighted_geometric_mean,
                         year_counts, cross_correlation_lag, percentile_rank)


def test_lift_pmi_jaccard():
    # N=100, A=20, B=10, AB=5 → P(AB)=.05, P(A)P(B)=.02 → lift 2.5
    assert abs(lift(5, 20, 10, 100) - 2.5) < 1e-9
    assert abs(pmi(5, 20, 10, 100) - math.log2(2.5)) < 1e-9
    v = npmi(5, 20, 10, 100)
    assert v is not None and -1 <= v <= 1
    assert abs(jaccard(5, 20, 10) - 5.0 / 25.0) < 1e-9
    # 분모 0 처리
    assert lift(0, 0, 10, 100) == 0.0
    assert pmi(0, 20, 10, 100) is None


def test_hhi_entropy():
    assert abs(hhi([50, 50]) - 0.5) < 1e-9
    assert hhi([100]) == 1.0
    assert hhi([]) is None
    assert abs(shannon_entropy([50, 50]) - 1.0) < 1e-9
    assert shannon_entropy([10, 10, 10, 10], normalize=True) == 1.0


def test_year_counts_fills_gaps():
    s = year_counts([2018, 2018, 2021])
    assert list(s.index) == [2018, 2019, 2020, 2021]
    assert s.loc[2019] == 0.0


# --- 케이스 ⑤: 최근 연도 0건 포함 시계열 → CAGR 불가, 대체지표 폴백 ---
def test_growth_ladder_with_zero_recent():
    s = pd.Series([5, 8, 12, 0], index=[2019, 2020, 2021, 2022])
    growth, method = robust_growth(s, recent_years=3)
    assert growth is not None
    assert method != "cagr"  # end=0 → CAGR 불가 → 대체지표 사용
    s2 = pd.Series([2, 4, 8], index=[2020, 2021, 2022])
    g2, m2 = robust_growth(s2, recent_years=3)
    assert m2 == "cagr" and abs(g2 - 1.0) < 1e-9
    g3, m3 = robust_growth(pd.Series(dtype=float))
    assert g3 is None and m3 == "insufficient"
    # ④ 특허 1건뿐인 시계열
    g4, m4 = robust_growth(pd.Series([1], index=[2022]), recent_years=3)
    assert (g4 is None) or isinstance(g4, float)


def test_normalize_series_constant_and_dominance():
    out = normalize_series([5, 5, 5])
    assert np.allclose(out, 0.5)
    vals = [1, 2, 3, 1000000]  # 극단값 지배 방지 (winsorize)
    out2 = normalize_series(vals, log=True, winsor_pct=0.02)
    assert out2.min() >= 0 and out2.max() <= 1


def test_weighted_geometric_mean():
    v = weighted_geometric_mean({"a": 0.5, "b": 0.5}, {"a": 1, "b": 1})
    assert abs(v - 0.5) < 1e-9
    assert weighted_geometric_mean({"a": 1.0}, {"a": 0}) is None
    # None 성분은 epsilon 처리되어 0 에 가까운 점수
    v2 = weighted_geometric_mean({"a": None, "b": 1.0}, {"a": 1, "b": 1})
    assert v2 < 0.1


def test_cross_correlation_lag():
    idx = list(range(2010, 2022))
    a = pd.Series([i % 5 + i * 0.5 for i in range(12)], index=idx)
    b = a.shift(-2).dropna()  # A 가 2년 선행 (B[t]=A[t+2] → corr(A[t],B[t+lag]))
    lag, corr = cross_correlation_lag(a, b, max_lag=3)
    assert lag is not None and corr is not None
    assert abs(corr) > 0.9
    # 표본 부족
    lag2, corr2 = cross_correlation_lag(a.head(2), b.head(2))
    assert lag2 is None


def test_percentile_rank():
    assert percentile_rank([1, 2, 3, 4], 4) == 100.0
    assert percentile_rank([], 1) is None
