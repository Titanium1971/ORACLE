# server.py — Velvet MCP Core (local, propre, souverain)
# -----------------------------------------------------
# - /health avec ping Airtable réel
# - CORS actif
# - /questions/random renvoie des questions prêtes pour le front
# - Tirage réellement aléatoire via champ "Rand" (Airtable)

import os
import json
import random
import re
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request, send_from_directory

APP_ENV = "BETA"  # forced: Airtable env field only supports BETA

app = Flask(__name__, static_folder='webapp', static_url_path='/webapp')

print("🟢 SERVER.PY LOADED - Flask app initialized")

from flask_cors import CORS

CORS(app, resources={r"/*": {"origins": "*"}})

# ================================================================
# Telegram Bot — Webhook mode (Publish via gunicorn)
# ------------------------------------------------
# Goal: Run & Publish behave the same by letting gunicorn serve the webhook.
# - No polling in Publish.
# - The bot handlers come from bot.py (texts/logic stay in one place).
#
# ENV required:
#   TELEGRAM_BOT_TOKEN
# Optional:
#   TELEGRAM_WEBHOOK_SECRET  (recommended)
#
# Routes:
#   POST /telegram/webhook/<secret?>
#   GET  /telegram/webhook/status
#   POST /telegram/webhook/set   (best-effort; needs public HTTPS URL)
# ================================================================
import asyncio
import threading

_TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
_TELEGRAM_SECRET = (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()
_TELEGRAM_APP = None
_TELEGRAM_LOOP = None
_TELEGRAM_LOOP_THREAD = None


def _ensure_event_loop_thread():
    """Start a dedicated asyncio loop in a background thread (one per gunicorn worker)."""
    global _TELEGRAM_LOOP, _TELEGRAM_LOOP_THREAD

    if _TELEGRAM_LOOP and _TELEGRAM_LOOP.is_running():
        return

    _TELEGRAM_LOOP = asyncio.new_event_loop()

    def _runner(loop):
        asyncio.set_event_loop(loop)
        loop.run_forever()

    _TELEGRAM_LOOP_THREAD = threading.Thread(
        target=_runner, args=(_TELEGRAM_LOOP,), name="telegram-webhook-loop", daemon=True
    )
    _TELEGRAM_LOOP_THREAD.start()


async def _init_telegram_app():
    """Initialize python-telegram-bot Application once (handlers imported from bot.py)."""
    global _TELEGRAM_APP

    if _TELEGRAM_APP is not None:
        return _TELEGRAM_APP

    if not _TELEGRAM_TOKEN:
        return None

    # Import handlers (no side effects: bot.py only starts polling under __main__)
    from telegram.ext import Application, CommandHandler, MessageHandler, TypeHandler, filters
    from telegram import Update as TgUpdate

    from bot import start as tg_start
    from bot import whoami as tg_whoami
    from bot import handle_webapp_data as tg_handle_webapp_data
    from bot import debug_any_update as tg_debug_any_update

    app_ = Application.builder().token(_TELEGRAM_TOKEN).build()
    app_.add_handler(CommandHandler("start", tg_start))
    app_.add_handler(CommandHandler("whoami", tg_whoami))
    app_.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, tg_handle_webapp_data))
    app_.add_handler(TypeHandler(TgUpdate, tg_debug_any_update), group=-1)

    await app_.initialize()
    await app_.start()
    _TELEGRAM_APP = app_
    print("🟣 TELEGRAM WEBHOOK READY (application initialized)", flush=True)
    return _TELEGRAM_APP


def _run_coro(coro):
    """Run a coroutine on the dedicated loop and wait for result (sync Flask context)."""
    _ensure_event_loop_thread()
    fut = asyncio.run_coroutine_threadsafe(coro, _TELEGRAM_LOOP)
    return fut.result(timeout=20)


@app.get("/telegram/webhook/status")
def telegram_webhook_status():
    return jsonify({
        "ok": True,
        "token_set": bool(_TELEGRAM_TOKEN),
        "secret_set": bool(_TELEGRAM_SECRET),
        "app_initialized": _TELEGRAM_APP is not None,
    }), 200


