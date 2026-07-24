# -*- coding: utf-8 -*-
"""
cache.py — 결과 캐싱 (필터 조합 기준 캐시 키) + 분석 실행 로그.

계산 논리:
- 캐시 키 = SHA1( dataset명 | 분석명 | 정렬된 필터 JSON | 정렬된 설정 JSON ).
- in-memory LRU(OrderedDict) + TTL. 전처리 DataFrame 캐시와 분석 결과(JSON) 캐시를
  분리하여, 필터가 같으면 전처리를 재사용하고 집계 결과도 재사용한다.
- Webapp backend 프로세스는 단일 프로세스이므로 thread lock 으로 보호한다.
- run_log: 최근 분석 실행 기록(분석명, 캐시 hit 여부, 소요시간, 행 수)을 보관하여
  /api/config 의 "분석 실행 로그" 기능에 제공한다.
"""
import hashlib
import json
import threading
import time
from collections import OrderedDict


def make_cache_key(*parts):
    """임의 객체들을 안정적인 문자열 키(SHA1)로 변환. dict 는 key 정렬 후 직렬화."""
    ser = []
    for p in parts:
        try:
            ser.append(json.dumps(p, sort_keys=True, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            ser.append(repr(p))
    return hashlib.sha1("|".join(ser).encode("utf-8")).hexdigest()


class LRUCache(object):
    """TTL 지원 in-memory LRU 캐시."""

    def __init__(self, max_items=64, ttl_seconds=1800):
        self.max_items = int(max_items)
        self.ttl = float(ttl_seconds)
        self._data = OrderedDict()  # key -> (expire_ts, value)
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expire_ts, value = item
            if time.time() > expire_ts:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key, value):
        with self._lock:
            self._data[key] = (time.time() + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_items:
                self._data.popitem(last=False)

    def clear(self):
        with self._lock:
            self._data.clear()


# 전처리 DataFrame 캐시 (무겁고 수가 적음) / 분석 결과 캐시 (가볍고 수가 많음)
DF_CACHE = LRUCache(max_items=8, ttl_seconds=3600)
RESULT_CACHE = LRUCache(max_items=256, ttl_seconds=1800)

_RUN_LOG = []
_RUN_LOG_LOCK = threading.Lock()
_RUN_LOG_MAX = 200


def log_run(analysis, cache_hit, elapsed_ms, n_rows, status="ok"):
    """분석 실행 로그 기록 (최근 _RUN_LOG_MAX 건 유지)."""
    with _RUN_LOG_LOCK:
        _RUN_LOG.append({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "analysis": analysis, "cache_hit": bool(cache_hit),
            "elapsed_ms": round(float(elapsed_ms), 1),
            "n_rows": int(n_rows) if n_rows is not None else None,
            "status": status,
        })
        del _RUN_LOG[:-_RUN_LOG_MAX]


def get_run_log(limit=50):
    with _RUN_LOG_LOCK:
        return list(_RUN_LOG[-int(limit):])[::-1]


def clear_all_caches():
    DF_CACHE.clear()
    RESULT_CACHE.clear()


def cached_analysis(analysis_name, key_parts, compute_fn):
    """분석 결과 캐시 래퍼.

    key_parts: 캐시 키 구성 요소 리스트 (dataset, 필터, 설정 등).
    compute_fn: () -> (result_dict, n_rows). 캐시 미스 시 호출.
    반환: result_dict (meta.cache_hit / meta.generated_at 을 주입).
    """
    key = make_cache_key(analysis_name, *key_parts)
    t0 = time.time()
    cached = RESULT_CACHE.get(key)
    if cached is not None:
        log_run(analysis_name, True, (time.time() - t0) * 1000.0,
                cached.get("meta", {}).get("n_rows"))
        out = dict(cached)
        meta = dict(out.get("meta", {}))
        meta["cache_hit"] = True
        out["meta"] = meta
        return out
    result, n_rows = compute_fn()
    meta = dict(result.get("meta", {}))
    meta.setdefault("generated_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    meta["cache_hit"] = False
    meta["n_rows"] = int(n_rows) if n_rows is not None else None
    result["meta"] = meta
    if result.get("status") in ("ok", "empty", "disabled"):
        RESULT_CACHE.set(key, result)
    log_run(analysis_name, False, (time.time() - t0) * 1000.0, n_rows,
            status=result.get("status", "ok"))
    return result
