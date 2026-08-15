# -*- coding: utf-8 -*-
"""
auth.py — 앱 수준 접속자 관리 (편의성 접근 제어 계층).

설계:
- ID = 팀명/이름 (자유 문자열), PW = 사원번호.
- 사원번호는 사용자별 salt 를 붙여 SHA-256 해시로만 저장 (원문 미저장).
- 최초 로그인 시 자동 등록. 첫 번째 등록 사용자는 자동으로 관리자.
- 토큰: "name_b64.expiry.HMAC" 서명 토큰 (비밀키는 storage 에 1회 생성 보관)
  → Backend 재시작 후에도 유효, 서버 세션 저장 불필요. 기본 유효기간 30일.
- 권한 규칙: 관리자=전체 조회/삭제/사용자 관리. 일반 사용자=자기 소유(owner)
  항목 + 소유자 미지정(legacy) 항목만 조회. 삭제는 자기 것만.

⚠ 보안 성격 (화면·매뉴얼에 명시):
  이 계층은 '실수로 남의 작업을 보거나 지우는 것'을 막는 편의성 접근 관리다.
  사원번호는 추측 가능성이 있는 약한 비밀번호이며, Dataiku Webapp 구조상
  완전한 보안 경계가 아니다 — 강한 접근 통제는 Dataiku 프로젝트 권한으로.
"""
import base64
import hashlib
import hmac
import logging
import os
import time

from src import storage

logger = logging.getLogger("ip_landscape")

_TOKEN_TTL_SECONDS = 30 * 24 * 3600   # 30일
_MAX_USERS = 500


def _users_store():
    return storage.load_store("users")


def _save_users(data):
    storage.save_store("users", data)


def _secret():
    """토큰 서명 비밀키 (최초 1회 생성 후 storage 보관)."""
    data = storage.load_store("auth")
    if not data.get("secret"):
        data["secret"] = base64.b64encode(os.urandom(32)).decode("ascii")
        storage.save_store("auth", data)
    return data["secret"].encode("ascii")


def _hash_pw(emp_no, salt):
    return hashlib.sha256((salt + str(emp_no)).encode("utf-8")).hexdigest()


def _b64(s):
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii").rstrip("=")


def _unb64(s):
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad).decode("utf-8")


def make_token(name):
    expiry = int(time.time()) + _TOKEN_TTL_SECONDS
    payload = "%s.%d" % (_b64(name), expiry)
    sig = hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return "%s.%s" % (payload, sig)


def verify_token(token):
    """토큰 → 사용자 이름 또는 None (만료/위조/삭제된 사용자)."""
    try:
        name_b64, expiry_s, sig = str(token or "").split(".")
        payload = "%s.%s" % (name_b64, expiry_s)
        want = hmac.new(_secret(), payload.encode("ascii"),
                        hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, want):
            return None
        if int(expiry_s) < time.time():
            return None
        name = _unb64(name_b64)
    except Exception:
        return None
    return name if find_user(name) else None


def find_user(name):
    name = str(name or "").strip()
    for u in _users_store().get("items") or []:
        if u.get("name") == name:
            return u
    return None


def login(name, emp_no):
    """로그인 (미등록 이름이면 자동 등록). 반환 (user, token) 또는 ValueError.

    첫 번째 등록 사용자는 자동 관리자.
    """
    name = str(name or "").strip()[:60]
    emp_no = str(emp_no or "").strip()
    if not name or not emp_no:
        raise ValueError("팀명/이름과 사원번호를 모두 입력하세요.")
    if len(emp_no) < 4:
        raise ValueError("사원번호는 4자 이상이어야 합니다.")
    data = _users_store()
    items = data.get("items") or []
    # 같은 로드본(items) 안에서 사용자를 찾아야 last_login 갱신이 저장됨 —
    # find_user() 는 별도 로드본을 반환해 갱신이 유실된다
    user = next((u for u in items if u.get("name") == name), None)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    if user is None:
        if len(items) >= _MAX_USERS:
            raise ValueError("등록 가능한 사용자 수를 초과했습니다.")
        salt = base64.b64encode(os.urandom(12)).decode("ascii")
        user = {"name": name, "salt": salt,
                "pw_hash": _hash_pw(emp_no, salt),
                "is_admin": len(items) == 0,   # 첫 사용자 = 관리자
                "created_at": now, "last_login": now}
        items.append(user)
        _save_users({"items": items})
        logger.info("신규 사용자 등록: %s%s", name,
                    " (관리자)" if user["is_admin"] else "")
    else:
        if not hmac.compare_digest(user.get("pw_hash", ""),
                                   _hash_pw(emp_no, user.get("salt", ""))):
            raise ValueError("사원번호가 일치하지 않습니다.")
        user["last_login"] = now
        _save_users({"items": items})
    return user, make_token(name)


def is_admin(name):
    u = find_user(name)
    return bool(u and u.get("is_admin"))


def public_user(u):
    """비밀 필드 제거한 사용자 정보."""
    return {"name": u.get("name"), "is_admin": bool(u.get("is_admin")),
            "created_at": u.get("created_at"), "last_login": u.get("last_login")}


def list_users():
    return [public_user(u) for u in _users_store().get("items") or []]


def set_admin(name, admin_flag):
    data = _users_store()
    items = data.get("items") or []
    target = None
    for u in items:
        if u.get("name") == str(name).strip():
            target = u
    if target is None:
        raise LookupError("사용자를 찾을 수 없습니다: %s" % name)
    if not admin_flag and sum(1 for u in items if u.get("is_admin")) <= 1 \
            and target.get("is_admin"):
        raise ValueError("마지막 관리자는 해제할 수 없습니다.")
    target["is_admin"] = bool(admin_flag)
    _save_users({"items": items})
    return public_user(target)


def delete_user(name):
    data = _users_store()
    items = data.get("items") or []
    target = find_user(name)
    if target is None:
        raise LookupError("사용자를 찾을 수 없습니다: %s" % name)
    if target.get("is_admin") and \
            sum(1 for u in items if u.get("is_admin")) <= 1:
        raise ValueError("마지막 관리자는 삭제할 수 없습니다.")
    _save_users({"items": [u for u in items
                           if u.get("name") != str(name).strip()]})
    return True


def can_see(owner, requester_name):
    """항목 조회 권한: 관리자=전부 / 사용자=자기 것 + 소유자 미지정(legacy) /
    비로그인=소유자 미지정 항목만."""
    if not owner:
        return True
    if not requester_name:
        return False
    if requester_name == owner:
        return True
    return is_admin(requester_name)


def can_delete(owner, requester_name):
    """삭제 권한: 자기 것 또는 관리자. 소유자 미지정 항목은 로그인 사용자 누구나."""
    if not requester_name:
        return not owner
    if not owner or requester_name == owner:
        return True
    return is_admin(requester_name)
