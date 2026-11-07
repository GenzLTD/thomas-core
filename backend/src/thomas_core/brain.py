"""核的意图大脑桥（刀 5f，RFC 裁决 1）：`parse_intent` / `dispatch` 由宿主注入。

为什么不在核里实现：`src/agents/central_brain.py`（753 行）+ `agents/` 其余 14 件（合计
≈4,369 行）是产品面（诗歌 / 叙事 / MBTI / 岗位匹配 / 导航）。核只负责「收到问题 →
按意图把活派出去」，具体派给谁属于产品实现。

缺省行为（**与改造前逐字等价**）：惰性 import `src.agents.central_brain`；宿主不在
（独立核仓）则抛 `BrainNotConfigured`，`ask_routes` 原有的 try/except 会走「退配额 + 500」，
不会静默返回空答案。
"""
from __future__ import annotations

_impl = None


class BrainNotConfigured(RuntimeError):
    """宿主未注入大脑实现，且找不到缺省实现。"""


def register_brain(parse_intent, dispatch) -> None:
    """注入实现（宿主在 create_app() 里注册一次即可）。"""
    global _impl
    _impl = (parse_intent, dispatch)


def reset_brain() -> None:
    """清空注入（测试用；不影响缺省惰性实现）。"""
    global _impl
    _impl = None


def _default_brain():
    try:
        from src.agents.central_brain import dispatch, parse_intent

        return parse_intent, dispatch
    except Exception as exc:  # ImportError / 宿主缺失
        raise BrainNotConfigured(
            "brain not configured: 宿主未调用 register_brain()，且缺省 src.agents.central_brain 不可用"
        ) from exc


def get_brain():
    """返回 `(parse_intent, dispatch)`。"""
    if _impl is not None:
        return _impl
    return _default_brain()
