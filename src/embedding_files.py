# -*- coding: utf-8 -*-
"""
embedding_files.py — 업로드된 임베딩 벡터 파일(.npy/.npz) 관리 + 문헌 매칭.

배경:
  임베딩 벡터를 raw Excel 의 텍스트 컬럼으로 넣는 대신, 별도의 .npy/.npz
  파일로 업로드해 분석 데이터와 출원번호(또는 공개번호)로 매칭한다.

지원 형식:
  ① .npz (권장) — 두 배열을 담은 압축 파일:
       벡터:  'embeddings' | 'vectors' | 'emb' | 'X'  (N×D float)
       키:    'app_number' | '출원번호' | 'ids' | 'keys' | 'id' |
              'pub_number' | '공개번호'                (N, 문자열/숫자)
       키 배열이 없으면 ②와 같은 순서 기반으로 처리.
  ② .npy — N×D float 배열 하나. 문헌 키가 없으므로 '현재 dataset 의 행 순서'
       기반 매칭만 가능하며, 행 수가 정확히 일치할 때만 적용한다 (불일치 시
       적용 거부 — 임의 정렬·추측 매칭 금지).

매칭 규칙 (값을 지어내지 않음):
  - 키 정규화: 문자열화 → 공백 제거 → 하이픈/점 등 비영숫자 제거 → 대문자.
  - df 의 app_number 우선, 없으면 pub_number 로 매칭.
  - 매칭 안 된 문헌의 _embedding 은 None (임베딩 분석에서 자동 제외).
"""
import io
import logging
import os
import re
import time
import uuid

import numpy as np

from src import storage

logger = logging.getLogger("ip_landscape")

_VEC_KEYS = ("embeddings", "vectors", "emb", "X", "x")
_ID_KEYS = ("app_number", "출원번호", "ids", "keys", "id",
            "pub_number", "공개번호")
_EMB_MAX_FILE_MB = 300
_EMB_MAX_ITEMS = 20
_EMB_NORM_RE = re.compile(r"[^0-9A-Za-z가-힣]")


