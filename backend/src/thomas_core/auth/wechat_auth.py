"""
WeChat MiniApp authentication.
Handles wx.login code -> openid -> looma JWT flow.
"""
import requests
from flask import current_app


def code2session(code: str) -> dict:
    """
    Exchange wx.login code for openid + session_key.
    Calls WeChat API: https://api.weixin.qq.com/sns/jscode2session

    Returns:
        {"openid": "...", "session_key": "...", "unionid": "..." (optional)}

    Raises:
        ValueError if the code is invalid or WeChat API returns an error.
    """
    config = current_app.config
    url = "https://api.weixin.qq.com/sns/jscode2session"
    params = {
        "appid": config["WECHAT_APPID"],
        "secret": config["WECHAT_APP_SECRET"],
        "js_code": code,
        "grant_type": "authorization_code",
    }
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()

    if "errcode" in data and data["errcode"] != 0:
        raise ValueError(f"WeChat code2session error: {data.get('errmsg', 'unknown')}")

    if "openid" not in data:
        raise ValueError("WeChat code2session: no openid in response")

    return data
