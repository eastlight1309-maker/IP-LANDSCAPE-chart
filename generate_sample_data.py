# -*- coding: utf-8 -*-
"""
generate_sample_data.py — 테스트·데모 전용 합성 데이터 생성 스크립트.

반도체 패키징 도메인 예시로 WIPS 스타일 헤더의 합성 Dataset 을 생성한다.
⚠ 테스트 전용: 앱 본체는 절대 데이터를 임의 생성하지 않는다 (Demo mode 제외).

최소 Dataset Schema (개념 → 예시 헤더):
  공개번호, 출원번호, 등록번호, 패밀리 ID, 발명의 명칭, 요약, 독립청구항, 출원인,
  발명자, 출원일, 등록일, 우선일, 만료예정일, 국가, 법적상태, 등록 여부, 존속 여부,
  인용 수, 피인용 수, 패밀리 수, 패밀리 국가 수, 기술 대분류, 기술 중분류,
  다중 기술분류, 분류 신뢰도, 해결과제, 해결수단, 제품, 공정, 임베딩 벡터,
  자사 특허 여부

사용법:
  python generate_sample_data.py [출력.csv] [--rows N]
  또는 테스트에서 generate_sample(...) / 시나리오 함수 import.

시나리오 함수 (tests/ 의 12개 요구 케이스 재현):
  generate_sample(n)                     — ① 필수 컬럼 전부 존재
  drop_optional_columns(df)              — ② 일부 선택 컬럼 없음
  generate_sample(sep=…)                 — ③ 쉼표/세미콜론/파이프/JSON 다중분류
  with_singleton_class(df)               — ④ 특허 1건뿐인 기술분류
  with_zero_recent_year(df)              — ⑤ 최근 연도 0건 시계열
  with_duplicate_families(df)            — ⑥ 중복 패밀리
  with_applicant_variants(df)            — ⑦ 출원인명 다형
  with_missing_legal_status(df)          — ⑧ 법적상태 누락
  without_citations(df)                  — ⑨ 인용 데이터 없음
  without_embeddings(df)                 — ⑩ 임베딩 없음
  generate_sample(n=50000)               — ⑪ 대용량 성능 테스트
  (기본 생성 데이터에 한글·영문·일문 혼재  — ⑫)
"""
import json
import sys

import numpy as np
import pandas as pd

L1 = ["패키징", "본딩", "테스트", "소재"]
L2 = {
    "패키징": ["FOWLP", "FOPLP", "2.5D Interposer", "3D 적층", "SiP"],
    "본딩": ["하이브리드 본딩", "TCB", "와이어 본딩", "플립칩"],
    "테스트": ["웨이퍼 테스트", "번인 테스트", "KGD 선별"],
    "소재": ["몰드 컴파운드", "언더필", "재배선 소재"],
}
COMPANIES = ["삼성전자", "SK하이닉스", "TSMC", "Intel", "ASE", "Amkor",
             "네패스", "LB세미콘", "JCET", "무라타제작소"]
AGENTS = ["특허법인 가온", "특허법인 나래", "특허법인 다올", "리앤목 특허법인",
          "특허법인 태평양", "법률사무소 한별(소송특화)"]
PROBLEMS = ["휨(warpage) 저감", "미세피치 접합 신뢰성", "방열 특성 개선",
            "수율 향상", "패키지 두께 감소", "신호 무결성 확보"]
SOLUTIONS = ["몰드 소재 조성 변경", "범프 구조 개선", "공정 온도 프로파일 제어",
             "적층 구조 재설계", "검사 알고리즘 고도화", "재배선층 최적화"]
PRODUCTS = ["모바일 AP", "HBM", "차량용 SoC", "전력 반도체", "이미지센서"]
PROCESSES = ["몰딩", "리플로우", "다이어태치", "그라인딩", "본딩"]
TITLES_EN = ["Semiconductor package with improved warpage control",
             "Hybrid bonding structure for stacked dies",
             "Fan-out wafer level package and manufacturing method"]
TITLES_JP = ["半導体パッケージおよびその製造方法", "積層型半導体装置", "配線基板の接合構造"]

EMB_DIM = 8


def _embed(l1_idx, l2_idx, rng):
    """기술분류 기반 결정적 클러스터 + 노이즈 임베딩 (테스트 재현성)."""
    base = np.zeros(EMB_DIM)
    base[l1_idx % EMB_DIM] = 2.0
    base[(l1_idx * 3 + l2_idx) % EMB_DIM] += 1.0
    return (base + rng.normal(0, 0.25, EMB_DIM)).round(4)


