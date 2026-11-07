"""核运行时小工具（刀 5a：把宿主 `src/app.py` 的 health 辅助函数收进核）。

为什么在核里：`create_core_app()` 的 `/health` 要报 `git_commit`，而原实现住在
`src/app.py`（宿主应用工厂，549 行、注册 27 个蓝图）。核如果 import 它，等于
把整个产品面拖进核 —— 独立发版 split 后新仓将 import 失败。

规则：本模块只依赖标准库；宿主反向 import（产品→核，允许）。
"""
from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path


def _backend_dir() -> str:
    """定位 backend/ 根目录（`git_commit.txt` 与 `run.py` 所在层）。

    两种布局都要成立：
    - 仓内：`backend/src/thomas_core/runtime.py` → 上溯 3 层 = `backend/`
    - 独立核仓：`src/thomas_core/runtime.py` → 上溯 2 层 = 仓根

    以「含 `requirements.txt` 或 `run.py` 或 `git_commit.txt`」为判据向上找，
    找不到时退回仓内布局的 3 层，保证行为与改造前一致。
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "requirements.txt").is_file() or (parent / "run.py").is_file():
            return str(parent)
        if (parent / "git_commit.txt").is_file():
            return str(parent)
    if len(here.parents) >= 3:
        return str(here.parents[2])
    return str(here.parent)


@lru_cache(maxsize=1)
def git_commit() -> str:
    """Resolve the deployed commit hash for /health (三级回退).

    Priority: GIT_COMMIT env → backend/git_commit.txt → git rev-parse.
    Cloud deploys rsync with --exclude='.git' (no git history), so deploy
    scripts write backend/git_commit.txt at rsync time; local runs fall back
    to rev-parse. Cached for the process lifetime.
    """
    env = os.getenv("GIT_COMMIT", "").strip()
    if env:
        return env
    backend_dir = _backend_dir()
    marker = os.path.join(backend_dir, "git_commit.txt")
    try:
        with open(marker, encoding="utf-8") as f:
            val = f.read().strip()
            if val:
                return val
    except OSError:
        pass
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=backend_dir, timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


# 兼容旧名（宿主侧历史写法 `_git_commit()`）
_git_commit = git_commit