@app.post("/telegram/webhook")
@app.post("/telegram/webhook/<secret>")
def telegram_webhook(secret=None):
    # Optional shared secret check (recommended)
    if _TELEGRAM_SECRET:
        if not secret or secret != _TELEGRAM_SECRET:
            return jsonify({"ok": False, "error": "forbidden"}), 403

    if not _TELEGRAM_TOKEN:
        return jsonify({"ok": False, "error": "missing_TELEGRAM_BOT_TOKEN"}), 500
    # Ensure Telegram app is initialized (lazy init on first webhook call)
    global _TELEGRAM_APP
    if _TELEGRAM_APP is None:
        try:
            _TELEGRAM_APP = _run_coro(_init_telegram_app())
        except Exception as e:
            print("🔴 TELEGRAM INIT FAILED:", repr(e), flush=True)
            return jsonify({"ok": False, "error": "telegram_app_init_failed"}), 500


    data = request.get_json(silent=True) or {}
    try:
        tg_app = _run_coro(_init_telegram_app())
        if tg_app is None:
            return jsonify({"ok": False, "error": "telegram_app_init_failed"}), 500

        from telegram import Update as TgUpdate
        update = TgUpdate.de_json(data, tg_app.bot)
        # process_update is async
        _run_coro(tg_app.process_update(update))
        return jsonify({"ok": True}), 200
    except Exception as e:
        print(f"❌ telegram_webhook error: {e}", flush=True)
        return jsonify({"ok": False, "error": "telegram_webhook_exception", "message": str(e)[:300]}), 500


@app.post("/telegram/webhook/set")
def telegram_webhook_set():
    """
    Best-effort webhook setter.
    Builds URL from request.host_url (must be public HTTPS in Publish).
    """
    if not _TELEGRAM_TOKEN:
        return jsonify({"ok": False, "error": "missing_TELEGRAM_BOT_TOKEN"}), 500

    base = request.host_url.rstrip("/")
    path = "/telegram/webhook"
    if _TELEGRAM_SECRET:
        path += f"/{_TELEGRAM_SECRET}"
    webhook_url = base + path

    try:
        # Telegram setWebhook endpoint (no extra deps; use requests)
        r = requests.post(
            f"https://api.telegram.org/bot{_TELEGRAM_TOKEN}/setWebhook",
            json={"url": webhook_url, "drop_pending_updates": False},
            timeout=20,
        )
        return jsonify({
            "ok": r.status_code == 200,
            "status_code": r.status_code,
            "webhook_url": webhook_url,
            "telegram": (r.json() if r.headers.get("content-type","").startswith("application/json") else {"raw": r.text[:300]}),
        }), 200
    except Exception as e:
        return jsonify({"ok": False, "error": "setWebhook_failed", "message": str(e)}), 500


# -----------------------------------------------------
# ✅ Request logger (debug) — traces whether devices hit this backend
# -----------------------------------------------------
@app.before_request
def _log_incoming_request():
    try:
        init_data = request.headers.get("X-Telegram-InitData", "") or ""
        print(
            f"🧭 REQ {request.method} {request.path} | qs={request.query_string.decode('utf-8','ignore')[:200]} | initDataLen={len(init_data)}",
            flush=True
        )
    except Exception:
        pass

APP_VERSION = "v0.9-debug-airtable-errors"

# ============================================================================
#  NOTION CONFIGURATION (for ritual/complete endpoint)
# ============================================================================
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_EXAMS_DB_ID = os.getenv("NOTION_EXAMS_DB_ID")

NOTION_FIELDS = {
    "joueur_id": "Joueur ID",
    "mode": "Mode",
    "score": "Score",
    "statut": "Statut",
    "date": "Date/Heure",
    "time_s": "Temps total (s)",
    "time_mmss": "Temps total (mm:ss)",
    "reponses": "Réponses",
    "commentaires": "Commentaires",
    "version_bot": "Version Bot",
    "profil_joueur": "Profil joueur",
    "nom_utilisateur": "Nom utilisateur",
    "username_telegram": "Username Telegram",
}

NOTION_BASE_URL = "https://api.notion.com/v1"


def get_notion_headers():
    if not NOTION_API_KEY:
        return None
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def format_time_mmss(total_seconds):
    if total_seconds < 0:
        total_seconds = 0
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def compute_statut(score, total_questions, mode):
    if total_questions <= 0:
        return "En cours"
    if mode != "Prod":
        return "En cours"
    seuil = max(1, int(round(total_questions *
                             0.75))) if total_questions > 0 else 12
    return "Admis" if score >= seuil else "Refusé"


def compute_player_profile(score, total_questions, total_time_s):
    if total_questions <= 0:
        return "Oracle en Devenir"
    ratio = score / total_questions
    avg_time = total_time_s / total_questions if total_time_s > 0 else None

    if ratio >= 0.85:
        if avg_time is not None and avg_time <= 5:
            return "Esprit Fulgurant"
        return "Stratège Silencieux"
    elif ratio >= 0.65:
        return "Explorateur Patient"
    elif ratio >= 0.45:
        return "Éclaireur Instinctif"
    return "Oracle en Devenir"


