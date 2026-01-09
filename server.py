# server.py — Velvet MCP Core (canonical)
# -----------------------------------------------------
# Goals:
# - Serve Telegram WebApp from /webapp/ (index.html + static assets)
# - Provide API endpoints: /api, /health, /version, /questions/random, /ritual/start, /ritual/complete
# - CORS enabled (Telegram WebApp + browsers)
# - Airtable random draw using Rand field
# - Keep behavior stable across Replit Run / Publish (PORT env)

import os
import json
import random
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# -----------------------------------------------------
# App / Static (CANON)
# -----------------------------------------------------
# Serve static assets from the "webapp" folder under /webapp/<asset>
app = Flask(__name__, static_folder="webapp", static_url_path="/webapp")

CORS(app, resources={r"/*": {"origins": "*"}})

APP_ENV = os.getenv("ENV", "BETA")  # default BETA; can be overridden by ENV
APP_VERSION = "v1.0-canonical-static-webapp"

print("🟢 SERVER.PY LOADED - canonical static webapp")

# -----------------------------------------------------
# CORS headers (explicit)
# -----------------------------------------------------
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


# -----------------------------------------------------
# Base routes
# -----------------------------------------------------
@app.get("/api")
def api_root():
    return jsonify({"service": "velvet-mcp-core", "status": "ok", "version": APP_VERSION}), 200


@app.get("/")
def root():
    # Keep / as a health-ish JSON for quick checks (curl).
    return jsonify({"service": "velvet-mcp-core", "status": "ok", "version": APP_VERSION}), 200


@app.get("/version")
def version():
    return jsonify({"version": APP_VERSION}), 200


@app.get("/ping")
def ping():
    return jsonify({"ok": True, "version": APP_VERSION}), 200


# -----------------------------------------------------
# Telegram WebApp entrypoints
# -----------------------------------------------------
@app.get("/webapp")
def webapp_root_no_slash():
    return send_from_directory("webapp", "index.html")


@app.get("/webapp/")
def webapp_root():
    return send_from_directory("webapp", "index.html")


# Note: static assets are served automatically at /webapp/<filename> by Flask static_folder/static_url_path.
# Example: /webapp/style.css -> webapp/style.css


# -----------------------------------------------------
# Health (Airtable ping)
# -----------------------------------------------------
@app.get("/health")
def health():
    air_ok = False
    air_error = None

    api_key = os.getenv("AIRTABLE_API_KEY", "")
    base_id = os.getenv("AIRTABLE_BASE_ID", "")
    table_id = os.getenv("AIRTABLE_TABLE_ID", "")

    if api_key and base_id and table_id:
        try:
            url = f"https://api.airtable.com/v0/{base_id}/{table_id}?maxRecords=1"
            r = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
            air_ok = (r.status_code == 200)
            if not air_ok:
                air_error = f"{r.status_code}: {r.text[:200]}"
        except Exception as e:
            air_error = str(e)
    else:
        air_error = "missing_env"

    return jsonify({
        "status": "ok",
        "version": APP_VERSION,
        "utc": datetime.now(timezone.utc).isoformat(),
        "airtable": {"ok": air_ok, "error": air_error},
    }), 200


