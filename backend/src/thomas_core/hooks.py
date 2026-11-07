"""核的宿主钩子（刀 5e，RFC 裁决 5）：ask 热路径上仅有的两处产品侧硬依赖。

为什么做成钩子而不是搬进核：
- `src/timeline/events.py`（716 行）是产品侧时间线（含成长/任务/扫描等领域事件），
  核只需要其中「AI 交互埋点」这一条；
- `src/reports/match_report_manager.py`（399 行）是简历-岗位匹配报告，属途/聘产品面。

没注册时的缺省行为（**与改造前逐字等价**）：惰性 import 宿主的实现；宿主不在（独立核仓）
则 timeline 埋点按 no-op 处理、报告上下文返回 None —— 两条路径本来就都是 best-effort
（`ask_routes` 外面包着 try/except），所以失败不可见、不影响应答。
"""
from __future__ import annotations

import logging

logger = logging.getLogger("looma.core.hooks")

# 注册位（进程级；宿主在 create_app() 里注册一次即可）
_timeline_logger = None
_report_manager_factory = None


def register_timeline_logger(fn) -> None:
    """注册 `fn(db, user_id, **kwargs) -> None`（时间线 AI 交互埋点）。"""
    global _timeline_logger
    _timeline_logger = fn


def register_report_manager_factory(fn) -> None:
    """注册 `fn(db) -> manager`（匹配报告读取器，需有 get_report/list_user_reports）。"""
    global _report_manager_factory
    _report_manager_factory = fn


def reset_hooks() -> None:
    """清空注册位（测试用；不影响缺省惰性实现）。"""
    global _timeline_logger, _report_manager_factory
    _timeline_logger = None
    _report_manager_factory = None


def _default_timeline_logger():
    try:
        from src.timeline.events import record_interaction_log

        return record_interaction_log
    except Exception:  # ImportError / 宿主缺失
        logger.debug("timeline hook 未注册且宿主实现不可用 → no-op")
        return None


def _default_report_manager_factory():
    try:
        from src.reports.match_report_manager import MatchReportManager

        return MatchReportManager
    except Exception:
        logger.debug("report hook 未注册且宿主实现不可用 → None")
        return None


def record_interaction_log(db, user_id, **kwargs) -> None:
    """骨架调用点：时间线 AI 交互埋点（best-effort，异常不抛出）。"""
    fn = _timeline_logger or _default_timeline_logger()
    if fn is None:
        return
    try:
        fn(db, user_id, **kwargs)
    except Exception:
        logger.debug("timeline hook 执行失败（已忽略）", exc_info=True)


def report_manager(db):
    """返回匹配报告读取器实例；拿不到就返回 None（调用方保持原兜底语义）。"""
    factory = _report_manager_factory or _default_report_manager_factory()
    if factory is None:
        return None
    return factory(db)
