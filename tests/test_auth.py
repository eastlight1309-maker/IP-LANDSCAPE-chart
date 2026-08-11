# -*- coding: utf-8 -*-
"""접속자 관리 (앱 수준 접근 제어) 테스트."""
import pytest

from src import storage
from src.auth import login, verify_token, is_admin, set_admin, delete_user, \
    can_see, can_delete


@pytest.fixture(autouse=True)
def clean_users():
    storage.save_store("users", {"items": []})
    yield
    storage.save_store("users", {"items": []})


def test_register_login_and_token():
    user, token = login("IP팀/홍길동", "202401234")
    assert user["is_admin"] is True          # 첫 사용자 = 관리자
    assert user["pw_hash"] != "202401234"    # 원문 미저장
    assert verify_token(token) == "IP팀/홍길동"
    # 재로그인: 올바른 사원번호 → 성공, 틀리면 실패
    u2, t2 = login("IP팀/홍길동", "202401234")
    assert verify_token(t2) == "IP팀/홍길동"
    with pytest.raises(ValueError):
        login("IP팀/홍길동", "999999")
    # 두 번째 사용자는 일반
    u3, _t3 = login("특허팀/김철수", "202405678")
    assert u3["is_admin"] is False
    # 토큰 위조 방지
    assert verify_token(t2[:-4] + "0000") is None
    assert verify_token("garbage") is None


def test_admin_management():
    login("관리자", "10000000")
    login("일반유저", "20000000")
    assert is_admin("관리자") and not is_admin("일반유저")
    set_admin("일반유저", True)
    assert is_admin("일반유저")
    set_admin("일반유저", False)
    with pytest.raises(ValueError):      # 마지막 관리자 해제 불가
        set_admin("관리자", False)
    with pytest.raises(ValueError):      # 마지막 관리자 삭제 불가
        delete_user("관리자")
    delete_user("일반유저")
    assert not is_admin("일반유저")


def test_visibility_rules():
    login("admin", "11112222")           # 관리자
    login("userA", "33334444")
    login("userB", "55556666")
    assert can_see(None, None)           # 소유자 없는 항목은 모두
    assert can_see("userA", "userA")
    assert not can_see("userA", "userB")
    assert can_see("userA", "admin")
    assert not can_see("userA", None)    # 비로그인은 소유 항목 불가
    assert can_delete("userA", "admin") and can_delete("userA", "userA")
    assert not can_delete("userA", "userB")