def format_answers_pretty(answers):
    if not isinstance(answers, list):
        return "-"
    lines = []
    for a in answers:
        if not isinstance(a, dict):
            continue
        qid = a.get("question_id") or a.get("ID_question") or "?"

        # Check both choice_letter and selected_index
        choice_letter = a.get("choice_letter")
        if not choice_letter:
            selected_idx = a.get("selected_index")
            if selected_idx is not None:
                choice_letter = chr(65 + int(selected_idx))  # 0->A, 1->B, etc
            else:
                choice_letter = "-"

        is_correct = a.get("is_correct")
        status = (a.get("status") or "").lower()

        if is_correct is True or status == "correct":
            mark = "✅"
        elif status == "timeout":
            mark = "⏳"
        else:
            mark = "❌"

        lines.append(f"{qid} : {choice_letter} {mark}")
    return "\n".join(lines) if lines else "-"


def write_to_notion(payload):
    """Write ritual completion data to Notion"""
    if not NOTION_API_KEY or not NOTION_EXAMS_DB_ID:
        print("⚠️ Notion API key or DB ID not configured")
        return {"ok": False, "error": "notion_not_configured"}

    try:
        # Extract data from payload
        score = payload.get("score") or 0
        total = payload.get("total") or 15
        time_seconds = payload.get("time_total_seconds") or payload.get(
            "time_spent_seconds") or 0
        time_formatted = payload.get("time_formatted") or format_time_mmss(
            time_seconds)
        answers = payload.get("answers") or []
        comment = payload.get("comment_text") or payload.get(
            "feedback_text") or "-"
        telegram_user_id = str(
            payload.get("telegram_user_id") or payload.get("user_id")
            or "unknown")

        # Compute profile and status
        profil = compute_player_profile(score, total, time_seconds)
        statut = compute_statut(score, total, "Prod")
        answers_text = format_answers_pretty(answers)

        now = datetime.now(timezone.utc).isoformat()

        properties = {
            NOTION_FIELDS["joueur_id"]: {
                "title": [{
                    "type": "text",
                    "text": {
                        "content": telegram_user_id
                    }
                }]
            },
            NOTION_FIELDS["mode"]: {
                "select": {
                    "name": "Prod"
                }
            },
            NOTION_FIELDS["score"]: {
                "number": int(score)
            },
            NOTION_FIELDS["statut"]: {
                "select": {
                    "name": statut
                }
            },
            NOTION_FIELDS["date"]: {
                "date": {
                    "start": now
                }
            },
            NOTION_FIELDS["time_s"]: {
                "number": int(time_seconds)
            },
            NOTION_FIELDS["time_mmss"]: {
                "rich_text": [{
                    "type": "text",
                    "text": {
                        "content": time_formatted
                    }
                }]
            },
            NOTION_FIELDS["reponses"]: {
                "rich_text": [{
                    "type": "text",
                    "text": {
                        "content": (answers_text or "-")[:1900]
                    }
                }]
            },
            NOTION_FIELDS["commentaires"]: {
                "rich_text": [{
                    "type": "text",
                    "text": {
                        "content": (comment or "-")[:1900]
                    }
                }]
            },
            NOTION_FIELDS["version_bot"]: {
                "rich_text": [{
                    "type": "text",
                    "text": {
                        "content": "rituel_full_v1_http"
                    }
                }]
            },
            NOTION_FIELDS["profil_joueur"]: {
                "select": {
                    "name": profil
                }
            },
            NOTION_FIELDS["nom_utilisateur"]: {
                "rich_text": [{
                    "type": "text",
                    "text": {
                        "content": "-"
                    }
                }]
            },
            NOTION_FIELDS["username_telegram"]: {
                "rich_text": [{
                    "type": "text",
                    "text": {
                        "content": "-"
                    }
                }]
            },
        }

        url = f"{NOTION_BASE_URL}/pages"
        notion_payload = {
            "parent": {
                "database_id": NOTION_EXAMS_DB_ID
            },
            "properties": properties
        }

        headers = get_notion_headers()
        resp = requests.post(url,
                             headers=headers,
                             json=notion_payload,
                             timeout=20)

        if resp.status_code < 300:
            print(f"✅ Notion page created: {resp.json().get('id')}")
            return {"ok": True, "page_id": resp.json().get("id")}
        else:
            print(f"❌ Notion error {resp.status_code}: {resp.text[:500]}")
            return {"ok": False, "error": resp.text[:500]}

    except Exception as e:
        print(f"❌ Exception writing to Notion: {e}")
        return {"ok": False, "error": str(e)}


# -----------------------------------------------------
# CORS minimal (front local)
# -----------------------------------------------------
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
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


@app.get("/webapp/")
def webapp_index():
    """Serve the Telegram WebApp"""
    return send_from_directory('webapp', 'index.html')


@app.get("/version")
def version():
    return jsonify({"version": APP_VERSION}), 200


@app.get("/ping")
def ping():
    return jsonify({"ok": True, "version": APP_VERSION}), 200


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
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }



