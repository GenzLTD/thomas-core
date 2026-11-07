"""母舰答题（HarmonyOS 星海答题）。

只迁 start / answer / result / history。舰队、匹配、信号摄入仍在 looma-zervi
的产品 game_routes 里，核仓没有那些表和宿主模块。
结算补写与联调仓一致：/answer 把会话标成 completed 时不写 result_type，
第一次 GET /result 再补「专家级 / 进阶者 / 初学者」。
"""
from __future__ import annotations

import json
import logging

from flask import Blueprint, current_app, g, jsonify, request

from src.thomas_core.auth.decorators import require_auth
from src.thomas_core.db import quiz_store

logger = logging.getLogger("looma.game")

game_bp = Blueprint("game", __name__)

MOCK_QUIZ_QUESTIONS = [
    {
        "id": "q1", "text": "HarmonyOS 的 UI 框架叫什么？", "type": "single", "order": 1,
        "options": [
            {"id": "a", "text": "ArkUI", "value": 10},
            {"id": "b", "text": "React Native", "value": 0},
            {"id": "c", "text": "Flutter", "value": 0},
            {"id": "d", "text": "SwiftUI", "value": 0},
        ],
    },
    {
        "id": "q2", "text": "@State 装饰器的作用是什么？", "type": "single", "order": 2,
        "options": [
            {"id": "a", "text": "声明组件内部状态，变化时自动刷新 UI", "value": 10},
            {"id": "b", "text": "声明全局常量", "value": 0},
            {"id": "c", "text": "定义路由参数", "value": 0},
            {"id": "d", "text": "创建网络请求", "value": 0},
        ],
    },
    {
        "id": "q3", "text": "哪种数据结构是 FIFO（先进先出）？", "type": "single", "order": 3,
        "options": [
            {"id": "a", "text": "队列 (Queue)", "value": 10},
            {"id": "b", "text": "栈 (Stack)", "value": 0},
            {"id": "c", "text": "堆 (Heap)", "value": 0},
            {"id": "d", "text": "二叉树 (Binary Tree)", "value": 0},
        ],
    },
    {
        "id": "q4", "text": "以下哪个是 Looma 后端使用的 Web 框架？", "type": "single", "order": 4,
        "options": [
            {"id": "a", "text": "Flask (Python)", "value": 10},
            {"id": "b", "text": "Express (Node.js)", "value": 0},
            {"id": "c", "text": "Spring Boot (Java)", "value": 0},
            {"id": "d", "text": "Gin (Go)", "value": 0},
        ],
    },
    {
        "id": "q5", "text": "SQLite 的 WAL 模式主要优势是什么？", "type": "single", "order": 5,
        "options": [
            {"id": "a", "text": "支持并发读写，读不阻塞写", "value": 10},
            {"id": "b", "text": "数据加密存储", "value": 0},
            {"id": "c", "text": "自动备份到云端", "value": 0},
            {"id": "d", "text": "支持分布式查询", "value": 0},
        ],
    },
]


def _get_db():
    return current_app._db


def _score_answer(question: dict, selected_ids: list) -> int:
    score = 0
    for opt in question.get("options", []):
        if opt["id"] in selected_ids:
            score += opt.get("value", 0)
    return score


def _explain_answer(question: dict, selected_ids: list) -> str:
    correct = [opt["text"] for opt in question.get("options", []) if opt.get("value", 0) > 0]
    if not correct:
        return "请查看答案解析。"
    return "正确答案是: " + ", ".join(correct)


@game_bp.route("/start", methods=["POST"])
@require_auth
def quiz_start():
    """POST /v1/game/start — 新开一局，返回 session_id 和题目。"""
    session = quiz_store.create_quiz_session(
        _get_db(),
        g.user_id,
        json.dumps(MOCK_QUIZ_QUESTIONS, ensure_ascii=False),
    )
    return jsonify(
        session_id=session["id"],
        questions=MOCK_QUIZ_QUESTIONS,
        total=len(MOCK_QUIZ_QUESTIONS),
    ), 201


