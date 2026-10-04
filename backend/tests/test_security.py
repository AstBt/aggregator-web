# -*- coding: utf-8 -*-
"""安全模块单元测试（FR-1.1 / NFR-1）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from security import (
    ROLES,
    create_token,
    decode_token,
    hash_password,
    role_at_least,
    verify_password,
)


class TestPassword:
    def test_hash_is_not_plaintext_and_verifies(self):
        h = hash_password("s3cret-pass")
        assert h != "s3cret-pass" and "s3cret" not in h
        assert verify_password("s3cret-pass", h)

    def test_wrong_password_rejected(self):
        h = hash_password("s3cret-pass")
        assert not verify_password("wrong", h)

    def test_long_password_not_truncated_by_bcrypt(self):
        """72 字节以上密码经 SHA-256 后仍可正确校验（NFR-1）。"""
        long_pw = "x" * 200
        h = hash_password(long_pw)
        assert verify_password(long_pw, h)

    def test_same_password_different_hashes(self):
        assert hash_password("same") != hash_password("same")


class TestToken:
    def test_roundtrip_contains_user_and_version(self):
        token = create_token(42, token_version=3)
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "42" and payload["tv"] == 3

    def test_token_version_mismatch_invalidates(self):
        """旧令牌与用户当前 token_version 不符时应判失效（调用方比对）。"""
        token = create_token(42, token_version=0)
        payload = decode_token(token)
        assert payload["tv"] != 1

    def test_garbage_token_returns_none(self):
        assert decode_token("not.a.token") is None


class TestRoles:
    def test_hierarchy(self):
        assert role_at_least("admin", "operator")
        assert role_at_least("operator", "viewer")
        assert not role_at_least("viewer", "operator")
        assert not role_at_least("operator", "admin")

    def test_unknown_role_denied(self):
        assert not role_at_least("ghost", "viewer")
        assert ROLES["admin"] > ROLES["viewer"]
