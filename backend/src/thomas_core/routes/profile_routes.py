"""画像的删除和导出。只操作当前登录用户，不接受别人的 user_id。"""
from __future__ import annotations

from flask import Blueprint, g, jsonify

from src.thomas_core.auth.decorators import require_auth
from src.thomas_core.profile.engine import delete_user_data, export_user_data

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/export", methods=["GET"])
@require_auth
def export_profile():
    return jsonify(export_user_data(g.user_id))


@profile_bp.route("", methods=["DELETE"])
@require_auth
def delete_profile():
    return jsonify(delete_user_data(g.user_id))
