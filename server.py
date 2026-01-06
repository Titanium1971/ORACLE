# server.py — Velvet MCP Core (local, propre, souverain)
# -----------------------------------------------------
# - /health avec ping Airtable réel
# - CORS actif
# - /questions/random renvoie des questions prêtes pour le front
# - Tirage réellement aléatoire via champ "Rand" (Airtable)

import os
import json
import random
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

from flask_cors import CORS

CORS(app, resources={r"/*": {"origins": "*"}})

APP_VERSION = "v0.6-ritual-start-complete-airtable"


# -----------------------------------------------------
# CORS minimal (front local)
# -----------------------------------------------------
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers[
        "Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Telegram-InitData"
    return response


# -----------------------------------------------------
# Routes de base
# -----------------------------------------------------
@app.get("/")
def root():
    return jsonify({
        "service": "velvet-mcp-core",
        "status": "ok",
        "version": APP_VERSION,
    }), 200


@app.get("/version")
def version():
    return jsonify({"version": APP_VERSION}), 200


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
            r = requests.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
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
        "method": request.method,
        "airtable": {
            "ok": air_ok,
            "error": air_error,
        },
    }), 200


# -----------------------------------------------------
# Questions — tirage aléatoire + mapping propre
# -----------------------------------------------------
@app.route("/questions/random", methods=["GET", "OPTIONS"])
def questions_random():
    # Preflight CORS (au cas où)
    if request.method == "OPTIONS":
        return "", 204

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
        rr = requests.get(base_url, headers=headers, params=params, timeout=10)
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
            opts = json.loads(raw_opts) if isinstance(
                raw_opts, str) else (raw_opts or [])
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

    return jsonify({
        "count": count,
        "questions": mapped,
    }), 200


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
# Entrypoint local
# -----------------------------------------------------

# ================================================================
# Ritual endpoints (WebApp → Airtable)
# ================================================================
from flask import abort

def _json():
    try:
        return request.get_json(force=True, silent=False) or {}
    except Exception:
        return {}

def _airtable_headers():
    key = os.getenv("AIRTABLE_API_KEY") or os.getenv("AIRTABLE_KEY")
    if not key:
        return None
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

def _airtable_base_id():
    return os.getenv("AIRTABLE_BASE_ID") or os.getenv("AIRTABLE_BASE")

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

def airtable_find_one(table, formula):
    headers = _airtable_headers()
    base = _airtable_base_id()
    if not headers or not base:
        return {"ok": False, "error": "missing_airtable_env"}
    r = requests.get(_airtable_url(table), headers=headers, params={"filterByFormula": formula, "maxRecords": 1}, timeout=20)
    data = r.json()
    recs = data.get("records", []) if isinstance(data, dict) else []
    return {"ok": r.status_code < 300, "status": r.status_code, "record": (recs[0] if recs else None), "data": data}

def airtable_update(table, record_id, fields):
    headers = _airtable_headers()
    base = _airtable_base_id()
    if not headers or not base:
        return {"ok": False, "error": "missing_airtable_env"}
    r = requests.patch(_airtable_url(table) + f"/{record_id}", headers=headers, json={"fields": fields}, timeout=20)
    data = r.json()
    return {"ok": r.status_code < 300, "status": r.status_code, "data": data}

def upsert_player_by_telegram_user_id(players_table, telegram_user_id):
    # players.telegram_user_id is the upsert key (locked mapping)
    formula = f"{{telegram_user_id}}='{telegram_user_id}'"
    found = airtable_find_one(players_table, formula)
    if found.get("ok") and found.get("record"):
        return {"ok": True, "action": "found", "record_id": found["record"]["id"]}
    # create minimal
    created = airtable_create(players_table, {"telegram_user_id": str(telegram_user_id)})
    if created.get("ok"):
        return {"ok": True, "action": "created", "record_id": created["data"]["id"]}
    return {"ok": False, "error": created}

@app.get("/__routes")
def __routes():
    return jsonify({
        "ok": True,
        "version": APP_VERSION,
        "routes": sorted([str(r) for r in app.url_map.iter_rules()])
    })