# -----------------------------------------------------
# Questions — random draw + mapping
# -----------------------------------------------------
@app.route("/questions/random", methods=["GET", "OPTIONS"])
def questions_random():
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        count = int(request.args.get("count", "15"))
    except ValueError:
        count = 15
    count = max(1, min(50, count))

    api_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    table_id = os.getenv("AIRTABLE_TABLE_ID")

    if not (api_key and base_id and table_id):
        return jsonify({"error": "missing_env"}), 500

    headers = {"Authorization": f"Bearer {api_key}"}
    base_url = f"https://api.airtable.com/v0/{base_id}/{table_id}"

    threshold = random.randint(0, 999_999)

    def fetch_chunk(formula: str):
        params = {
            "maxRecords": count,
            "filterByFormula": formula,
            "sort[0][field]": "Rand",
            "sort[0][direction]": "asc",
        }
        rr = requests.get(base_url, headers=headers, params=params, timeout=12)
        if rr.status_code != 200:
            return rr, []
        return rr, rr.json().get("records", [])

    r1, recs = fetch_chunk(f"{{Rand}}>={threshold}")
    if r1.status_code == 200 and len(recs) < count:
        r2, recs2 = fetch_chunk(f"{{Rand}}<{threshold}")
        recs = recs + recs2

    if r1.status_code != 200:
        return jsonify({
            "error": "airtable_http_error",
            "status_code": r1.status_code,
            "detail": r1.text[:500],
        }), 502

    records = recs[:count]

    mapped = []
    for rec in records:
        f = rec.get("fields", {})

        raw_opts = f.get("Options (JSON)", "[]")
        try:
            opts = json.loads(raw_opts) if isinstance(raw_opts, str) else (raw_opts or [])
        except Exception:
            opts = []

        mapped.append({
            "id": f.get("ID_question"),
            "question": f.get("Question"),
            "options": opts,
            "correct_index": f.get("Correct_index"),
            "explanation": f.get("Explication"),
            "domaine": f.get("Domaine"),
            "niveau": f.get("Niveau"),
        })

    return jsonify({"count": count, "questions": mapped}), 200


# -----------------------------------------------------
# Airtable helpers (Core / Attempts)
# -----------------------------------------------------
def _airtable_headers():
    key = os.getenv("AIRTABLE_API_KEY") or os.getenv("AIRTABLE_KEY")
    if not key:
        return None
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _airtable_base_id(table_name=""):
    # BETA: use BETA_AIRTABLE_BASE_ID when available
    if APP_ENV.upper() == "BETA":
        return os.getenv("BETA_AIRTABLE_BASE_ID") or os.getenv("AIRTABLE_BASE_ID")

    # PROD: default to AIRTABLE_BASE_ID; allow core base override for core tables
    questions_table = os.getenv("AIRTABLE_TABLE_ID", "")
    core_tables = [
        "players",
        "rituel_attempts",
        "rituel_webapp_payloads",
        "rituel_answers",
        "rituel_feedback",
        os.getenv("AIRTABLE_PLAYERS_TABLE", ""),
        os.getenv("AIRTABLE_ATTEMPTS_TABLE", ""),
        os.getenv("AIRTABLE_PAYLOADS_TABLE", ""),
        os.getenv("AIRTABLE_ANSWERS_TABLE", ""),
        os.getenv("AIRTABLE_FEEDBACK_TABLE", ""),
    ]

    if table_name == questions_table:
        return os.getenv("AIRTABLE_BASE_ID")

    if table_name in core_tables:
        core_base = os.getenv("AIRTABLE_CORE_BASE_ID")
        if core_base:
            return core_base

    return os.getenv("AIRTABLE_BASE_ID")


def _airtable_url(table):
    base = _airtable_base_id(table)
    return f"https://api.airtable.com/v0/{base}/{table}"


def _core_table_name(prod_env_var: str, default_name: str, beta_env_var: str = "") -> str:
    if APP_ENV.upper() == "BETA":
        if beta_env_var:
            v = os.getenv(beta_env_var)
            if v:
                return v
        v2 = os.getenv(prod_env_var)
        return v2 or default_name
    v = os.getenv(prod_env_var)
    return v or default_name


def airtable_create(table, fields):
    headers = _airtable_headers()
    base = _airtable_base_id(table)
    if not headers or not base:
        return {"ok": False, "error": "missing_airtable_env"}
    r = requests.post(_airtable_url(table), headers=headers, json={"fields": fields}, timeout=20)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.status_code < 300, "status": r.status_code, "data": data}


def airtable_find_one(table, formula):
    headers = _airtable_headers()
    base = _airtable_base_id(table)
    if not headers or not base:
        return {"ok": False, "error": "missing_airtable_env"}
    r = requests.get(_airtable_url(table), headers=headers, params={"filterByFormula": formula, "maxRecords": 1}, timeout=20)
    data = r.json()
    recs = data.get("records", []) if isinstance(data, dict) else []
    return {"ok": r.status_code < 300, "status": r.status_code, "record": (recs[0] if recs else None), "data": data}


