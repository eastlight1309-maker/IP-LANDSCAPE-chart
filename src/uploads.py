# -*- coding: utf-8 -*-
"""
uploads.py — 웹앱 내 엑셀 업로드 작업 저장소 (방법 B).

설계:
- 업로드 시 작업자 이름·작업명은 필수다 (누가 어떤 목적으로 올렸는지 추적).
- 파일(xlsx/xls/csv)은 서버 저장 디렉터리(storage.upload_dir)에 보관하고,
  메타데이터(작업자·작업명·시각·행수·파일 경로)는 storage("uploads")에 영속화
  한다 — Dataiku 에서는 프로젝트 변수, 로컬에서는 JSON 파일.
- 업로드 즉시 DataFrame 으로 파싱해 in-memory dataset 으로 등록(inject)하므로
  바로 분석 대상(Settings → Dataset)으로 선택할 수 있다.
- Backend 재시작으로 in-memory 등록이 사라져도, 저장된 목록에서 "불러오기"
  하거나 해당 dataset 명을 참조하는 순간 파일에서 자동 재적재된다
  (ensure_loaded).

보안·안전:
- 확장자 화이트리스트(xlsx/xls/csv), 파일 60MB·60,000행 상한.
- 저장 파일명은 서버가 생성한 id 기반 (업로드 파일명은 메타데이터로만 보관).
- 작업자·작업명 길이 제한 및 HTML 이스케이프는 프론트에서 처리.
"""
import io
import logging
import os
import re
import time
import uuid

import pandas as pd

from src import storage
from src.data_access import inject_dataset, list_datasets

logger = logging.getLogger("ip_landscape")

ALLOWED_EXTENSIONS = (".xlsx", ".xls", ".csv")
MAX_FILE_MB = 60
MAX_ROWS = 60000
DATASET_PREFIX = "upload__"

_SLUG_RE = re.compile(r"[^0-9A-Za-z가-힣_-]+")


def _slug(text, limit=24):
    s = _SLUG_RE.sub("_", str(text or "").strip()).strip("_")
    return (s or "job")[:limit]


def _parse_table(raw_bytes, ext):
    """업로드 바이트 → DataFrame (첫 시트, 행 상한)."""
    buf = io.BytesIO(raw_bytes)
    if ext == ".csv":
        try:
            df = pd.read_csv(buf, nrows=MAX_ROWS)
        except UnicodeDecodeError:
            buf.seek(0)
            df = pd.read_csv(buf, nrows=MAX_ROWS, encoding="cp949")
    else:
        df = pd.read_excel(buf, sheet_name=0, nrows=MAX_ROWS,
                           engine="openpyxl" if ext == ".xlsx" else None)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")
    return df


def save_upload(raw_bytes, orig_filename, worker, job):
    """엑셀 업로드 저장 + 즉시 분석 가능 등록. 반환: 메타데이터 entry.

    실패 시 ValueError(사용자 안내 메시지).
    """
    worker = str(worker or "").strip()[:60]
    job = str(job or "").strip()[:120]
    if not worker or not job:
        raise ValueError("작업자 이름과 작업명은 반드시 입력해야 합니다.")
    orig = os.path.basename(str(orig_filename or ""))
    ext = os.path.splitext(orig)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("허용되지 않는 파일 형식입니다 (%s만 가능)."
                         % "/".join(ALLOWED_EXTENSIONS))
    if not raw_bytes:
        raise ValueError("빈 파일입니다.")
    if len(raw_bytes) > MAX_FILE_MB * 1024 * 1024:
        raise ValueError("파일이 %dMB 를 초과합니다." % MAX_FILE_MB)
    try:
        df = _parse_table(raw_bytes, ext)
    except Exception as e:
        raise ValueError("파일을 표로 해석할 수 없습니다: %s" % e)
    if not len(df) or not len(df.columns):
        raise ValueError("표 데이터가 비어 있습니다 (첫 시트를 확인하세요).")

    uid = uuid.uuid4().hex[:10]
    dataset_name = "%s%s_%s" % (DATASET_PREFIX, _slug(job), uid[:6])
    stored_name = "%s%s" % (uid, ext)
    stored_path = os.path.join(storage.upload_dir(), stored_name)
    with open(stored_path, "wb") as fh:
        fh.write(raw_bytes)

    entry = {
        "id": uid, "worker": worker, "job": job,
        "orig_filename": orig[:120], "stored_name": stored_name,
        "dataset": dataset_name,
        "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_rows": int(len(df)), "n_cols": int(len(df.columns)),
    }
    data = storage.load_uploads()
    items = list(data.get("items") or [])
    items.insert(0, entry)
    storage.save_uploads({"items": items[:200]})
    inject_dataset(dataset_name, df)
    logger.info("엑셀 업로드 저장: %s (%s / %s, %d행)", dataset_name, worker, job,
                len(df))
    return entry


def list_uploads():
    """저장된 업로드 작업 목록 (최신순). 로드 가능 여부 포함."""
    items = list(storage.load_uploads().get("items") or [])
    loaded = set(list_datasets())
    base = storage.upload_dir()
    for it in items:
        it["loaded"] = it.get("dataset") in loaded
        it["file_exists"] = os.path.exists(os.path.join(base,
                                                        str(it.get("stored_name"))))
    return items


def _find(upload_id):
    for it in storage.load_uploads().get("items") or []:
        if str(it.get("id")) == str(upload_id):
            return it
    return None


def load_upload(upload_id):
    """저장된 작업을 파일에서 읽어 분석 dataset 으로 (재)등록."""
    entry = _find(upload_id)
    if entry is None:
        raise LookupError("저장된 작업을 찾을 수 없습니다: %s" % upload_id)
    path = os.path.join(storage.upload_dir(), str(entry.get("stored_name")))
    if not os.path.exists(path):
        raise LookupError("저장 파일이 서버에 없습니다 (%s) — 다시 업로드하세요."
                          % entry.get("orig_filename"))
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as fh:
        df = _parse_table(fh.read(), ext)
    inject_dataset(str(entry["dataset"]), df)
    entry = dict(entry, n_rows=int(len(df)))
    return entry


def ensure_loaded(dataset_name):
    """upload__ dataset 이 재시작으로 내려갔으면 파일에서 자동 재적재. 성공 여부."""
    name = str(dataset_name or "")
    if not name.startswith(DATASET_PREFIX) or name in set(list_datasets()):
        return name in set(list_datasets())
    for it in storage.load_uploads().get("items") or []:
        if str(it.get("dataset")) == name:
            try:
                load_upload(it["id"])
                return True
            except Exception as e:
                logger.warning("업로드 dataset 자동 재적재 실패 (%s): %s", name, e)
                return False
    return False


def delete_upload(upload_id):
    """저장 작업 삭제 (메타데이터 + 파일)."""
    data = storage.load_uploads()
    items = list(data.get("items") or [])
    entry = next((it for it in items if str(it.get("id")) == str(upload_id)), None)
    if entry is None:
        raise LookupError("저장된 작업을 찾을 수 없습니다: %s" % upload_id)
    items = [it for it in items if str(it.get("id")) != str(upload_id)]
    storage.save_uploads({"items": items})
    try:
        path = os.path.join(storage.upload_dir(), str(entry.get("stored_name")))
        if os.path.exists(path):
            os.remove(path)
    except OSError as e:
        logger.warning("업로드 파일 삭제 실패: %s", e)
    return entry