def _airtable_base_id(table_name=""):
    """
    Routing des bases Airtable.

    - PROD (défaut) : comportement actuel
      * questions -> AIRTABLE_BASE_ID
      * core (players/attempts/payloads/answers/feedback) -> AIRTABLE_CORE_BASE_ID (si défini)

    - BETA (ENV=BETA) : tout passe par BETA_AIRTABLE_BASE_ID
      * questions -> BETA_AIRTABLE_BASE_ID
      * core -> BETA_AIRTABLE_BASE_ID
    """

    if APP_ENV == "BETA":
        return os.getenv("BETA_AIRTABLE_BASE_ID") or os.getenv("AIRTABLE_BASE_ID")

    # === PROD (comportement actuel) ===
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

    # Si c'est une table de joueurs/tentatives -> base CORE
    if table_name in core_tables:
        core_base = os.getenv("AIRTABLE_CORE_BASE_ID")
        if core_base:
            return core_base

    # Fallback sur base questions (ancien comportement)
    return os.getenv("AIRTABLE_BASE_ID")


def _airtable_url(table):
    base = _airtable_base_id(table)
    return f"https://api.airtable.com/v0/{base}/{table}"



def _core_table_name(prod_env_var: str, default_name: str, beta_env_var: str = "") -> str:
    """Retourne le nom/ID de table à utiliser selon ENV.
    - PROD : prod_env_var (si défini) sinon default_name
    - BETA : beta_env_var (si défini) sinon prod_env_var sinon default_name
    """
    if APP_ENV == "BETA":
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
    r = requests.post(_airtable_url(table),
                      headers=headers,
                      json={"fields": fields},
                      timeout=20)
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
    r = requests.get(_airtable_url(table),
                     headers=headers,
                     params={
                         "filterByFormula": formula,
                         "maxRecords": 1
                     },
                     timeout=20)
    data = r.json()
    recs = data.get("records", []) if isinstance(data, dict) else []
    return {
        "ok": r.status_code < 300,
        "status": r.status_code,
        "record": (recs[0] if recs else None),
        "data": data
    }



def airtable_find_latest(table, formula, sort_field="started_at"):
    """Find most recent record matching formula (best effort).
    Uses Airtable sort query params to pick latest by sort_field desc.
    """
    headers = _airtable_headers()
    base = _airtable_base_id(table)
    if not headers or not base:
        return {"ok": False, "error": "missing_airtable_env"}
    params = {
        "filterByFormula": formula,
        "maxRecords": 1,
        "sort[0][field]": sort_field,
        "sort[0][direction]": "desc",
    }
    r = requests.get(_airtable_url(table), headers=headers, params=params, timeout=20)
    data = r.json()
    recs = data.get("records", []) if isinstance(data, dict) else []
    rec = recs[0] if recs else None
    return {
        "ok": r.status_code < 300,
        "status": r.status_code,
        "record": rec,
        "records": recs,
        "raw": data,
    }


def airtable_update(table, record_id, fields):
    headers = _airtable_headers()
    base = _airtable_base_id(table)
    if not headers or not base:
        return {"ok": False, "error": "missing_airtable_env"}
    r = requests.patch(_airtable_url(table) + f"/{record_id}",
                       headers=headers,
                       json={"fields": fields},
                       timeout=20)
    data = r.json()
    return {"ok": r.status_code < 300, "status": r.status_code, "data": data}


