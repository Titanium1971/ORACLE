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
    "openai": {
        "has_key": bool(os.getenv("OPENAI_API_KEY")),
        "model": os.getenv("OPENAI_MODEL") or "",
    },
    "env": APP_ENV,
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

def airtable_update(table, record_id, fields):
    headers = _airtable_headers()
    base = _airtable_base_id(table)
    if not headers or not base:
        return {"ok": False, "error": "missing_airtable_env"}
    url = f"{_airtable_url(table)}/{record_id}"
    r = requests.patch(url, headers=headers, json={"fields": fields}, timeout=20)
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


# /ritual/complete: write completion + answers (+ optional payload, feedback) to Airtable CORE tables.
@app.route("/ritual/complete", methods=["POST", "OPTIONS"])
def ritual_complete():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = _json() or {}

    attempt_id = payload.get("attempt_id") or payload.get("attemptId") or payload.get("id")
    telegram_user_id = payload.get("telegram_user_id") or payload.get("user_id") or payload.get("tg_user_id")

    # We keep the endpoint "best-effort": never hard-crash the ritual UX.
    if not attempt_id:
        return jsonify({"ok": False, "error": "missing_attempt_id"}), 400

    # Tables (BETA/PROD aware)
    players_table  = _core_table_name("AIRTABLE_PLAYERS_TABLE",   "players",                 "BETA_AIRTABLE_PLAYERS_TABLE_ID")
    attempts_table = _core_table_name("AIRTABLE_ATTEMPTS_TABLE",  "rituel_attempts",         "BETA_AIRTABLE_ATTEMPTS_TABLE_ID")
    answers_table  = _core_table_name("AIRTABLE_ANSWERS_TABLE",   "rituel_answers",          "BETA_AIRTABLE_ANSWERS_TABLE_ID")
    payloads_table = _core_table_name("AIRTABLE_PAYLOADS_TABLE",  "rituel_webapp_payloads",  "BETA_AIRTABLE_PAYLOADS_TABLE_ID")
    feedback_table = _core_table_name("AIRTABLE_FEEDBACK_TABLE",  "rituel_feedback",         "BETA_AIRTABLE_FEEDBACK_TABLE_ID")

    # Upsert player (optional but useful for links)
    player_record_id = None
    if telegram_user_id:
        p = upsert_player_by_telegram_user_id(players_table, str(telegram_user_id))
        if p.get("ok"):
            player_record_id = p.get("record_id")

    # --- 1) Update attempt (best-effort, with 422 fallback) ---
    completed_at = payload.get("completed_at") or datetime.now(timezone.utc).isoformat()
    score_raw = payload.get("score_raw")
    score_max = payload.get("score_max")
    time_total_seconds = payload.get("time_total_seconds")

    attempt_fields_variants = [
        {
            "completed_at": completed_at,
            "score_raw": int(score_raw) if score_raw is not None else None,
            "score_max": int(score_max) if score_max is not None else None,
            "time_total_seconds": int(time_total_seconds) if time_total_seconds is not None else None,
            "status": "COMPLETED",
        },
        {
            "completed_at": completed_at,
            "score_raw": int(score_raw) if score_raw is not None else None,
            "score_max": int(score_max) if score_max is not None else None,
            "time_total_seconds": int(time_total_seconds) if time_total_seconds is not None else None,
        },
        {
            "completed_at": completed_at,
        },
    ]

    attempt_updated = False
    attempt_update_status = None
    for fields in attempt_fields_variants:
        # remove None values (Airtable doesn't like explicit nulls sometimes)
        fields = {k: v for k, v in fields.items() if v is not None}
        if not fields:
            continue
        upd = airtable_update(attempts_table, attempt_id, fields)
        attempt_update_status = upd.get("status")
        if upd.get("ok"):
            attempt_updated = True
            break

    # --- 2) Store raw payload (optional, best-effort) ---
    payload_written = False
    payload_write_status = None
    try:
        client_payload = payload.get("client_payload")
        if client_payload is None:
            # if not nested, store the full body
            client_payload = payload
        payload_json = json.dumps(client_payload, ensure_ascii=False)[:90000]

        fields_variants = [
            {"exam": [attempt_id], "player": ([player_record_id] if player_record_id else None), "payload_json": payload_json, "created_at": completed_at},
            {"exam": [attempt_id], "payload_json": payload_json, "created_at": completed_at},
            {"payload_json": payload_json},
        ]
        for fv in fields_variants:
            fv = {k: v for k, v in fv.items() if v is not None}
            if not fv:
                continue
            cr = airtable_create(payloads_table, fv)
            payload_write_status = cr.get("status")
            if cr.get("ok"):
                payload_written = True
                break
    except Exception:
        pass

    # --- 3) Write answers (best-effort, with progressive field fallback) ---
    answers_in = payload.get("answers") or []
    if not isinstance(answers_in, list):
        answers_in = []

    answers_written = 0
    answers_failed = 0
    last_answer_error = None

    for a in answers_in:
        if not isinstance(a, dict):
            continue

        qid = a.get("question_id") or a.get("qid") or a.get("id")
        selected_index = a.get("selected_index")
        status = a.get("status")
        is_correct = a.get("is_correct")
        correct_index = a.get("correct_index")

        # Variants: start rich, then progressively minimal to survive unknown schemas.
        variants = [
            {
                "exam": [attempt_id],
                "player": ([player_record_id] if player_record_id else None),
                "question_id": str(qid) if qid is not None else None,
                "selected_index": int(selected_index) if selected_index is not None else None,
                "status": str(status) if status is not None else None,
                "is_correct": bool(is_correct) if is_correct is not None else None,
                "correct_index": int(correct_index) if correct_index is not None else None,
                "created_at": completed_at,
            },
            {
                "exam": [attempt_id],
                "question_id": str(qid) if qid is not None else None,
                "selected_index": int(selected_index) if selected_index is not None else None,
                "status": str(status) if status is not None else None,
            },
            {
                "exam": [attempt_id],
                "question_id": str(qid) if qid is not None else None,
            },
        ]

        ok_one = False
        for fields in variants:
            fields = {k: v for k, v in fields.items() if v is not None}
            if not fields:
                continue
            cr = airtable_create(answers_table, fields)
            if cr.get("ok"):
                ok_one = True
                answers_written += 1
                break
            else:
                last_answer_error = cr
                # on 422, try simpler; on other errors, also try simpler once, then give up
                continue

        if not ok_one:
            answers_failed += 1

    # --- 4) Optional feedback row ---
    feedback_written = False
    feedback_write_status = None
    feedback_text = payload.get("feedback_text") or ""
    try:
        feedback_text = str(feedback_text).strip()
    except Exception:
        feedback_text = ""

    if feedback_text:
        fb_variants = [
            {"exam": [attempt_id], "player": ([player_record_id] if player_record_id else None), "feedback_text": feedback_text[:1900], "created_at": completed_at},
            {"exam": [attempt_id], "feedback_text": feedback_text[:1900], "created_at": completed_at},
            {"feedback_text": feedback_text[:1900]},
        ]
        for fv in fb_variants:
            fv = {k: v for k, v in fv.items() if v is not None}
            if not fv:
                continue
            cr = airtable_create(feedback_table, fv)
            feedback_write_status = cr.get("status")
            if cr.get("ok"):
                feedback_written = True
                break

    return jsonify({
        "ok": True,
        "version": APP_VERSION,
        "attempt_id": attempt_id,
        "attempt_updated": attempt_updated,
        "answers_written": answers_written,
        "answers_failed": answers_failed,
        "payload_written": payload_written,
        "feedback_written": feedback_written,
        "debug": {
            "attempt_update_status": attempt_update_status,
            "payload_write_status": payload_write_status,
            "feedback_write_status": feedback_write_status,
            "env": APP_ENV,
        }
    }), 200


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