@app.route("/ritual/start", methods=["POST", "OPTIONS"])
def ritual_start():
    """
    Start a ritual attempt.
    IMPORTANT: never return HTTP 500 to the WebApp for "business" failures (Airtable, schema mismatch, etc.).
    If Airtable is unavailable or rejects a field, we still return 200 with a local attempt_id so the ritual can proceed.
    """
    if request.method == "OPTIONS":
        return ("", 204)

    payload = _json()
    telegram_user_id = payload.get("telegram_user_id") or payload.get("user_id") or payload.get("tg_user_id")
    raw_mode = payload.get("mode") or payload.get("rituel_mode") or "rituel_full_v1"
    env = os.getenv("ENV", "PROD")

    if not telegram_user_id:
        return jsonify({"ok": False, "error": "missing_telegram_user_id"}), 400

    # Local attempt id (client-facing) — even if Airtable fails we keep going.
    now = datetime.datetime.utcnow()
    rand = "".join(random.choice("0123456789abcdef") for _ in range(6))
    attempt_id = f"AT-{int(now.timestamp())}-{rand}"

    players_table = os.getenv("AIRTABLE_PLAYERS_TABLE", "players")
    attempts_table = os.getenv("AIRTABLE_ATTEMPTS_TABLE", "rituel_attempts")

    # Normalize mode in a "safe" way: unknown select values can 422 in Airtable.
    # Prefer leaving it empty rather than breaking the ritual.
    mode = raw_mode
    status = payload.get("status") or payload.get("state") or "STARTED"

    # 1) Upsert player (tolerant)
    player_record = None
    try:
        player_record = upsert_player(players_table, str(telegram_user_id))
    except Exception as e:
        logger.exception("ritual_start: player_upsert_failed: %s", e)

    # 2) Create attempt in Airtable (best effort + retry minimal)
    attempt_record_id = None
    airtable_error = None

    if player_record and player_record.get("record_id"):
        started_at = now.isoformat() + "Z"

        # Full fields (may fail if selects don't match in Airtable)
        fields_full = {
            "player": [player_record["record_id"]],
            "started_at": started_at,
            "mode": mode,
            "status": status,
        }

        # Minimal fields (very high chance to pass in Airtable)
        fields_min = {
            "player": [player_record["record_id"]],
            "started_at": started_at,
        }

        try:
            created = airtable_create(attempts_table, fields_full)
            attempt_record_id = created.get("record_id")
        except Exception as e:
            airtable_error = str(e)
            logger.exception("ritual_start: attempt_create_failed (full): %s", e)
            # Retry minimal (drop select fields that often cause 422)
            try:
                created = airtable_create(attempts_table, fields_min)
                attempt_record_id = created.get("record_id")
                airtable_error = None
            except Exception as e2:
                airtable_error = str(e2)
                logger.exception("ritual_start: attempt_create_failed (min): %s", e2)

    # ✅ Always 200 to keep the WebApp flowing.
    res = {
        "ok": True,
        "env": env,
        "attempt_id": attempt_id,               # client-facing id
        "attempt_record_id": attempt_record_id, # Airtable record id (recXXXX) when available
        "player_record_id": (player_record or {}).get("record_id"),
    }
    if airtable_error:
        res["warning"] = "attempt_not_persisted"
        res["warning_detail"] = airtable_error[:500]

    return jsonify(res), 200


@app.route("/ritual/complete", methods=["POST", "OPTIONS"])
def ritual_complete():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = _json()
    telegram_user_id = payload.get("telegram_user_id") or payload.get("user_id") or payload.get("tg_user_id")
    attempt_record_id = payload.get("attempt_record_id") or payload.get("exam_record_id") or payload.get("attempt_id")

    if not telegram_user_id:
        return jsonify({"ok": False, "error": "missing_telegram_user_id"}), 400

    players_table = os.getenv("AIRTABLE_PLAYERS_TABLE", "players")
    attempts_table = os.getenv("AIRTABLE_ATTEMPTS_TABLE", "rituel_attempts")
    payloads_table = os.getenv("AIRTABLE_PAYLOADS_TABLE", "rituel_webapp_payloads")
    answers_table = os.getenv("AIRTABLE_ANSWERS_TABLE", "rituel_answers")
    feedback_table = os.getenv("AIRTABLE_FEEDBACK_TABLE", "rituel_feedback")

    p = upsert_player_by_telegram_user_id(players_table, str(telegram_user_id))
    if not p.get("ok"):
        return jsonify({"ok": False, "error": "player_upsert_failed", "details": p}), 500

    # 1) Log raw payload (always)
    raw_fields = {
        "telegram_user_id": str(telegram_user_id),
        "payload": json.dumps(payload, ensure_ascii=False)[:98000],
        "utc": datetime.now(timezone.utc).isoformat(),
    }
    raw_res = airtable_create(payloads_table, raw_fields)

    # 2) Update attempt if we have its record id
    attempt_update = None
    if attempt_record_id:
        upd = {
            "completed_at": payload.get("completed_at") or datetime.now(timezone.utc).isoformat(),
            "status": payload.get("status") or "COMPLETED",
        }
        # scoring fields (only if provided)
        for k_src, k_dst in [
            ("score_raw", "score_raw"),
            ("score_max", "score_max"),
            ("time_total_seconds", "time_total_seconds"),
            ("result", "result"),
            ("mode", "mode"),
        ]:
            if payload.get(k_src) is not None:
                upd[k_dst] = payload.get(k_src)
        attempt_update = airtable_update(attempts_table, str(attempt_record_id), upd)

    # 3) Insert answers (if provided) — tolerant schema
    answers = payload.get("answers") or payload.get("rituel_answers") or []
    answers_inserted = 0
    if isinstance(answers, list) and attempt_record_id:
        for a in answers[:200]:
            if not isinstance(a, dict):
                continue
            fields = {
                "player": [p["record_id"]],
                "exam": [str(attempt_record_id)],
                "utc": datetime.now(timezone.utc).isoformat(),
            }
            # common answer fields
            for k in ["question_id", "ID_question", "selected_index", "correct_index", "is_correct", "time_ms", "time_seconds"]:
                if a.get(k) is not None:
                    fields[k] = a.get(k)
            res = airtable_create(answers_table, fields)
            if res.get("ok"):
                answers_inserted += 1

    # 4) Insert feedback (if provided)
    fb = payload.get("feedback") or payload.get("rituel_feedback")
    feedback_res = None
    if attempt_record_id and fb:
        fields = {
            "player": [p["record_id"]],
            "exam": [str(attempt_record_id)],
            "utc": datetime.now(timezone.utc).isoformat(),
        }
        if isinstance(fb, dict):
            if fb.get("text"):
                fields["text"] = fb["text"]
            if fb.get("rating") is not None:
                fields["rating"] = fb["rating"]
        else:
            fields["text"] = str(fb)
        feedback_res = airtable_create(feedback_table, fields)

    return jsonify({
        "ok": True,
        "version": APP_VERSION,
        "payload_logged": raw_res.get("ok", False),
        "payload_record": (raw_res.get("data", {}) or {}).get("id"),
        "attempt_updated": (attempt_update or {}).get("ok") if attempt_update else None,
        "answers_inserted": answers_inserted,
        "feedback_logged": feedback_res.get("ok") if feedback_res else None,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Velvet MCP Core listening on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