def upsert_player_by_telegram_user_id(players_table, telegram_user_id):
    # players.telegram_user_id is the upsert key (locked mapping)
    formula = f"{{telegram_user_id}}='{telegram_user_id}'"
    found = airtable_find_one(players_table, formula)
    if found.get("ok") and found.get("record"):
        return {
            "ok": True,
            "action": "found",
            "record_id": found["record"]["id"]
        }
    # create minimal
    created = airtable_create(players_table,
                              {"telegram_user_id": str(telegram_user_id)})
    if created.get("ok"):
        return {
            "ok": True,
            "action": "created",
            "record_id": created["data"]["id"]
        }
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
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        print("🔵 DEBUG /ritual/start appelé")

        payload = _json()
        telegram_user_id = payload.get("telegram_user_id") or payload.get(
            "user_id") or payload.get("tg_user_id")
        print(f"🔵 telegram_user_id = {telegram_user_id}")

        if not telegram_user_id:
            return jsonify({
                "ok": False,
                "error": "missing_telegram_user_id"
            }), 400

        players_table = _core_table_name("AIRTABLE_PLAYERS_TABLE", "players", "BETA_AIRTABLE_PLAYERS_TABLE_ID")
        attempts_table = _core_table_name("AIRTABLE_ATTEMPTS_TABLE", "rituel_attempts", "BETA_AIRTABLE_ATTEMPTS_TABLE_ID")
        print(
            f"🔵 players_table = {players_table}, attempts_table = {attempts_table}",
            flush=True)
        print(f"🔵 payload complet = {payload}", flush=True)

        p = upsert_player_by_telegram_user_id(players_table,
                                              str(telegram_user_id))
        if not p.get("ok"):
            return jsonify({
                "ok": False,
                "error": "player_upsert_failed",
                "details": p
            }), 500

        # Translate mode for Airtable (app.js sends "rituel_full_v1" but Airtable expects "PROD" or "TEST")
        raw_mode = payload.get("mode") or payload.get("env") or "BETA"
        if raw_mode in ("rituel_full_v1", "ritual_full_v1", "rituel_v1",
                        "ritual_v1"):
            airtable_mode = "PROD"
        elif raw_mode == "TEST":
            airtable_mode = "TEST"
        else:
            airtable_mode = "PROD"  # fallback

        print(f"🔵 Mode translation: {raw_mode} → {airtable_mode}", flush=True)

        # Create attempt (write only whitelisted raw fields; never computed/system fields)
        fields = {
            "player": [p["record_id"]],
            "started_at": payload.get("started_at") or datetime.now(timezone.utc).isoformat(),
            "mode": airtable_mode,
            # BETA: store environment explicitly if the field exists
            "env": "BETA",
            # If score_max is not provided at start, default to 15 (rituel standard)
            "score_max": int(payload.get("score_max") or payload.get("total") or 15),
            # Human-readable label for debugging (safe if field exists)
            "attempt_label": payload.get("attempt_label") or datetime.now(timezone.utc).strftime("RIT-%Y%m%d-%H%M%S"),
        }
        # optional text mirror if you have one; safe to ignore if field absent
        if payload.get("Players"):
            fields["Players"] = payload.get("Players")

        print(f"🔵 DEBUG - Player record_id créé: {p['record_id']}")
        print(
            f"🔵 DEBUG - Tentative création attempt avec fields: {json.dumps(fields, indent=2)}"
        )

        created = airtable_create(attempts_table, fields)

        # Retry si la table BETA n'a pas le champ "mode"
        if (not created.get("ok")
                and created.get("status") == 422
                and isinstance(created.get("data"), dict)
                and isinstance(created["data"].get("error"), dict)
                and "Unknown field name" in str(created["data"]["error"].get("message", ""))
                and "mode" in str(created["data"]["error"].get("message", ""))):
            fields.pop("mode", None)
            print("🟡 Airtable 422 (mode inconnu) → retry sans 'mode'", flush=True)
            created = airtable_create(attempts_table, fields)

        print(
            f"🔵 DEBUG - Réponse airtable_create: {json.dumps(created, indent=2)}"
        )

        if not created.get("ok"):
            print(f"🔴 ERREUR AIRTABLE COMPLÈTE:")
            print(f"🔴 Status Code: {created.get('status')}")
            print(f"🔴 Data: {json.dumps(created.get('data'), indent=2)}")
            print(f"🔴 Fields envoyés: {json.dumps(fields, indent=2)}")
            return jsonify({
                "ok": False,
                "error": "attempt_create_failed",
                "details": created,
                "fields_sent": fields,
                "airtable_response": created.get("data")
            }), 500

        return jsonify({
            "ok": True,
            "version": APP_VERSION,
            "attempt_id": created["data"]["id"],
            "player_record_id": p["record_id"],
        })

    except Exception as e:
        print(f"🔴 EXCEPTION DANS /ritual/start: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "ok": False,
            "error": "internal_server_error",
            "message": str(e)
        }), 500


