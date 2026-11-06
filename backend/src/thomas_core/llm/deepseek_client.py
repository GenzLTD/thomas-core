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
    """
    Generate a RAG answer using retrieved context chunks.

    Args:
        question: user's question
        context_chunks: list of text chunks from ChromaDB search

    Returns:
        Generated answer string
    """
    context_text = "\n\n---\n\n".join(context_chunks) if context_chunks else "(no context found)"

    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant. Answer the user's question based on the "
                "provided context. If the context doesn't contain relevant information, "
                "say so honestly. Always cite which context chunk you used.\n\n"
                f"Context:\n{context_text}"
            ),
        },
        {"role": "user", "content": question},
    ]

    result = chat_completion(messages)
    return result["choices"][0]["message"]["content"]
