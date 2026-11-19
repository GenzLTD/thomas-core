"""
DeepSeek API client.
Handles chat completions and streaming responses.
"""
import requests
from flask import current_app


def chat_completion(messages: list, stream: bool = False, temperature: float = 0.7) -> dict:
    """
    Call DeepSeek chat completion API.

    Args:
        messages: list of {"role": "system"|"user"|"assistant", "content": "..."}
        stream: whether to stream the response
        temperature: sampling temperature (0-2)

    Returns:
        API response dict (or generator if stream=True)
    """
    config = current_app.config
    url = f"{config['DEEPSEEK_BASE_URL']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['DEEPSEEK_API_KEY']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config["DEEPSEEK_MODEL"],
        "messages": messages,
        "stream": stream,
        "temperature": temperature,
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()


def rag_answer(question: str, context_chunks: list) -> str:
    """禁用：RAG 生成必须走 call_llm + rag_egress 分轨，禁止无闸门直连 DeepSeek。"""
    raise RuntimeError(
        "deepseek_client.rag_answer is disabled; use call_llm with rag egress policy "
        "(privacy dual-track)."
    )