@app.route("/ritual/complete", methods=["POST", "OPTIONS"])
def ritual_complete():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = _json()
    try:
        print("🔶 /ritual/complete payload_keys =", sorted(list(payload.keys())))
        if "client_payload" in payload:
            cp = payload.get("client_payload")
            cp_type = type(cp).__name__
            cp_preview = str(cp)
            if len(cp_preview) > 1200:
                cp_preview = cp_preview[:1200] + "…"
            print("🔶 /ritual/complete client_payload_type =", cp_type)
            print("🔶 /ritual/complete client_payload_preview =", cp_preview)
    except Exception as _e:
        print("🔶 /ritual/complete payload_log_error =", repr(_e))

    telegram_user_id = payload.get("telegram_user_id") or payload.get(
        "user_id") or payload.get("tg_user_id")
    attempt_record_id = (
        payload.get("attempt_record_id")
        or payload.get("exam_record_id")
        or payload.get("attempt_id")
        or payload.get("attemptRecordId")
        or payload.get("examRecordId")
        or payload.get("attempt_record")
    )

    if not telegram_user_id:
        return jsonify({"ok": False, "error": "missing_telegram_user_id"}), 400

    players_table = _core_table_name("AIRTABLE_PLAYERS_TABLE", "players", "BETA_AIRTABLE_PLAYERS_TABLE_ID")
    attempts_table = _core_table_name("AIRTABLE_ATTEMPTS_TABLE", "rituel_attempts", "BETA_AIRTABLE_ATTEMPTS_TABLE_ID")
    payloads_table = _core_table_name("AIRTABLE_PAYLOADS_TABLE", "rituel_webapp_payloads", "BETA_AIRTABLE_PAYLOADS_TABLE_ID")
    answers_table = _core_table_name("AIRTABLE_ANSWERS_TABLE", "rituel_answers", "BETA_AIRTABLE_ANSWERS_TABLE_ID")
    feedback_table = _core_table_name("AIRTABLE_FEEDBACK_TABLE", "rituel_feedback", "BETA_AIRTABLE_FEEDBACK_TABLE_ID")

    p = upsert_player_by_telegram_user_id(players_table, str(telegram_user_id))
    if not p.get("ok"):
        return jsonify({
            "ok": False,
            "error": "player_upsert_failed",
            "details": p
        }), 500

    # 1) Log raw payload (always)
    raw_fields = {
        "telegram_user_id": str(telegram_user_id),
        "payload": json.dumps(payload, ensure_ascii=False)[:98000],
        "utc": datetime.now(timezone.utc).isoformat(),
    }
    raw_res = airtable_create(payloads_table, raw_fields)

        # 2) Resolve attempt record id (client may omit it)
    if not attempt_record_id:
        try:
            # Pick the most recent non-completed attempt for this player in BETA.
            formula_parts = [
                f'{{player}}="{telegram_user_id}"',
                '{{env}}="BETA"',
                'OR({completed_at}="", {completed_at}=BLANK())'.replace("{completed_at}", "{completed_at}"),
            ]
            if payload.get("attempt_label"):
                # attempt_label helps disambiguate if multiple attempts exist
                safe_label = str(payload.get("attempt_label")).replace('"', '\"')
                formula_parts.append(f'{{attempt_label}}="{safe_label}"')
            formula = "AND(" + ",".join(formula_parts) + ")"
            found = airtable_find_latest(attempts_table, formula, sort_field="started_at")
            rec = found.get("record") if isinstance(found, dict) else None
            if rec and rec.get("id"):
                attempt_record_id = rec["id"]
        except Exception:
            pass

    # 3) Update attempt row (if we have its record id)
    attempt_update = None
    if attempt_record_id:
        upd = {
            # Always stamp completion time (server-side fallback)
            "completed_at": payload.get("completed_at") or datetime.now(timezone.utc).isoformat(),
            # Keep existing status semantics; if field doesn't exist in Airtable it will 422 and we retry later if needed
            "status": payload.get("status") or "COMPLETED",
            # Mirror env on the attempt row (field exists in BETA schema)
            "env": "BETA",
        }

        # Ensure score_max is always present on completion (BETA schema expects it)
        if payload.get("score_max") is not None:
            upd["score_max"] = payload.get("score_max")
        elif payload.get("total") is not None:
            upd["score_max"] = payload.get("total")
        else:
            upd["score_max"] = 15

        # Optional: attempt_label can be provided by client; if absent, keep existing value
        if payload.get("attempt_label") is not None:
            upd["attempt_label"] = payload.get("attempt_label")
        # scoring fields (only if provided)
        for k_src, k_dst in [
            ("score_raw", "score_raw"),
            ("score_max", "score_max"),
            ("time_total_seconds", "time_total_seconds"),
            ("result", "result"),
        ]:
            if payload.get(k_src) is not None:
                upd[k_dst] = payload.get(k_src)

        # Backward-compatible aliases from WebApp payload
        if upd.get("score_raw") is None and payload.get("score") is not None:
            upd["score_raw"] = payload.get("score")

        if upd.get("time_total_seconds") is None and payload.get("time_spent_seconds") is not None:
            upd["time_total_seconds"] = payload.get("time_spent_seconds")

        # Store full answers + feedback directly on the attempt row (BETA schema fields)
        # We accept several possible payload keys for compatibility.
        # Try to extract answers from top-level payload or nested client_payload (often carries WebApp data)
        client_payload_raw = payload.get("client_payload")
        client_payload = client_payload_raw
        client_payload_parse_error = None

        # client_payload can be a dict already, or a JSON string
        if isinstance(client_payload, str):
            try:
                client_payload = json.loads(client_payload)
            except Exception as e:
                client_payload_parse_error = str(e)

        def _looks_like_answers_list(x):
            """Heuristic: list of dicts with answer-ish keys."""
            if not isinstance(x, list) or not x:
                return False
            if not all(isinstance(it, dict) for it in x):
                return False
            keys = set().union(*(it.keys() for it in x))
            answerish = {"answer", "selected", "choice", "correct", "correct_index", "is_correct", "question_id", "qid", "id_question"}
            return len(keys.intersection(answerish)) >= 1

        def _extract_answers(obj):
            """Shallow extraction from common keys."""
            if isinstance(obj, list) and _looks_like_answers_list(obj):
                return obj
            if not isinstance(obj, dict):
                return None
            cand = (
                obj.get("answers")
                or obj.get("rituel_answers")
                or obj.get("answers_json")
                or obj.get("answersPayload")
                or obj.get("responses")
                or (obj.get("results") or {}).get("answers")
                or (obj.get("data") or {}).get("answers")
                or (obj.get("payload") or {}).get("answers")
            )
            if isinstance(cand, str):
                try:
                    cand = json.loads(cand)
                except Exception:
                    pass
            if isinstance(cand, list):
                return cand
            return None

        def _deep_find_answers(obj, depth=0, max_depth=6):
            """Deep scan for an answers-like list anywhere in nested payload."""
            if depth > max_depth:
                return None
            if _looks_like_answers_list(obj):
                return obj
            if isinstance(obj, dict):
                # Prefer obvious keys first
                for k in ("answers", "responses", "rituel_answers", "answers_json", "answersPayload"):
                    v = obj.get(k)
                    if isinstance(v, str):
                        try:
                            v = json.loads(v)
                        except Exception:
                            pass
                    if _looks_like_answers_list(v):
                        return v
                for v in obj.values():
                    found = _deep_find_answers(v, depth + 1, max_depth)
                    if found is not None:
                        return found
            if isinstance(obj, list):
                for v in obj:
                    found = _deep_find_answers(v, depth + 1, max_depth)
                    if found is not None:
                        return found
            return None

        answers_for_row = (
            _extract_answers(payload)
            or _extract_answers(client_payload)
            or _deep_find_answers(client_payload)
            or _deep_find_answers(payload)
        )

        # If the WebApp doesn't send answers yet, write a diagnostic payload so Airtable is never empty
        if answers_for_row is None:
            diag = {
                "_note": "answers missing in payload",
                "payload_keys": sorted(list(payload.keys())),
                "client_payload_type": type(client_payload_raw).__name__,
            }

            # Provide preview of raw client_payload (truncated) to locate where answers are nested
            if isinstance(client_payload_raw, str):
                diag["client_payload_len"] = len(client_payload_raw)
                diag["client_payload_preview"] = client_payload_raw[:1200]
                if client_payload_parse_error:
                    diag["client_payload_parse_error"] = client_payload_parse_error
            elif isinstance(client_payload_raw, dict):
                diag["client_payload_keys"] = sorted(list(client_payload_raw.keys()))
            else:
                diag["client_payload_value"] = str(client_payload_raw)[:300]

            # If parsed client_payload is a dict, include its keys too
            if isinstance(client_payload, dict):
                diag["client_payload_parsed_keys"] = sorted(list(client_payload.keys()))

            answers_for_row = diag
