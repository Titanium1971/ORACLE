# server.py — Velvet MCP Core (MODEFIX)
# Corrige définitivement les erreurs Airtable "Unknown field name"

import os
import json
import random
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

APP_VERSION = "v1.0-canonical-static-webapp"
APP_ENV = os.getenv("ENV", "BETA").upper()

# Flask sans static automatique (stabilité /webapp)
app = Flask(__name__, static_folder=None)
CORS(app, resources={r"/*": {"origins": "*"}})

WEBAPP_DIR = "webapp"

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Telegram-InitData"
    return response


def _json():
    try:
        return request.get_json(force=True, silent=False) or {}
    except Exception:
        return {}


# -------------------------------------------------
# WebApp
# -------------------------------------------------
@app.get("/webapp")
@app.get("/webapp/")
def webapp_root():
    return send_from_directory(WEBAPP_DIR, "index.html")


@app.get("/webapp/<path:filename>")
def webapp_assets(filename):
    return send_from_directory(WEBAPP_DIR, filename)


# -------------------------------------------------
# API
# -------------------------------------------------
@app.get("/api")
def api_root():
    return jsonify({"service": "velvet-mcp-core", "status": "ok", "version": APP_VERSION}), 200


@app.get("/version")
def version():
    return jsonify({"version": APP_VERSION}), 200


# -------------------------------------------------
# Airtable helpers
# -------------------------------------------------
def _airtable_headers():
    key = os.getenv("AIRTABLE_API_KEY")
    if not key:
        return None
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _airtable_base_id():
    return os.getenv("BETA_AIRTABLE_BASE_ID") or os.getenv("AIRTABLE_BASE_ID")


def _airtable_url(table):
    return f"https://api.airtable.com/v0/{_airtable_base_id()}/{table}"


def airtable_create(table, fields):
    headers = _airtable_headers()
    if not headers:
        return {"ok": False, "error": "missing_airtable_key"}

    r = requests.post(_airtable_url(table), headers=headers, json={"fields": fields})
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}

    return {"ok": r.status_code < 300, "status": r.status_code, "data": data}


def airtable_find_one(table, formula):
    headers = _airtable_headers()
    if not headers:
        return None

    r = requests.get(
        _airtable_url(table),
        headers=headers,
        params={"filterByFormula": formula, "maxRecords": 1},
    )
    data = r.json()
    recs = data.get("records", []) if isinstance(data, dict) else []
    return recs[0] if recs else None


# -------------------------------------------------
# Ritual start (MODEFIX)
# -------------------------------------------------
@app.route("/ritual/start", methods=["POST", "OPTIONS"])
def ritual_start():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = _json()
    telegram_user_id = payload.get("telegram_user_id")

    if not telegram_user_id:
        return jsonify({"ok": False, "error": "missing_telegram_user_id"}), 400

    players_table = os.getenv("BETA_AIRTABLE_PLAYERS_TABLE_ID") or "players"
    attempts_table = os.getenv("BETA_AIRTABLE_ATTEMPTS_TABLE_ID") or "rituel_attempts"

    # Upsert player
    rec = airtable_find_one(players_table, f"{{telegram_user_id}}='{telegram_user_id}'")
    if rec:
        player_id = rec["id"]
    else:
        created = airtable_create(players_table, {"telegram_user_id": str(telegram_user_id)})
        if not created.get("ok"):
            return jsonify({"ok": False, "error": "player_create_failed"}), 500
        player_id = created["data"]["id"]

    fields = {
        "player": [player_id],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "mode": payload.get("mode", "TEST"),
        "env": APP_ENV,
        "score_max": 15,
        "attempt_label": datetime.now(timezone.utc).strftime("RIT-%Y%m%d-%H%M%S"),
    }

    created = airtable_create(attempts_table, fields)

    # 🔥 MODEFIX : purge champs inconnus
    if not created.get("ok") and created.get("status") == 422:
        msg = str(created.get("data"))
        for k in ("mode", "env", "score_max", "attempt_label"):
            if k in fields:
                fields.pop(k, None)

        created = airtable_create(attempts_table, fields)

        if not created.get("ok") and created.get("status") == 422:
            created = airtable_create(
                attempts_table,
                {"player": [player_id], "started_at": fields["started_at"]},
            )

    if not created.get("ok"):
        return jsonify({"ok": False, "error": "attempt_create_failed", "details": created}), 500

    return jsonify(
        {
            "ok": True,
            "attempt_id": created["data"]["id"],
            "player_record_id": player_id,
            "version": APP_VERSION,
        }
    ), 200


# -------------------------------------------------
# Errors
# -------------------------------------------------
@app.errorhandler(404)
def not_found(_):
    return "Not Found", 404


@app.errorhandler(500)
def server_error(_):
    return jsonify({"error": "internal_server_error"}), 500
