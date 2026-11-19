"""独立核仓缺省大脑：仅 RAG 意图 + 出境分轨（host 未注入 central_brain 时使用）。"""
from __future__ import annotations

import logging
from typing import Any

from flask import current_app

from src.thomas_core.config import rag_egress_for_collection
from src.thomas_core.llm.call_llm import call_llm

logger = logging.getLogger("thomas_core.brain_rag")


def parse_intent(query: str, navigator_mode: bool = False):
    """独立核：一律走 rag（产品意图由宿主注入的大脑覆盖）。"""
    return "rag", 0.5, {}


def dispatch(
    *,
    intent: str,
    query: str,
    context: dict | None = None,
    slots: dict | None = None,
    _timing: dict | None = None,
) -> dict[str, Any]:
    context = context or {}
    slots = slots or {}
    collection = (
        current_app.config.get("CHROMA_COLLECTION")
        or "looma_knowledge"
    )
    privacy_mode = (
        current_app.config.get("RAG_PRIVACY_MODE")
        or "dual"
    )
    egress = rag_egress_for_collection(str(collection))

    results: list[dict] = []
    try:
        from src.thomas_core.rag.chroma_client import search_chroma

        results = search_chroma(query, n_results=5, collection=collection) or []
    except Exception as e:
        logger.warning("RAG search failed: %s", e)

    # 无命中时仍按集合策略分轨（避免静默走云）
    if not results and collection == "poetry_full":
        egress = rag_egress_for_collection("poetry_full")
    elif results:
        # 若结果带 collection 元数据则取首条
        meta0 = (results[0].get("metadata") or {}) if isinstance(results[0], dict) else {}
        coll_hit = meta0.get("collection") or collection
        egress = rag_egress_for_collection(str(coll_hit))

    llm_kwargs: dict[str, Any] = {}
    if egress == "local_only":
        llm_kwargs["allowed_providers"] = ("ollama",)

    if results:
        context_text = "\n\n".join(
            (r.get("content") or r.get("chunk_text") or "")[:800] for r in results[:5]
        )
        prompt = (
            "你是知识库助手。请根据参考资料回答用户问题；资料不足时如实说明。\n\n"
            f"参考资料：\n{context_text}\n\n"
            f"用户问题：{query}\n\n回答："
        )
    else:
        prompt = (
            "你是知识库助手。当前检索未命中文档，请基于通用知识简要回答，"
            "并说明未命中知识库。\n\n"
            f"用户问题：{query}\n\n回答："
        )
        # 无检索正文 → 公开/无检索可走 LLM_PROVIDER_ORDER（dual 下非强制 local）
        if (current_app.config.get("RAG_PRIVACY_MODE") or "dual") == "local_only":
            egress = "local_only"
            llm_kwargs["allowed_providers"] = ("ollama",)
        else:
            egress = "cloud_ok"
            llm_kwargs.pop("allowed_providers", None)

    llm_meta: dict[str, Any] = {}
    answer = call_llm(prompt, meta=llm_meta, **llm_kwargs)

    if answer is None and egress == "local_only":
        return {
            "answer": (
                "当前知识库内容需在本地模型生成；本地模型暂不可用，"
                "请稍后重试或联系管理员启用 Ollama。"
            ),
            "error": "rag_local_required",
            "egress": egress,
            "rag_privacy": privacy_mode,
            "llm_provider": None,
            "_sources": [
                {"id": r.get("id"), "score": r.get("score"), "chunk_text": ""}
                for r in results
            ],
            "slots": slots,
        }

    sources = [
        {
            "chunk_text": (r.get("content") or r.get("chunk_text") or "")[:200],
            "score": r.get("score"),
        }
        for r in results
    ]
    return {
        "answer": answer or "知识库检索失败，请稍后再试",
        "egress": egress,
        "rag_privacy": privacy_mode,
        "llm_provider": llm_meta.get("provider"),
        "_sources": sources,
        "slots": slots,
    }