def upsert_player_by_telegram_user_id(players_table, telegram_user_id):
    formula = f"{{telegram_user_id}}='{telegram_user_id}'"
    found = airtable_find_one(players_table, formula)
    if found.get("ok") and found.get("record"):
        return {"ok": True, "action": "found", "record_id": found["record"]["id"]}

    created = airtable_create(players_table, {"telegram_user_id": str(telegram_user_id)})
    if created.get("ok"):
        return {"ok": True, "action": "created", "record_id": created["data"]["id"]}
    return {"ok": False, "error": created}


# -----------------------------------------------------
# Ritual endpoints
# -----------------------------------------------------
@app.route("/ritual/start", methods=["POST", "OPTIONS"])
def ritual_start():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = _json()
    telegram_user_id = payload.get("telegram_user_id") or payload.get("user_id") or payload.get("tg_user_id")

    if not telegram_user_id:
        return jsonify({"ok": False, "error": "missing_telegram_user_id"}), 400

    players_table = _core_table_name("AIRTABLE_PLAYERS_TABLE", "players", "BETA_AIRTABLE_PLAYERS_TABLE_ID")
    attempts_table = _core_table_name("AIRTABLE_ATTEMPTS_TABLE", "rituel_attempts", "BETA_AIRTABLE_ATTEMPTS_TABLE_ID")

    p = upsert_player_by_telegram_user_id(players_table, str(telegram_user_id))
    if not p.get("ok"):
        return jsonify({"ok": False, "error": "player_upsert_failed", "details": p}), 500

    raw_mode = payload.get("mode") or payload.get("env") or (APP_ENV.upper())
    if raw_mode in ("rituel_full_v1", "ritual_full_v1", "rituel_v1", "ritual_v1", "rituel_full_v1_http"):
        airtable_mode = "PROD"
    elif raw_mode == "TEST":
        airtable_mode = "TEST"
    else:
        airtable_mode = "PROD"

    fields = {
        "player": [p["record_id"]],
        "started_at": payload.get("started_at") or datetime.now(timezone.utc).isoformat(),
        "mode": airtable_mode,
        "env": APP_ENV.upper(),
        "score_max": int(payload.get("score_max") or payload.get("total") or 15),
        "attempt_label": payload.get("attempt_label") or datetime.now(timezone.utc).strftime("RIT-%Y%m%d-%H%M%S"),
    }

    created = airtable_create(attempts_table, fields)

    # Retry without fields that may not exist (safe fallback)
    if not created.get("ok") and created.get("status") == 422:
        fields.pop("attempt_label", None)
        created = airtable_create(attempts_table, fields)

    if not created.get("ok"):
        return jsonify({"ok": False, "error": "attempt_create_failed", "details": created}), 500

    attempt_id = created["data"].get("id")
    return jsonify({"ok": True, "attempt_id": attempt_id, "player_record_id": p["record_id"], "version": APP_VERSION}), 200


# /ritual/complete: keep minimal (log-only) to avoid breaking; you can extend later.
@app.route("/ritual/complete", methods=["POST", "OPTIONS"])
def ritual_complete():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = _json()
    # For now, acknowledge and return ok. You can wire Notion/Airtable writing here if needed.
    return jsonify({"ok": True, "version": APP_VERSION}), 200


# -----------------------------------------------------
# Debug: list routes
# -----------------------------------------------------
@app.get("/__routes")
def __routes():
    return jsonify({"ok": True, "version": APP_VERSION, "routes": sorted([str(r) for r in app.url_map.iter_rules()])}), 200


# -----------------------------------------------------
# Errors
# -----------------------------------------------------
@app.errorhandler(404)
def not_found(_):
    return jsonify({"error": "not_found"}), 404


@app.errorhandler(500)
def server_error(_):
    return jsonify({"error": "internal_server_error"}), 500


# -----------------------------------------------------
# Entrypoint local (optional)
# -----------------------------------------------------
if __name__ == "__main__":
    if os.getenv("RUN_LOCAL_SERVER") == "1":
        port = int(os.getenv("PORT", "5050"))
        app.run(host="0.0.0.0", port=port, debug=False)
    else:
        print("ℹ️ server.py: dev server désactivé (set RUN_LOCAL_SERVER=1 pour lancer en local).")