@game_bp.route("/answer", methods=["POST"])
@require_auth
def quiz_answer():
    """POST /v1/game/answer — body: session_id, question_id, option_ids."""
    data = request.get_json() or {}
    session_id = (data.get("session_id") or "").strip()
    question_id = (data.get("question_id") or "").strip()
    option_ids = data.get("option_ids") or []
    if not session_id:
        return jsonify(error="bad_request", message="session_id required"), 400
    if not question_id:
        return jsonify(error="bad_request", message="question_id required"), 400

    db = _get_db()
    session = quiz_store.get_quiz_session(db, session_id)
    if not session:
        return jsonify(error="not_found", message="quiz session not found"), 404
    if session["user_id"] != g.user_id:
        return jsonify(error="forbidden", message="not your session"), 403

    questions = json.loads(session["questions_json"])
    current = next((q for q in questions if q["id"] == question_id), None)
    if current is None:
        return jsonify(error="bad_request", message="question not in this session"), 400

    score = _score_answer(current, option_ids)
    updated = quiz_store.submit_quiz_answer(db, session_id, question_id, option_ids, score)
    if not updated:
        return jsonify(error="server_error", message="failed to record answer"), 500

    completed = updated["status"] == "completed"
    body = {
        "correct": score > 0,
        "score": score,
        "explanation": _explain_answer(current, option_ids),
        "completed": completed,
    }
    if not completed:
        nxt = updated["current_index"]
        if nxt < len(questions):
            body["next_question"] = questions[nxt]
    return jsonify(body)


@game_bp.route("/result", methods=["GET"])
@require_auth
def quiz_result():
    """GET /v1/game/result?session_id= — 补写 result_type 后返回结算。"""
    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return jsonify(error="bad_request", message="session_id required"), 400

    db = _get_db()
    session = quiz_store.get_quiz_session(db, session_id)
    if not session:
        return jsonify(error="not_found", message="quiz session not found"), 404
    if session["user_id"] != g.user_id:
        return jsonify(error="forbidden", message="not your session"), 403

    if session["status"] != "completed" or not (session.get("result_type") or "").strip():
        total = session["total_questions"] or 1
        pct = session["total_score"] / (total * 10) if total > 0 else 0
        if pct >= 0.8:
            result_type = "专家级"
        elif pct >= 0.5:
            result_type = "进阶者"
        else:
            result_type = "初学者"
        insights = [
            f"答对 {session['correct_count']}/{session['total_questions']} 题",
            f"总得分 {session['total_score']} 分",
        ]
        session = quiz_store.complete_quiz_session(
            db,
            session_id,
            result_type=result_type,
            insights_json=json.dumps(insights, ensure_ascii=False),
        )
        _record_side_effects(db, session_id, result_type, session)

    insights = json.loads(session.get("insights_json") or "[]")
    return jsonify(
        session_id=session["id"],
        total_score=session["total_score"],
        total_questions=session["total_questions"],
        correct_count=session["correct_count"],
        result_type=session.get("result_type") or "",
        insights=insights,
    )


@game_bp.route("/history", methods=["GET"])
@require_auth
def quiz_history():
    """GET /v1/game/history — 当前用户已完成的答题。"""
    records = quiz_store.get_quiz_history(_get_db(), g.user_id)
    return jsonify(sessions=records, total=len(records))


def _record_side_effects(db, session_id: str, result_type: str, session: dict) -> None:
    """信任记忆和时间线都是产品侧能力。核里没有就跳过，不影响结算。"""
    try:
        if hasattr(db, "insert_trust_memory"):
            db.insert_trust_memory(
                user_id=g.user_id,
                session_type="quiz",
                session_id=session_id,
                memory_content={
                    "result_type": result_type,
                    "total_score": session["total_score"],
                    "correct_count": session["correct_count"],
                    "total_questions": session["total_questions"],
                },
                memory_level=1,
            )
    except Exception as exc:
        logger.warning("trust_agent: harmonyos quiz memory skipped for %s: %s", g.user_id, exc)
    try:
        from src.timeline.events import record_learning_activity

        record_learning_activity(
            db,
            g.user_id,
            source_ref=session_id,
            activity_type="harmony_quiz",
            title="完成鸿蒙答题",
            summary=f"{result_type} · {session['correct_count']}/{session['total_questions']}",
            score=session["total_score"],
            total=session["total_questions"],
            correct_count=session["correct_count"],
            result_type=result_type,
        )
    except Exception as exc:
        logger.warning("timeline: learning_activity skipped for %s: %s", g.user_id, exc)