def _norm_key(value):
    """출원번호/공개번호 정규화 — 형식 차이(하이픈·공백·점)를 흡수한다.

    엑셀 숫자 컬럼이 float 로 읽히면 str() 가 '1020190123456.0' 을 만들고,
    점만 제거하면 뒤에 가짜 0 이 붙어 영원히 매칭 실패한다 → '.0' 꼬리를
    먼저 잘라낸다 (실제 소수점 번호는 특허 번호 체계에 존재하지 않음).
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    if isinstance(value, float) and float(value).is_integer():
        s = str(int(value))
    else:
        s = str(value).strip()
    if not s or s.lower() in ("nan", "none"):
        return ""
    s = re.sub(r"\.0+$", "", s)
    return _EMB_NORM_RE.sub("", s).upper()


def _load_entries():
    return list(storage.load_store("embedding_files").get("items") or [])


def _save_entries(items):
    storage.save_store("embedding_files", {"items": items[:_EMB_MAX_ITEMS]})


def list_embedding_files():
    return _load_entries()


def find_entry(file_id):
    for it in _load_entries():
        if it.get("id") == file_id:
            return it
    return None


def _emb_dir():
    base = os.path.join(storage.upload_dir(), "embeddings")
    os.makedirs(base, exist_ok=True)
    return base


def _extract_arrays(raw_bytes, filename):
    """파일 → (ids 리스트 또는 None, N×D float 행렬). 실패 시 ValueError."""
    buf = io.BytesIO(raw_bytes)
    name = str(filename).lower()
    if not (name.endswith(".npz") or name.endswith(".npy")):
        raise ValueError("지원하지 않는 확장자입니다 — .npy 또는 .npz 만 가능합니다.")
    try:
        loaded = np.load(buf, allow_pickle=True)
    except Exception:
        raise ValueError("numpy 파일로 해석할 수 없습니다 — np.save/np.savez 로 "
                         "저장한 .npy/.npz 파일인지 확인하세요.")
    if name.endswith(".npz"):
        with loaded as z:
            keys = list(z.keys())
            vec_key = next((k for k in _VEC_KEYS if k in keys), None)
            if vec_key is None:  # 이름이 달라도 2차원 수치 배열이면 벡터로 인정
                vec_key = next((k for k in keys
                                if getattr(z[k], "ndim", 0) == 2
                                and np.issubdtype(z[k].dtype, np.number)), None)
            if vec_key is None:
                raise ValueError("npz 안에 N×D 숫자 벡터 배열이 없습니다 — "
                                 "'embeddings' 키로 저장하세요. (발견된 키: %s)"
                                 % ", ".join(keys))
            vectors = np.asarray(z[vec_key], dtype=np.float64)
            id_key = next((k for k in _ID_KEYS if k in keys and k != vec_key), None)
            if id_key is None:
                id_key = next((k for k in keys
                               if k != vec_key and getattr(z[k], "ndim", 0) == 1
                               and len(z[k]) == len(vectors)), None)
            ids = None
            if id_key is not None:
                ids = [str(v) for v in np.asarray(z[id_key]).tolist()]
    else:
        arr = loaded
        if getattr(arr, "dtype", None) is not None and arr.dtype.names:
            # 구조화 배열: 키 필드 + 벡터 필드 탐색
            fields = list(arr.dtype.names)
            id_f = next((f for f in fields if f.lower() in
                         [k.lower() for k in _ID_KEYS]), None)
            vec_f = next((f for f in fields if f != id_f), None)
            if id_f is None or vec_f is None:
                raise ValueError("구조화 npy 에서 키/벡터 필드를 찾지 못했습니다 "
                                 "(필드: %s)" % ", ".join(fields))
            ids = [str(v) for v in arr[id_f].tolist()]
            vectors = np.asarray([np.asarray(v, dtype=np.float64)
                                  for v in arr[vec_f]], dtype=np.float64)
        else:
            vectors = np.asarray(arr, dtype=np.float64)
            ids = None
    if vectors.ndim != 2 or vectors.shape[0] < 1 or vectors.shape[1] < 2:
        raise ValueError("벡터 배열은 N×D 2차원이어야 합니다 (현재 shape=%s)."
                         % (vectors.shape,))
    if not np.isfinite(vectors).all():
        raise ValueError("벡터에 NaN/Inf 값이 있습니다 — 파일을 확인하세요.")
    if ids is not None and len(ids) != len(vectors):
        raise ValueError("키 배열 길이(%d)와 벡터 수(%d)가 다릅니다."
                         % (len(ids), len(vectors)))
    return ids, vectors


def save_embedding_file(raw_bytes, filename, owner=None):
    """업로드 파일 검증·저장 → 목록 entry. 실패 시 ValueError."""
    if len(raw_bytes) > _EMB_MAX_FILE_MB * 1024 * 1024:
        raise ValueError("파일이 %dMB 를 초과합니다." % _EMB_MAX_FILE_MB)
    ids, vectors = _extract_arrays(raw_bytes, filename)
    eid = uuid.uuid4().hex[:12]
    stored = "emb_%s.npz" % eid
    path = os.path.join(_emb_dir(), stored)
    # 항상 정규화된 npz 로 저장 → 로딩 경로 단일화
    if ids is not None:
        np.savez_compressed(path, embeddings=vectors,
                            ids=np.asarray(ids, dtype=object))
    else:
        np.savez_compressed(path, embeddings=vectors)
    entry = {"id": eid, "filename": str(filename)[:120], "stored_name": stored,
             "n": int(vectors.shape[0]), "dim": int(vectors.shape[1]),
             "has_ids": ids is not None, "owner": owner,
             "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    items = _load_entries()
    items.insert(0, entry)
    _save_entries(items)
    return entry


def delete_embedding_file(file_id):
    items = _load_entries()
    entry = next((it for it in items if it.get("id") == file_id), None)
    if entry is None:
        return False
    try:
        os.remove(os.path.join(_emb_dir(), str(entry.get("stored_name"))))
    except OSError:
        pass
    _save_entries([it for it in items if it.get("id") != file_id])
    return True


def load_embedding_arrays(file_id):
    """entry id → (ids 또는 None, 행렬). 파일이 없으면 (None, None)."""
    entry = find_entry(file_id)
    if entry is None:
        return None, None
    path = os.path.join(_emb_dir(), str(entry.get("stored_name")))
    try:
        with np.load(path, allow_pickle=True) as z:
            vectors = np.asarray(z["embeddings"], dtype=np.float64)
            ids = [str(v) for v in z["ids"].tolist()] if "ids" in z else None
        return ids, vectors
    except Exception as e:
        logger.warning("embedding file load failed (%s): %s", file_id, e)
        return None, None


def match_stats(df, file_id):
    """현재 표준 프레임과의 매칭 통계 (적용 없이 진단만)."""
    ids, vectors = load_embedding_arrays(file_id)
    if vectors is None:
        return {"error": "파일을 읽을 수 없습니다."}
    if ids is None:
        ok = len(df) == len(vectors)
        return {"mode": "order", "n_file": int(len(vectors)),
                "n_data": int(len(df)), "matched": int(len(df)) if ok else 0,
                "match_field": "행 순서",
                "note": None if ok else ("행 수 불일치(파일 %d vs 데이터 %d) — "
                                         "키 배열이 없는 .npy 는 행 수가 정확히 "
                                         "일치해야 적용됩니다."
                                         % (len(vectors), len(df)))}
    table = {_norm_key(k) for k in ids if _norm_key(k)}
    best_field, best_n = None, -1
    for field in ("app_number", "pub_number"):
        if field not in df.columns:
            continue
        n = int(df[field].map(_norm_key).isin(table).sum())
        if n > best_n:
            best_field, best_n = field, n
    return {"mode": "ids", "n_file": int(len(vectors)), "n_data": int(len(df)),
            "matched": max(best_n, 0),
            "match_field": {"app_number": "출원번호", "pub_number": "공개번호",
                            None: "없음"}[best_field],
            "note": None if best_n > 0 else
            "출원번호/공개번호가 파일 키와 하나도 일치하지 않습니다 — 키 형식을 "
            "확인하세요 (하이픈·공백 차이는 자동 흡수됩니다)."}


def apply_to_frame(df, file_id):
    """표준 프레임의 _embedding 을 업로드 파일 벡터로 채운다 (제자리 수정).

    반환: {"applied": bool, "matched": n, "match_field": ..., "reason": ...}
    매칭 실패 문헌은 None — 임의 벡터를 만들지 않는다.
    """
    ids, vectors = load_embedding_arrays(file_id)
    if vectors is None:
        return {"applied": False, "reason": "임베딩 파일을 읽을 수 없습니다."}
    if ids is None:
        if len(df) != len(vectors):
            return {"applied": False,
                    "reason": "키 없는 .npy 는 행 수가 데이터와 정확히 일치해야 "
                              "합니다 (파일 %d vs 데이터 %d)."
                              % (len(vectors), len(df))}
        df["_embedding"] = [vectors[i] for i in range(len(df))]
        return {"applied": True, "matched": int(len(df)), "match_field": "행 순서"}
    table = {}
    for k, i in zip(ids, range(len(ids))):
        nk = _norm_key(k)
        if nk and nk not in table:  # 중복 키는 첫 벡터 사용
            table[nk] = i
    best_field, best_idx = None, None
    for field in ("app_number", "pub_number"):
        if field not in df.columns:
            continue
        idx = df[field].map(lambda v: table.get(_norm_key(v)))
        if best_idx is None or idx.notna().sum() > best_idx.notna().sum():
            best_field, best_idx = field, idx
    if best_idx is None or not best_idx.notna().any():
        return {"applied": False,
                "reason": "출원번호/공개번호가 파일 키와 일치하지 않습니다."}
    df["_embedding"] = [vectors[int(i)] if i is not None and not
                        (isinstance(i, float) and np.isnan(i)) else None
                        for i in best_idx]
    return {"applied": True, "matched": int(best_idx.notna().sum()),
            "match_field": {"app_number": "출원번호",
                            "pub_number": "공개번호"}[best_field]}
