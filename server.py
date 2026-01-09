# server.py — Velvet MCP Core (MODEFIX + RITUAL_COMPLETE)
# -----------------------------------------------------
# - WebApp stable: /webapp/ (index.html) + /webapp/<asset>
# - API: /api, /version, /health, /questions/random
# - Ritual: /ritual/start (MODEFIX schema) + /ritual/complete (best-effort writes)
# - CORS enabled

import os
import json
import random
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

APP_VERSION = "v1.0-canonical-static-webapp"
APP_ENV = os.getenv("ENV", "BETA").upper()
WEBAPP_DIR = "webapp"

# Disable Flask automatic static route to avoid conflicts; we serve /webapp/<asset> ourselves.
app = Flask(__name__, static_folder=None)
CORS(app, resources={r"/*": {"origins": "*"}})

print("🟢 SERVER.PY LOADED -", APP_VERSION, "| ENV=", APP_ENV)


# -------------------------------------------------
# CORS explicit
# -------------------------------------------------
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


def now_iso():
    return datetime.now(timezone.utc).isoformat()


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
# API basics
# -------------------------------------------------
@app.get("/api")
def api_root():
    return jsonify({"service": "velvet-mcp-core", "status": "ok", "version": APP_VERSION}), 200


@app.get("/version")
def version():
    return jsonify({"version": APP_VERSION}), 200


@app.get("/health")
def health():
    air_ok = False
    air_error = None

    api_key = os.getenv("AIRTABLE_API_KEY", "")
    base_id = os.getenv("AIRTABLE_BASE_ID", "") or (os.getenv("BETA_AIRTABLE_BASE_ID", "") if APP_ENV == "BETA" else "")
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
        "utc": now_iso(),
        "airtable": {"ok": air_ok, "error": air_error},
    }), 200


# -------------------------------------------------
# Airtable helpers (MODEFIX-friendly)
# -------------------------------------------------
def _airtable_headers():
    key = os.getenv("AIRTABLE_API_KEY") or os.getenv("AIRTABLE_KEY")
    if not key:
        return None
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _airtable_base_id():
    # BETA uses BETA_AIRTABLE_BASE_ID when present
    if APP_ENV == "BETA":
        return os.getenv("BETA_AIRTABLE_BASE_ID") or os.getenv("AIRTABLE_BASE_ID")
    return os.getenv("AIRTABLE_BASE_ID")


def _airtable_url(table):
    base = _airtable_base_id()
    return f"https://api.airtable.com/v0/{base}/{table}"


def airtable_create(table, fields):
    headers = _airtable_headers()
    base = _airtable_base_id()
    if not headers or not base:
        return {"ok": False, "error": "missing_airtable_env"}

    r = requests.post(_airtable_url(table), headers=headers, json={"fields": fields}, timeout=20)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.status_code < 300, "status": r.status_code, "data": data}


def airtable_update(table, record_id, fields):
    headers = _airtable_headers()
    base = _airtable_base_id()
    if not headers or not base:
        return {"ok": False, "error": "missing_airtable_env"}

    r = requests.patch(_airtable_url(table) + f"/{record_id}", headers=headers, json={"fields": fields}, timeout=20)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"ok": r.status_code < 300, "status": r.status_code, "data": data}


def airtable_find_one(table, formula):
    headers = _airtable_headers()
    base = _airtable_base_id()
    if not headers or not base:
        return {"ok": False, "error": "missing_airtable_env"}

    r = requests.get(_airtable_url(table), headers=headers, params={"filterByFormula": formula, "maxRecords": 1}, timeout=20)
    data = r.json() if r.text else {}
    recs = data.get("records", []) if isinstance(data, dict) else []
    return {"ok": r.status_code < 300, "status": r.status_code, "record": (recs[0] if recs else None), "data": data}


def _core_table(env_var: str, default_name: str):
    # In BETA, you likely store table IDs in BETA_... env vars. If absent, fallback to default_name.
    v = os.getenv(env_var)
    return v or default_name


