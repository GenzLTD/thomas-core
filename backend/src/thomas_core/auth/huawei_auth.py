"""
华为帐号 OAuth 2.0 登录辅助模块

流程: 元服务端获取 authorizationCode → 后端换取 access_token →
     获取 openID/unionID → 签发 looma JWT

参考文档: https://developer.huawei.com/consumer/cn/doc/HMSCore-References/account-auth-openplatform-0000001050150169

Usage (shared by auth_routes.py):
    from src.thomas_core.auth.huawei_auth import exchange_authorization_code, HuaweiUserInfo
"""

import time
import json
import requests
from dataclasses import dataclass, field
from flask import current_app


# ============ Data Class ============

@dataclass
class HuaweiUserInfo:
    open_id: str
    union_id: str = ""
    display_name: str = ""
    avatar_url: str = ""
    raw: dict = field(default_factory=dict)

    def to_metadata(self) -> str:
        return json.dumps(self.raw, ensure_ascii=False)


# ============ Config Helpers ============

# 华为 OAuth 区域端点映射
_OAUTH_DOMAINS = {
    "cn": "oauth-login.cloud.huawei.com",
    "ru": "oauth-login-ru.cloud.huawei.com",
    "de": "oauth-login-de.cloud.huawei.com",  # 欧洲
    "sg": "oauth-login-sg.cloud.huawei.com",   # 亚太
}

# 华为 account 区域端点映射（userinfo / rest.php）
_ACCOUNT_DOMAINS = {
    "cn": "account.cloud.huawei.com",
    "ru": "account-ru.cloud.huawei.com",
    "de": "account-de.cloud.huawei.com",
    "sg": "account-sg.cloud.huawei.com",
}


def _oauth_region() -> str:
    return current_app.config.get("HUAWEI_OAUTH_REGION", "cn").strip().lower()


def _token_url() -> str:
    region = _oauth_region()
    domain = _OAUTH_DOMAINS.get(region, _OAUTH_DOMAINS["cn"])
    return f"https://{domain}/oauth2/v3/token"


def _userinfo_url() -> str:
    region = _oauth_region()
    domain = _ACCOUNT_DOMAINS.get(region, _ACCOUNT_DOMAINS["cn"])
    return f"https://{domain}/rest.php"


def _client_id() -> str:
    return current_app.config.get("HUAWEI_CLIENT_ID", "")


def _client_secret() -> str:
    return current_app.config.get("HUAWEI_CLIENT_SECRET", "")


# ============ Public API ============

def exchange_authorization_code(authorization_code: str) -> dict:
    """用 authorization_code 换取 access_token。

    Raises ValueError on failure.
    """
    payload = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "client_id": _client_id(),
        "client_secret": _client_secret(),
    }

    resp = requests.post(
        _token_url(),
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )

    if resp.status_code != 200:
        raise ValueError(
            f"Huawei token exchange failed: HTTP {resp.status_code} — {resp.text[:300]}"
        )

    data = resp.json()
    if "access_token" not in data:
        raise ValueError(f"access_token missing in Huawei response: {data}")

    return data


def fetch_user_info(access_token: str) -> HuaweiUserInfo:
    """使用 access_token 获取华为帐号用户信息（openID / unionID）。

    Raises ValueError on failure.
    """
    params = {
        "nsp_ts": str(int(time.time() * 1000)),
        "access_token": access_token,
        "nsp_fmt": "JSON",
        "nsp_svc": "openplatform.account.getOpenPlatformUserInfo",
    }

    resp = requests.get(
        _userinfo_url(),
        params=params,
        timeout=10,
    )

    if resp.status_code != 200:
        raise ValueError(
            f"Huawei userinfo request failed: HTTP {resp.status_code} — {resp.text[:300]}"
        )

    data = resp.json()

    # 华为返回结构中，用户信息可能在 userInfo 或 response 字段
    user_info = data.get("userInfo") or data.get("response") or data

    open_id = user_info.get("openID", "")
    if not open_id:
        raise ValueError(f"No openID in Huawei userinfo response: {data}")

    return HuaweiUserInfo(
        open_id=open_id,
        union_id=user_info.get("unionID", ""),
        display_name=user_info.get("displayName", ""),
        avatar_url=user_info.get("headPictureURL", ""),
        raw=data,
    )