def generate_sample(n=600, seed=42, sep="; ", multiclass_format="sep",
                    year_min=2012, year_max=2024):
    """합성 특허 DataFrame 생성 (WIPS 스타일 한글 헤더).

    multiclass_format: 'sep'(sep 문자열 구분) | 'json'(JSON 배열 문자열)
    """
    rng = np.random.default_rng(seed)
    rows = []
    n_years = year_max - year_min + 1
    # 성장 편향: 최근 연도에 더 많은 문헌 (성장 기술 검출 케이스)
    year_weights = np.linspace(1.0, 3.0, n_years)
    year_weights /= year_weights.sum()
    for i in range(n):
        l1_idx = int(rng.integers(0, len(L1)))
        l1 = L1[l1_idx]
        l2_list = L2[l1]
        l2_idx = int(rng.integers(0, len(l2_list)))
        l2 = l2_list[l2_idx]
        year = int(rng.choice(np.arange(year_min, year_max + 1), p=year_weights))
        comp = COMPANIES[int(rng.integers(0, len(COMPANIES)))]
        granted = bool(rng.random() < 0.55)
        active = granted and bool(rng.random() < 0.8)
        multi = [l2]
        if rng.random() < 0.45:  # 다중분류 (융합 신호)
            other_l1 = L1[int(rng.integers(0, len(L1)))]
            other = L2[other_l1][int(rng.integers(0, len(L2[other_l1])))]
            if other != l2:
                multi.append(other)
        if multiclass_format == "json":
            multi_str = json.dumps(multi, ensure_ascii=False)
        else:
            multi_str = sep.join(multi)
        lang = rng.random()
        if lang < 0.7:
            title = "%s 기반 %s 기술" % (l2, PROBLEMS[i % len(PROBLEMS)])
        elif lang < 0.85:
            title = TITLES_EN[i % len(TITLES_EN)]
        else:
            title = TITLES_JP[i % len(TITLES_JP)]
        co_applicant = rng.random() < 0.12
        applicant_field = comp if not co_applicant else \
            "%s; %s" % (comp, COMPANIES[int(rng.integers(0, len(COMPANIES)))])
        inv_pool_base = (COMPANIES.index(comp)) * 12
        invs = ["발명자%02d" % (inv_pool_base + int(rng.integers(0, 18)))
                for _ in range(int(rng.integers(1, 4)))]
        month = int(rng.integers(1, 13))
        has_trial = bool(rng.random() < 0.05)
        rows.append({
            "공개번호": "KR10-%d-%07dA" % (year, i),
            "출원번호": "KR10-%d-%07d" % (year, i),
            "등록번호": ("KR10-%07d" % (2000000 + i)) if granted else "",
            "패밀리 ID": "FAM%05d" % (i // 2),  # 2건/패밀리 평균 (dedup 케이스)
            "발명의 명칭": title,
            "요약": "%s 분야에서 %s 문제를 해결하기 위해 %s 을(를) 적용한다."
                   % (l1, PROBLEMS[i % len(PROBLEMS)], SOLUTIONS[i % len(SOLUTIONS)]),
            "독립청구항": ("반도체 패키지에 있어서, %s 구조를 포함하며, %s 특징을 갖는 "
                      "것을 특징으로 하는 %s 분야의 반도체 장치 및 그 제조 방법으로서 "
                      "상기 구조는 %s 공정으로 형성되는 반도체 패키지."
                      % (l2, SOLUTIONS[i % len(SOLUTIONS)], l1,
                         PROCESSES[i % len(PROCESSES)])),
            "출원인": applicant_field,
            "발명자": "; ".join(invs),
            "출원일": "%d-%02d-15" % (year, month),
            "등록일": ("%d-%02d-20" % (year + 2, month)) if granted else "",
            "우선일": "%d-%02d-01" % (year, month),
            "만료예정일": "%d-%02d-14" % (year + 20, month),
            "국가": ["KR", "US", "JP", "CN", "EP"][i % 5],
            "법적상태": ("등록" if active else
                     ("존속기간만료" if granted else
                      ["공개", "심사중", "거절", "취하"][i % 4])),
            "등록 여부": "Y" if granted else "N",
            "존속 여부": "Y" if active else "N",
            "인용 수": int(rng.poisson(4)),
            "피인용 수": int(rng.poisson(3)) + (10 if i % 37 == 0 else 0),
            "패밀리 수": int(rng.integers(1, 9)),
            "패밀리 국가 수": int(rng.integers(1, 6)),
            "패밀리 국가 목록": "; ".join(
                ["KR", "US", "JP", "CN", "EP", "DE", "TW"][:int(rng.integers(1, 6))]),
            "기술 대분류": l1,
            "기술 중분류": l2,
            "다중 기술분류": multi_str,
            "분류 신뢰도": round(float(rng.uniform(0.3, 1.0)), 3),
            "청구항 수": int(rng.integers(3, 35)),
            "독립항 수": int(rng.integers(1, 5)),
            "IPC분류": "; ".join(["H01L 23/28", "H01L 25/065", "H01L 21/56",
                                  "H01L 24/00", "G01R 31/26"][:int(rng.integers(1, 4))]),
            "해결과제": PROBLEMS[i % len(PROBLEMS)],
            "해결수단": SOLUTIONS[i % len(SOLUTIONS)],
            "제품": PRODUCTS[i % len(PRODUCTS)],
            "공정": PROCESSES[i % len(PROCESSES)],
            "임베딩 벡터": json.dumps(_embed(l1_idx, l2_idx, rng).tolist()),
            "자사 특허 여부": "Y" if comp == "네패스" else "N",
            # ---- 심층 WIPS 필드 (연차료·대리인·심사·심판) ----
            "소멸일": ("%d-%02d-10" % (year + 2 + int(rng.integers(2, 14)), month))
                    if (granted and not active and rng.random() < 0.8) else "",
            "대리인": (AGENTS[4 + (i % 2)]
                    if (year >= year_max - 3 and rng.random() < 0.35)
                    else AGENTS[COMPANIES.index(comp) % 4]),
            "우선심사 여부": "Y" if ((l1 == L1[0] and year >= year_max - 3
                                and rng.random() < 0.45) or rng.random() < 0.07) else "N",
            "심사청구일": "%d-%02d-01" % (year + int(rng.integers(0, 2)), month),
            "거절이유통지 횟수": int(rng.poisson(1.2)) + (3 if i % 41 == 0 else 0),
            "심사관 인용문헌 수": int(rng.poisson(4 if l1 == L1[1] else 2)),
            "출원인 인용문헌 수": int(rng.poisson(2)),
            "원출원번호": ("KR10-%d-%07d" % (max(year_min, year - 1), max(0, i - 5)))
                     if rng.random() < 0.08 else "",
            "도면 수": int(rng.integers(2, 12)) + (COMPANIES.index(comp) % 3) * 6,
            "명세서 페이지 수": int(rng.integers(8, 60)),
            "심판 이력": (["무효심판", "거절결정불복심판"][i % 2] if has_trial else ""),
            "심판 청구인": (COMPANIES[(COMPANIES.index(comp) + 1) % len(COMPANIES)]
                      if (has_trial and i % 2 == 0) else ""),
        })
    return pd.DataFrame(rows)


# ---------------- 테스트 케이스 변형 ----------------
def drop_optional_columns(df):
    """② 일부 선택 컬럼 제거 (피인용·패밀리·해결과제 등)."""
    drop = ["피인용 수", "인용 수", "패밀리 수", "패밀리 국가 수", "해결과제", "해결수단",
            "임베딩 벡터", "분류 신뢰도", "만료예정일", "자사 특허 여부"]
    return df.drop(columns=[c for c in drop if c in df.columns])


def with_singleton_class(df):
    """④ 특허 1건뿐인 기술분류 추가."""
    row = df.iloc[0].copy()
    row["공개번호"] = "KR10-2024-9999999A"
    row["패밀리 ID"] = "FAM99999"
    row["기술 중분류"] = "양자 패키징"
    row["다중 기술분류"] = "양자 패키징"
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)