# Format answers_json for ergonomic reading in Airtable:
        # - add question number (q: 1..N)
        # - keep only the most useful fields when possible
        if answers_for_row is not None:
            def _idx_to_letter(x):
                try:
                    xi = int(x)
                    return ["A","B","C","D"][xi] if 0 <= xi <= 3 else None
                except Exception:
                    return None

            def _normalize_answer_item(a, qn):
                if not isinstance(a, dict):
                    return {"q": qn, "raw": a}
                qid = a.get("question_id") or a.get("qid") or a.get("id_question") or a.get("questionId") or a.get("id")
                ans = (
                    a.get("answer") or a.get("selected") or a.get("user_answer") or a.get("choice")
                    or a.get("selected_option") or a.get("selected_letter") or a.get("userChoice")
                )
                if ans is None:
                    ans = a.get("selected_index") if "selected_index" in a else (a.get("answer_index") if "answer_index" in a else a.get("selectedIndex"))
                ans_letter = ans.strip().upper() if isinstance(ans, str) and ans.strip().upper() in ("A","B","C","D") else _idx_to_letter(ans)
                corr = (
                    a.get("correct") or a.get("correct_answer") or a.get("correctOption")
                    or a.get("correct_letter") or a.get("correctLetter")
                )
                if corr is None:
                    corr = a.get("correct_index") if "correct_index" in a else (a.get("correctIndex") if "correctIndex" in a else a.get("answer_correct_index"))
                corr_letter = corr.strip().upper() if isinstance(corr, str) and corr.strip().upper() in ("A","B","C","D") else _idx_to_letter(corr)
                is_corr = None
                for k in ("is_correct","isCorrect","correct_flag","correctFlag","ok"):
                    if k in a:
                        is_corr = a.get(k)
                        break
                if isinstance(is_corr, str):
                    if is_corr.lower() in ("true","1","yes","ok"):
                        is_corr = True
                    elif is_corr.lower() in ("false","0","no"):
                        is_corr = False
                if is_corr is None and ans_letter and corr_letter:
                    is_corr = (ans_letter == corr_letter)
                out = {"q": qn, "answer": ans_letter, "correct": corr_letter, "is_correct": is_corr}
                if qid is not None:
                    out["question_id"] = qid
                if out.get("answer") is None and out.get("correct") is None and out.get("is_correct") is None:
                    out["raw_keys"] = sorted(list(a.keys()))
                    out["raw_preview"] = {k: a.get(k) for k in list(a.keys())[:12]}
                return out

            try:
                formatted = []
                if isinstance(answers_for_row, list):
                    for i, a in enumerate(answers_for_row, start=1):
                        if isinstance(a, dict):
                            formatted.append(_normalize_answer_item(a, i))
                        else:
                            formatted.append({"q": i, "value": a})
                    answers_json_val = formatted
                else:
                    # If it's already a JSON string or dict, store as-is (best effort).
                    answers_json_val = answers_for_row

                upd["answers_json"] = json.dumps(
                    answers_json_val,
                    ensure_ascii=False,
                    indent=2
                )[:98000]
            except Exception:
                upd["answers_json"] = str(answers_for_row)[:98000]

        # Always write feedback_text (empty string if none)
        fb_text = payload.get("feedback_text") or payload.get("comment_text")
        if fb_text is None and isinstance(payload.get("feedback"), dict):
            fb_text = payload["feedback"].get("text")
        if fb_text is None:
            fb_text = ""
        upd["feedback_text"] = str(fb_text)[:1900]

        # Translate mode for Airtable
        if payload.get("mode") is not None:
            raw_mode = payload.get("mode")
            if raw_mode in ("rituel_full_v1", "ritual_full_v1", "rituel_v1",
                            "ritual_v1"):
                upd["mode"] = "PROD"
            elif raw_mode == "TEST":
                upd["mode"] = "TEST"
            else:
                upd["mode"] = "PROD"

        attempt_update = airtable_update(attempts_table, str(attempt_record_id), upd)

        # If BETA table is missing some fields, retry by removing unknown fields (max 5 attempts)
        tries = 0
        while attempt_update and (not attempt_update.get("ok")) and attempt_update.get("status") == 422 and tries < 5:
            tries += 1
            msg = ""
            try:
                msg = ((attempt_update.get("data") or {}).get("error") or {}).get("message") or ""
            except Exception:
                msg = ""
            if "Unknown field name" not in msg:
                break
            # Extract field name between quotes: Unknown field name: "xxx"
            m_uf = re.search(r'Unknown field name:\s*\"([^\"]+)\"', msg)
            if not m_uf:
                break
            bad_field = m_uf.group(1)
            if bad_field in upd:
                upd.pop(bad_field, None)
                print(f"🟡 Airtable 422 (unknown field '{bad_field}') → retry sans ce champ", flush=True)
                attempt_update = airtable_update(attempts_table, str(attempt_record_id), upd)
            else:
                break

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
            for k in [
                    "question_id", "ID_question", "selected_index",
                    "correct_index", "is_correct", "time_ms", "time_seconds"
            ]:
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

    # 5) ✅ WRITE TO NOTION (new!)
    notion_res = None
    try:
        notion_res = write_to_notion(payload)
        if notion_res.get("ok"):
            print(
                f"✅ NOTION WRITE SUCCESS: page_id={notion_res.get('page_id')}")
        else:
            print(f"⚠️ NOTION WRITE FAILED: {notion_res.get('error')}")
    except Exception as e:
        print(f"❌ NOTION WRITE EXCEPTION: {e}")

    return jsonify({
        "ok":
        True,
        "version":
        APP_VERSION,
        "payload_logged":
        raw_res.get("ok", False),
        "payload_record": (raw_res.get("data", {}) or {}).get("id"),
        "attempt_updated":
        (attempt_update or {}).get("ok") if attempt_update else None,
        "answers_inserted":
        answers_inserted,
        "feedback_logged":
        feedback_res.get("ok") if feedback_res else None,
        "notion_written":
        notion_res.get("ok") if notion_res else False,
    })


if __name__ == "__main__":
    # -----------------------------------------------------
    # Entrypoint local (DEV ONLY)
    # -----------------------------------------------------
    # En environnement Publish/WSGI (gunicorn), ce bloc n'est jamais exécuté.
    # Pour éviter toute confusion et supprimer l'avertissement "development server",
    # le lancement via `python3 server.py` est désactivé par défaut.
    #
    # Pour lancer en local :
    #   RUN_LOCAL_SERVER=1 PORT=5000 python3 server.py
    #
    if os.getenv("RUN_LOCAL_SERVER",
                 "").strip() not in ("1", "true", "TRUE", "yes", "YES"):
        print(
            "ℹ️ server.py: dev server désactivé (set RUN_LOCAL_SERVER=1 pour lancer en local)."
        )
        raise SystemExit(0)

    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Velvet MCP Core listening on port {port}")
    # use_reloader=False évite un double lancement (et donc des doubles logs / ports déjà utilisés)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