def _strip_on_422(created_resp, fields, remove_keys):
    """
    If Airtable says Unknown field name on 422, remove fields and return updated fields.
    """
    msg = ""
    try:
        msg = (created_resp.get("data") or {}).get("error", {}).get("message", "")
    except Exception:
        msg = ""

    if not msg:
        msg = str(created_resp.get("data") or "")

    if "Unknown field name" not in str(msg):
        return fields  # not a schema error

    for k in remove_keys:
        if k in fields:
            # if msg mentions key or generic unknown field, remove
            if (k in str(msg)) or ("Unknown field name" in str(msg)):
                fields.pop(k, None)

    return fields


# -------------------------------------------------
# Questions — random draw + mapping
# -------------------------------------------------
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
    base_id = _airtable_base_id()
    table_id = os.getenv("AIRTABLE_TABLE_ID")  # questions table id/name

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


# -------------------------------------------------
# /ritual/start (MODEFIX schema)
# -------------------------------------------------
@app.route("/ritual/start", methods=["POST", "OPTIONS"])
def ritual_start():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = _json()
    telegram_user_id = payload.get("telegram_user_id") or payload.get("user_id") or payload.get("tg_user_id")
    if not telegram_user_id:
        return jsonify({"ok": False, "error": "missing_telegram_user_id"}), 400

    players_table = _core_table("BETA_AIRTABLE_PLAYERS_TABLE_ID", "players")
    attempts_table = _core_table("BETA_AIRTABLE_ATTEMPTS_TABLE_ID", "rituel_attempts")

    # Upsert player
    found = airtable_find_one(players_table, f"{{telegram_user_id}}='{telegram_user_id}'")
    if not found.get("ok"):
        return jsonify({"ok": False, "error": "player_lookup_failed", "details": found}), 500

    if found.get("record"):
        player_id = found["record"]["id"]
    else:
        created_player = airtable_create(players_table, {"telegram_user_id": str(telegram_user_id)})
        if not created_player.get("ok"):
            return jsonify({"ok": False, "error": "player_create_failed", "details": created_player}), 500
        player_id = created_player["data"]["id"]

    fields = {
        "player": [player_id],
        "started_at": payload.get("started_at") or now_iso(),
        "mode": payload.get("mode", "TEST"),
        "env": APP_ENV,
        "score_max": int(payload.get("score_max") or payload.get("total") or 15),
        "attempt_label": payload.get("attempt_label") or datetime.now(timezone.utc).strftime("RIT-%Y%m%d-%H%M%S"),
    }

    created = airtable_create(attempts_table, fields)

    # MODEFIX: if schema mismatch, remove optional fields (mode/env/score_max/attempt_label), then minimal
    if (not created.get("ok")) and created.get("status") == 422:
        fields = _strip_on_422(created, fields, ("mode", "env", "score_max", "attempt_label"))
        created = airtable_create(attempts_table, fields)

        if (not created.get("ok")) and created.get("status") == 422:
            minimal = {k: fields[k] for k in ("player", "started_at") if k in fields}
            created = airtable_create(attempts_table, minimal)

    if not created.get("ok"):
        return jsonify({"ok": False, "error": "attempt_create_failed", "details": created}), 500

    return jsonify({
        "ok": True,
        "attempt_id": created["data"]["id"],
        "player_record_id": player_id,
        "version": APP_VERSION,
    }), 200