def with_zero_recent_year(df):
    """⑤ 최근 연도 0건: 최신 2개 연도 문헌 제거 후 더 최신 연도 1건만 추가."""
    years = pd.to_datetime(df["출원일"]).dt.year
    y_max = years.max()
    out = df[years < y_max - 1].copy()
    row = out.iloc[0].copy()
    row["공개번호"] = "KR10-2099-0000001A"
    row["출원일"] = "%d-01-15" % (y_max + 1)
    row["우선일"] = "%d-01-01" % (y_max + 1)
    return pd.concat([out, pd.DataFrame([row])], ignore_index=True)


def with_duplicate_families(df):
    """⑥ 중복 패밀리: 첫 20건을 같은 패밀리로 복제."""
    dup = df.head(20).copy()
    dup["공개번호"] = dup["공개번호"].str.replace("A", "B", regex=False)
    dup["국가"] = "US"
    return pd.concat([df, dup], ignore_index=True)


def with_applicant_variants(df):
    """⑦ 출원인명 다형: 동일 기업의 표기 변형."""
    out = df.copy()
    variants = {"삼성전자": ["삼성전자 주식회사", "(주)삼성전자", "SAMSUNG ELECTRONICS CO., LTD.",
                          "Samsung Electronics Co Ltd"],
                "SK하이닉스": ["에스케이하이닉스 주식회사", "SK HYNIX INC.", "SK hynix Inc"]}
    rng = np.random.default_rng(1)
    def _variant(name):
        base = name.split(";")[0].strip()
        if base in variants and rng.random() < 0.7:
            return variants[base][int(rng.integers(0, len(variants[base])))]
        return name
    out["출원인"] = out["출원인"].map(_variant)
    return out


def with_missing_legal_status(df):
    """⑧ 법적상태 누락 (30% 결측)."""
    out = df.copy()
    rng = np.random.default_rng(2)
    mask = rng.random(len(out)) < 0.3
    out.loc[mask, "법적상태"] = None
    return out


def without_citations(df):
    """⑨ 인용 데이터 없음."""
    return df.drop(columns=[c for c in ("인용 수", "피인용 수") if c in df.columns])


def without_embeddings(df):
    """⑩ 임베딩 없음."""
    return df.drop(columns=[c for c in ("임베딩 벡터",) if c in df.columns])


def main(argv):
    out_path = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else "sample_patents.csv"
    n = 600
    if "--rows" in argv:
        n = int(argv[argv.index("--rows") + 1])
    df = generate_sample(n=n)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print("생성 완료: %s (%d행 × %d컬럼)" % (out_path, len(df), len(df.columns)))


if __name__ == "__main__":
    main(sys.argv)