# -------------------------------------------------
# /ritual/complete (best-effort writes)
# -------------------------------------------------
@app.route("/ritual/complete", methods=["POST", "OPTIONS"])
def ritual_complete():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = _json()
    attempt_id = payload.get("attempt_id") or payload.get("attemptId") or payload.get("id")
    telegram_user_id = payload.get("telegram_user_id") or payload.get("user_id") or payload.get("tg_user_id")

    if not attempt_id:
        return jsonify({"ok": False, "error": "missing_attempt_id"}), 400

    attempts_table = _core_table("BETA_AIRTABLE_ATTEMPTS_TABLE_ID", "rituel_attempts")
    answers_table = _core_table("BETA_AIRTABLE_ANSWERS_TABLE_ID", "rituel_answers")
    feedback_table = _core_table("BETA_AIRTABLE_FEEDBACK_TABLE_ID", "rituel_feedback")

    # 1) Update attempt (best effort)
    upd_fields = {
        "completed_at": payload.get("completed_at") or now_iso(),
        "score_raw": payload.get("score_raw"),
        "score_max": payload.get("score_max"),
        "time_total_seconds": payload.get("time_total_seconds"),
    }

    # remove None values
    upd_fields = {k: v for k, v in upd_fields.items() if v is not None}

    upd = airtable_update(attempts_table, attempt_id, upd_fields) if upd_fields else {"ok": True}

    # Retry if schema mismatch
    if (not upd.get("ok")) and upd.get("status") == 422:
        # strip common missing fields
        upd_fields = _strip_on_422(upd, upd_fields, ("completed_at", "score_raw", "score_max", "time_total_seconds"))
        upd = airtable_update(attempts_table, attempt_id, upd_fields) if upd_fields else {"ok": True}

    # 2) Create answers records (best effort)
    answers = payload.get("answers") or []
    answers_written = 0
    answers_errors = []

    if isinstance(answers, list) and len(answers) > 0:
        for a in answers[:60]:  # hard cap
            if not isinstance(a, dict):
                continue
            fields = {
                "exam": [attempt_id],  # common naming (linked to attempts)
                "question_id": a.get("question_id") or a.get("id") or a.get("qid"),
                "choice_letter": a.get("choice_letter"),
                "status": a.get("status"),
                "is_correct": a.get("is_correct"),
            }
            # remove None
            fields = {k: v for k, v in fields.items() if v is not None}

            created = airtable_create(answers_table, fields)
            if (not created.get("ok")) and created.get("status") == 422:
                fields = _strip_on_422(created, fields, ("question_id", "choice_letter", "status", "is_correct"))
                # minimal fallback
                minimal = {"exam": [attempt_id]}
                if fields.get("question_id") is not None:
                    minimal["question_id"] = fields["question_id"]
                created = airtable_create(answers_table, minimal)

            if created.get("ok"):
                answers_written += 1
            else:
                answers_errors.append(created)

    # 3) Create feedback record (best effort)
    feedback_text = payload.get("feedback_text") or payload.get("comment_text") or ""
    feedback_written = False
    feedback_err = None

    if isinstance(feedback_text, str) and feedback_text.strip():
        fb_fields = {
            "exam": [attempt_id],
            "player_telegram_user_id": str(telegram_user_id) if telegram_user_id else None,
            "feedback_text": feedback_text.strip(),
            "created_at": now_iso(),
        }
        fb_fields = {k: v for k, v in fb_fields.items() if v is not None}

        fb = airtable_create(feedback_table, fb_fields)
        if (not fb.get("ok")) and fb.get("status") == 422:
            fb_fields = _strip_on_422(fb, fb_fields, ("player_telegram_user_id", "feedback_text", "created_at"))
            # minimal
            minimal = {"exam": [attempt_id]}
            if fb_fields.get("feedback_text"):
                minimal["feedback_text"] = fb_fields["feedback_text"]
            fb = airtable_create(feedback_table, minimal)

        if fb.get("ok"):
            feedback_written = True
        else:
            feedback_err = fb

    return jsonify({
        "ok": True,
        "attempt_id": attempt_id,
        "attempt_update_ok": bool(upd.get("ok", True)),
        "answers_written": answers_written,
        "feedback_written": feedback_written,
        "warnings": {
            "attempt_update": None if upd.get("ok", True) else upd,
            "answers_errors_count": len(answers_errors),
            "feedback_error": feedback_err,
        },
        "version": APP_VERSION,
    }), 200


# -------------------------------------------------
# Debug routes listing
# -------------------------------------------------
@app.get("/__routes")
def __routes():
    return jsonify({"ok": True, "version": APP_VERSION, "routes": sorted([str(r) for r in app.url_map.iter_rules()])}), 200


# -------------------------------------------------
# Errors
# -------------------------------------------------
@app.errorhandler(404)
def not_found(_):
    return "Not Found", 404


@app.errorhandler(500)
def server_error(_):
    return jsonify({"error": "internal_server_error"}), 500


if __name__ == "__main__":
    if os.getenv("RUN_LOCAL_SERVER") == "1":
        port = int(os.getenv("PORT", "5050"))
        app.run(host="0.0.0.0", port=port, debug=False)
    else:
        print("ℹ️ server.py: dev server désactivé (set RUN_LOCAL_SERVER=1 pour lancer en local).")
