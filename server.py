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
from datetime import datetime, timezone, timedelta

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

APP_VERSION = "v1.4.2-anti-repeat-15-fix-2026-01-16"

# Airtable single-select choices (players_beta.qualified_via)
QUALIFIED_VIA_CHOICE_MAP = {
    "A": "Régularité Velvet (3 rituels)",
    "B": "Excellence Accélérée (2 rituels)",
    "C": "Rituel Parfait (15/15)",
}

def _map_qualified_via_choice(via_code: str) -> str:
    """Map internal A/B/C codes to Airtable single-select choice names."""
    v = (via_code or "").strip().upper()
    return QUALIFIED_VIA_CHOICE_MAP.get(v, (via_code or ""))


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
        # Score: prefer explicit score_raw/score_max from backend payloads, fallback to legacy keys.
        score = payload.get("score_raw")
        if score is None:
            score = payload.get("score")
        if score is None:
            score = payload.get("final_score")
        if score is None:
            score = 0

        total = payload.get("score_max")
        if total is None:
            total = payload.get("total")
        if total is None:
            total = 15

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
@app.route("/questions/random", methods=["GET"])
def questions_random():
    """Return random questions.

    Anti-repetition (BETA only): if telegram_user_id is provided, we try to avoid showing
    identical/similar questions to the same player during their first 15 completed rituals.

    Similarity rule (best-effort, lightweight):
      - block exact repeats by ID_question
      - block very similar question text
      - block moderately similar question text when the correct answer text matches

    This is designed to be fail-open: if anything goes wrong, we return questions normally.
    """

    count = int(request.args.get("count", 15))
    tid = request.args.get("telegram_user_id") or request.args.get("tid")

    # -------------------------
    # Anti-repeat: build history
    # -------------------------
    anti_repeat_enabled = True
    seen_question_ids = set()
    history_norm = []  # list of (q_norm, a_norm)

    def _norm(s: str) -> str:
        if not s:
            return ""
        s = str(s)
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        s = s.lower().strip()
        s = re.sub(r"[^a-z0-9\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _sim(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return difflib.SequenceMatcher(None, a, b).ratio()

    # Only try to anti-repeat when we have a telegram_user_id and we can reach the BETA base.
    # If not, we keep behavior identical to the previous version.
    if tid:
        try:
            beta_base_id = os.getenv("BETA_AIRTABLE_BASE_ID")
            beta_players_table = os.getenv("BETA_AIRTABLE_PLAYERS_TABLE_ID")
            beta_attempts_table = os.getenv("BETA_AIRTABLE_ATTEMPTS_TABLE_ID")

            if beta_base_id and beta_players_table and beta_attempts_table:
                headers = {
                    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
                    "Content-Type": "application/json",
                }

                # 1) Resolve player record by telegram_user_id
                players_url = f"https://api.airtable.com/v0/{beta_base_id}/{beta_players_table}"
                pr = requests.get(
                    players_url,
                    headers=headers,
                    params={
                        "maxRecords": 1,
                        "filterByFormula": f'{{telegram_user_id}}="{tid}"',
                    },
                    timeout=20,
                )

                player_rec_id = None
                if pr.status_code == 200:
                    recs = pr.json().get("records", [])
                    if recs:
                        player_rec_id = recs[0].get("id")

                if player_rec_id:
                    # 2) Pull up to 15 latest completed attempts for that player
                    attempts_url = f"https://api.airtable.com/v0/{beta_base_id}/{beta_attempts_table}"
                    formula = f'FIND("{player_rec_id}", ARRAYJOIN({{player}}))'

                    ar = requests.get(
                        attempts_url,
                        headers=headers,
                        params={
                            "maxRecords": 15,
                            "filterByFormula": formula,
                            "sort[0][field]": "completed_at",
                            "sort[0][direction]": "desc",
                        },
                        timeout=20,
                    )

                    completed = []
                    if ar.status_code == 200:
                        for rec in ar.json().get("records", []):
                            fields = rec.get("fields", {})
                            if fields.get("completed_at"):
                                completed.append(fields)

                    # If the player already completed >= 15 rituals, anti-repeat is disabled (as requested)
                    if len(completed) >= 15:
                        anti_repeat_enabled = False

                    # Build seen IDs + optional similarity memory from answers_json
                    if anti_repeat_enabled:
                        for fields in completed:
                            raw = fields.get("answers_json")
                            if not raw:
                                continue
                            try:
                                parsed = json.loads(raw)
                            except Exception:
                                continue

                            # answers_json is usually a list of answer dicts
                            items = []
                            if isinstance(parsed, list):
                                items = parsed
                            elif isinstance(parsed, dict):
                                if isinstance(parsed.get("answers"), list):
                                    items = parsed.get("answers")

                            for a in items:
                                if not isinstance(a, dict):
                                    continue
                                qid = a.get("question_id") or a.get("id")
                                if qid:
                                    seen_question_ids.add(str(qid))

                                qt = a.get("question_text") or a.get("question")
                                ca = a.get("correct_answer_text")
                                qn = _norm(qt)
                                an = _norm(ca)
                                if qn:
                                    history_norm.append((qn, an))

        except Exception:
            # fail-open: never block /questions/random because of anti-repeat
            anti_repeat_enabled = True
            seen_question_ids = set()
            history_norm = []

    # -------------------------
    # Fetch random candidates (same behavior as before)
    # -------------------------
    threshold = random.random()

    url = f"https://api.airtable.com/v0/{os.getenv('AIRTABLE_BASE_ID','')}/{os.getenv('AIRTABLE_TABLE_ID','')}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json",
    }

    # Fetch more than needed, then filter locally (avoids huge Airtable formulas)
    chunk = max(120, min(240, count * 12))

    params = {
        "sort[0][field]": "Rand",
        "sort[0][direction]": "asc",
        "maxRecords": chunk,
        "filterByFormula": f"{{Rand}} >= {threshold}",
    }

    r1 = requests.get(url, headers=headers, params=params, timeout=20)
    records1 = r1.json().get("records", []) if r1.status_code == 200 else []

    # Wrap around if not enough
    records2 = []
    if len(records1) < chunk:
        params2 = {
            "sort[0][field]": "Rand",
            "sort[0][direction]": "asc",
            "maxRecords": (chunk - len(records1)),
            "filterByFormula": f"{{Rand}} < {threshold}",
        }
        r2 = requests.get(url, headers=headers, params=params2, timeout=20)
        records2 = r2.json().get("records", []) if r2.status_code == 200 else []

    candidates = records1 + records2

    def _extract_correct_answer(fields: dict) -> str:
        opts = fields.get("Options")
        if not opts:
            return ""
        try:
            arr = json.loads(opts) if isinstance(opts, str) else opts
            if not isinstance(arr, list):
                return ""
        except Exception:
            return ""
        try:
            ci = int(fields.get("Correct_index"))
        except Exception:
            return ""
        if 0 <= ci < len(arr):
            return str(arr[ci])
        return ""

    # -------------------------
    # Local filtering
    # -------------------------
    picked = []
    picked_ids = set()

    for rec in candidates:
        fields = rec.get("fields", {})
        qid = fields.get("ID_question")
        if not qid:
            continue
        qid = str(qid)

        # Unique in the returned set
        if qid in picked_ids:
            continue

        if anti_repeat_enabled and qid in seen_question_ids:
            continue

        q_text = fields.get("Question", "")
        ans_text = _extract_correct_answer(fields)
        qn = _norm(q_text)
        an = _norm(ans_text)

        # Similarity filtering only if we have a history of texts
        if anti_repeat_enabled and history_norm and qn:
            too_similar = False
            for (hq, ha) in history_norm:
                if not hq:
                    continue
                s = _sim(qn, hq)
                if s >= 0.92:
                    too_similar = True
                    break
                if an and ha and an == ha and s >= 0.86:
                    too_similar = True
                    break
            if too_similar:
                continue

        picked.append(rec)
        picked_ids.add(qid)
        if len(picked) >= count:
            break

    # Fail-open: if we could not pick enough, return unfiltered picks from candidates
    if len(picked) < count:
        for rec in candidates:
            fields = rec.get("fields", {})
            qid = fields.get("ID_question")
            if not qid:
                continue
            qid = str(qid)
            if qid in picked_ids:
                continue
            picked.append(rec)
            picked_ids.add(qid)
            if len(picked) >= count:
                break

    mapped = []
    for rec in picked[:count]:
        fields = rec.get("fields", {})
        mapped.append(
            {
                "id": fields.get("ID_question") or rec.get("id"),
                "question": fields.get("Question"),
                "options": json.loads(fields.get("Options", "[]"))
                if fields.get("Options")
                else [],
                "correct_index": fields.get("Correct_index"),
                "explanation": fields.get("Explication"),
                "level": fields.get("Niveau"),
                "domain": fields.get("Domaine"),
            }
        )

    return jsonify({"ok": True, "questions": mapped})

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


def airtable_list(table, formula, sort_field="completed_at", direction="desc", max_records=10):
    """List Airtable records matching a formula (best effort).

    Notes:
    - Uses filterByFormula + sort to fetch a small window of recent records.
    - Designed for audit/qualification logic (not pagination).
    """
    headers = _airtable_headers()
    base = _airtable_base_id(table)
    if not headers or not base:
        return {"ok": False, "error": "missing_airtable_env"}

    params = {
        "filterByFormula": formula,
        "maxRecords": int(max_records or 10),
    }
    if sort_field:
        params["sort[0][field]"] = sort_field
        params["sort[0][direction]"] = (direction or "desc")

    r = requests.get(_airtable_url(table), headers=headers, params=params, timeout=20)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    recs = data.get("records", []) if isinstance(data, dict) else []
    return {
        "ok": r.status_code < 300,
        "status": r.status_code,
        "records": recs,
        "raw": data,
    }


def _safe_int(x, default=None):
    try:
        if x is None or x == "":
            return default
        return int(float(x))
    except Exception:
        return default


def _beta_eval_from_attempt_fields(fields: dict):
    """Extract only what we need for beta qualification from an attempt fields dict."""
    return {
        "score_raw": _safe_int(fields.get("score_raw"), None),
        "score_max": _safe_int(fields.get("score_max"), None),
        "time_total_seconds": _safe_int(fields.get("time_total_seconds"), None),
        "is_free": bool(fields.get("is_free")),
        "completed_at": fields.get("completed_at") or fields.get("started_at"),
    }


def evaluate_beta_qualification(attempts_table: str, telegram_user_id: str, current_attempt: dict = None):
    """Compute beta qualification (A/B/C) from COMPLETED BETA attempts.

    Rules (locked by user):
    - All paths are evaluated on FREE attempts only (is_free = true) during the trial phase.
    - Voie C: any ritual at 15/15 (no time constraint)
    - Voie B: the 2 BEST free rituals (not the last 2), each >=12/15 AND <= 6 minutes
    - Voie A: the 3 free rituals, average >=8/15 AND each < 7 minutes
    """
    tid = str(telegram_user_id)
    safe_tid = tid.replace('"', '\\"')

    # player is a link field -> it exposes the linked record's primary field value (telegram_user_id)
    # NOTE: Airtable formula fields must use single braces: {env}, {status}, {is_free}.
    # Using double braces would make the formula invalid and return no records.
    formula = (
        'AND('
        f'FIND("{safe_tid}", ARRAYJOIN({{player}})), '
        '{env}="BETA", '
        '{status}="COMPLETED", '
        '{is_free}=TRUE()'
        ')'
    )

    res = airtable_list(attempts_table, formula, sort_field="completed_at", direction="desc", max_records=10)
    recs = res.get("records", []) if res.get("ok") else []

    attempts = []
    seen_ids = set()
    for rec in recs:
        rid = rec.get("id")
        if rid:
            seen_ids.add(rid)
        fields = rec.get("fields") or {}
        attempts.append(_beta_eval_from_attempt_fields(fields))

    # Ensure current attempt is considered even if Airtable hasn't surfaced it yet.
    if isinstance(current_attempt, dict):
        cur_id = current_attempt.get("id")
        cur_fields = current_attempt.get("fields") or {}
        # Only consider it for qualification if it's a FREE attempt.
        if bool(cur_fields.get("is_free")):
            if cur_id and cur_id not in seen_ids:
                attempts.insert(0, _beta_eval_from_attempt_fields(cur_fields))
            elif not cur_id:
                attempts.insert(0, _beta_eval_from_attempt_fields(cur_fields))

    def _score(a):
        return a.get("score_raw") if a else None

    def _time(a):
        return a.get("time_total_seconds") if a else None

    # Safety: we only evaluate FREE attempts.
    attempts = [a for a in attempts if a.get("is_free")]

    # --- Voie C ---
    for a in attempts:
        if _score(a) == 15:
            return {"qualified": True, "via": "C"}

    # --- Voie B (2 meilleurs rituels gratuits) ---
    # Filter by time constraint first, then rank by score desc, time asc.
    b_candidates = [a for a in attempts if _time(a) is not None and _time(a) <= 360 and _score(a) is not None]
    b_candidates.sort(key=lambda x: (-_score(x), _time(x)))
    best2 = b_candidates[:2]
    if len(best2) == 2 and all((_score(a) >= 12) for a in best2):
        return {"qualified": True, "via": "B"}

    # --- Voie A ---
    last3 = attempts[:3]
    if len(last3) == 3:
        scores = [s for s in (_score(x) for x in last3) if s is not None]
        if len(scores) == 3:
            avg = sum(scores) / 3.0
            ok_time = all((_time(x) is not None and _time(x) < 420) for x in last3)
            if ok_time and avg >= 8.0:
                return {"qualified": True, "via": "A"}

    return {"qualified": False, "via": None}


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




def _merge_application_fields(source_fields: dict, target_fields: dict) -> dict:
    """Copy only safe 'application' fields from the form record into the target player.
    Never overwrites non-empty target fields.
    """
    SAFE_FIELDS = [
        "email",
        "first_name",
        "last_name",
        "phone",
        "motivation_text",
        "entry_channel",
        "cultural_self_positioning",
    ]
    out = {}
    for k in SAFE_FIELDS:
        sv = source_fields.get(k)
        tv = target_fields.get(k)
        if (tv is None or str(tv).strip() == "") and (sv is not None and str(sv).strip() != ""):
            out[k] = sv
    return out


def link_player_by_token(players_table, token, telegram_user_id, telegram_username=None):
    """Hard rule: 1 telegram_user_id == 1 player record.

    If a form-created record (status=APPLIED) is found by link_token *and* a Telegram record already
    exists for telegram_user_id, we MERGE the application fields into the existing Telegram record
    and neutralize the form record (clear link_token), instead of creating duplicates.

    Returns:
      - {ok: True, action: 'linked', record_id: 'rec...'} when the canonical player record is chosen
      - {ok: True, skipped: True} when no token
      - {ok: False, error: 'link_token_not_found'} if token not found
      - {ok: False, error: 'link_token_already_linked'} if token linked to another tg id
    """
    token = (token or "").strip()
    if not token:
        return {"ok": True, "skipped": True}

    # 1) Find the form record by token
    formula = f"{{link_token}}='{token}'"
    found = airtable_find_one(players_table, formula)
    if not found.get("ok"):
        return {"ok": False, "error": "link_token_lookup_failed", "details": found}

    form_rec = found.get("record")
    if not form_rec:
        return {"ok": False, "error": "link_token_not_found"}

    form_fields = (form_rec.get("fields") or {})
    existing_tg_on_form = str(form_fields.get("telegram_user_id") or "").strip()

    # Token already linked to another Telegram id -> conflict
    if existing_tg_on_form and existing_tg_on_form != str(telegram_user_id):
        return {"ok": False, "error": "link_token_already_linked", "record_id": form_rec.get("id")}

    # 2) Find the canonical Telegram record by telegram_user_id (if it exists)
    tg_formula = f"{{telegram_user_id}}='{str(telegram_user_id)}'"
    tg_found = airtable_find_one(players_table, tg_formula)
    tg_rec = tg_found.get("record") if tg_found.get("ok") else None

    # 3) If a Telegram record exists and it's different from the form record -> merge INTO Telegram record
    if tg_rec and tg_rec.get("id") != form_rec.get("id"):
        tg_fields = (tg_rec.get("fields") or {})
        upd = _merge_application_fields(form_fields, tg_fields)

        # Always ensure identity fields on canonical record
        upd["telegram_user_id"] = str(telegram_user_id)
        if telegram_username:
            upd["telegram_username"] = str(telegram_username)
        # Best effort: set ACTIVE if option exists
        upd["status"] = "ACTIVE"
        # Keep token for audit (optional)
        upd["link_token"] = token

        res = airtable_update(players_table, tg_rec["id"], upd)
        if not res.get("ok"):
            return {"ok": False, "error": "link_token_merge_update_failed", "details": res}

        # Neutralize form record to prevent reuse and to avoid duplicates (no telegram_user_id set here)
        try:
            airtable_update(players_table, form_rec["id"], {"link_token": ""})
        except Exception:
            pass

        return {"ok": True, "action": "merged_into_existing", "record_id": tg_rec["id"]}

    # 4) No existing Telegram record -> upgrade the form record into the canonical player
    upd = {"telegram_user_id": str(telegram_user_id), "status": "ACTIVE"}
    if telegram_username:
        upd["telegram_username"] = str(telegram_username)

    res = airtable_update(players_table, form_rec["id"], upd)
    if res.get("ok"):
        return {"ok": True, "action": "linked", "record_id": form_rec["id"]}
    return {"ok": False, "error": "link_token_update_failed", "details": res}


def _normalize_telegram_username(u: str) -> str:
    """Normalize telegram username to maximize matching stability.
    - removes leading '@'
    - lowercases
    - strips whitespace
    """
    if u is None:
        return ""
    u = str(u).strip()
    if u.startswith("@"):
        u = u[1:]
    u = u.strip().lower()
    u = re.sub(r"\s+", "", u)
    return u


def link_form_player_by_telegram_username(players_table, telegram_user_id, telegram_username):
    """Best-effort link:
    If a player record exists with matching telegram_username but missing telegram_user_id,
    upgrade it by writing telegram_user_id (and setting status ACTIVE when possible).

    This prevents duplicates when the form creates the player first and Telegram arrives later.
    """
    try:
        uname = _normalize_telegram_username(telegram_username)
        if not uname:
            return {"ok": True, "skipped": True, "reason": "missing_username"}

        # Look for a "form" player: same username, no telegram_user_id yet
        safe_uname = uname.replace("'", "\\'")
        formula = (
            "AND("
            "OR({telegram_user_id}='', {telegram_user_id}=BLANK()),"
            f"LOWER({{telegram_username}})='{safe_uname}'"
            ")"
        )
        found = airtable_find_one(players_table, formula)
        rec = found.get("record") if found.get("ok") else None
        if not rec:
            return {"ok": True, "skipped": True, "reason": "no_form_match"}

        upd = {
            "telegram_user_id": str(telegram_user_id),
            # Keep username normalized to stabilize future matches
            "telegram_username": uname,
            # Best effort: set ACTIVE (safe even if field doesn't exist -> will 422 but we don't want to block)
            "status": "ACTIVE",
        }

        res = airtable_update(players_table, rec["id"], upd)

        if res.get("ok"):
            return {"ok": True, "action": "linked_by_username", "record_id": rec["id"]}

        # If "status" field doesn't exist, retry without it (do not block the flow)
        try:
            msg = ""
            if isinstance(res.get("data"), dict):
                err = res["data"].get("error")
                if isinstance(err, dict):
                    msg = str(err.get("message") or "")
            if "Unknown field name" in msg and "status" in msg:
                upd.pop("status", None)
                res2 = airtable_update(players_table, rec["id"], upd)
                if res2.get("ok"):
                    return {"ok": True, "action": "linked_by_username", "record_id": rec["id"]}
                return {"ok": False, "error": "link_by_username_update_failed", "details": res2}
        except Exception:
            pass

        return {"ok": False, "error": "link_by_username_update_failed", "details": res}
    except Exception as e:
        print("🟠 link_by_username_exception =", repr(e))
        return {"ok": False, "error": "link_by_username_exception", "details": str(e)}

def maybe_update_player_username(players_table, player_record_id, telegram_username):
    """Best-effort: write telegram_username on every interaction (can change).
    Never blocks the ritual flow.
    """
    try:
        if not telegram_username:
            return {"ok": True, "skipped": True}
        fields = {"telegram_username": str(telegram_username)}
        res = airtable_update(players_table, str(player_record_id), fields)
        if not res.get("ok"):
            print("🟠 username_update_failed =", res)
        else:
            print("🟢 username_updated =", telegram_username)
        return res
    except Exception as e:
        print("🟠 username_update_exception =", repr(e))
        return {"ok": False, "error": str(e)}


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

        start_token = (payload.get("link_token") or payload.get("start_param") or payload.get("start") or payload.get("token") or "").strip()
        p = None
        if start_token:
            bind = link_player_by_token(
                players_table,
                start_token,
                str(telegram_user_id),
                payload.get("telegram_username") or payload.get("telegramUsername"),
            )
            if bind.get("ok") and bind.get("action") in ("linked", "merged_into_existing"):
                p = {"ok": True, "action": "linked", "record_id": bind.get("record_id")}
            elif (not bind.get("ok")) and bind.get("error") == "link_token_already_linked":
                return jsonify({"ok": False, "error": "link_token_already_linked"}), 409
            # if token not found or lookup failed, we silently fallback to upsert by telegram_user_id
        
        if not p:
            # ✅ Option A: if the player was created by the form first, link it now using telegram_username
            try:
                tg_un = payload.get("telegram_username") or payload.get("telegramUsername")
                link_res = link_form_player_by_telegram_username(players_table, str(telegram_user_id), tg_un)
                if link_res.get("ok") and link_res.get("action") == "linked_by_username":
                    p = {"ok": True, "action": "linked_by_username", "record_id": link_res.get("record_id")}
            except Exception as _e:
                print("🟠 link_by_username (ritual_start) failed:", repr(_e), flush=True)

            p = upsert_player_by_telegram_user_id(players_table, str(telegram_user_id))
            if not p.get("ok"):
                return jsonify({
                    "ok": False,
                    "error": "player_upsert_failed",
                    "details": p
                }), 500

        # ✅ Update telegram_username if provided (can change over time)
        maybe_update_player_username(players_table, p.get("record_id"), payload.get("telegram_username") or payload.get("telegramUsername"))




        # ===== Access gate (Option B) =====
        # Source of truth: beta_gate_status + beta_access_until (ACTIVE window),
        # else free_rituals_remaining (trial), else blocked.
        apply_free_gate = False
        remaining = 0
        used = 0
        active_attempt = ""

        try:
            _f = f"{{telegram_user_id}}='{str(telegram_user_id)}'"
            found_player = airtable_find_one(players_table, _f)
            player_record = found_player.get("record") if found_player.get("ok") else None
        except Exception as _e:
            player_record = None
            print("🔴 access_gate: failed to fetch player record:", repr(_e), flush=True)

        player_fields = (player_record or {}).get("fields") or {}
        active_attempt = str(player_fields.get("active_attempt_label") or "").strip()

        def _parse_iso(_s):
            if not _s:
                return None
            try:
                _s = str(_s)
                if _s.endswith("Z"):
                    _s = _s[:-1] + "+00:00"
                return datetime.fromisoformat(_s)
            except Exception:
                return None

        # Idempotence / active lock: if an attempt is already active, return it
        if active_attempt:
            print(f"🟠 access_gate: active_attempt_label present → idempotent return {active_attempt}", flush=True)
            return jsonify({
                "ok": True,
                "version": APP_VERSION,
                "attempt_id": active_attempt,
                "player_record_id": p["record_id"],
                "idempotent": True
            }), 200

        beta_gate_status = str(player_fields.get("beta_gate_status") or "").strip()
        beta_access_until_raw = player_fields.get("beta_access_until")
        beta_until_dt = _parse_iso(beta_access_until_raw)
        beta_cycles_used = int(player_fields.get("beta_cycles_used") or 0)
        now_dt = datetime.now(timezone.utc)

        # ===== Auto-renew (15 days) up to 3 cycles =====
        # Rule: if beta_gate_status is ACTIVE but beta_access_until is in the past,
        # then on next /ritual/start we extend +15 days IF beta_cycles_used < 3.
        # If beta_cycles_used >= 3, we mark EXPIRED and block.
        beta_renewed = False
        if beta_gate_status == "ACTIVE" and beta_until_dt and beta_until_dt <= now_dt:
            if beta_cycles_used < 3:
                # Backfill: if cycles_used is 0 while ACTIVE, assume current cycle is 1.
                current_cycles = beta_cycles_used if beta_cycles_used > 0 else 1
                new_cycles = current_cycles + 1
                new_until_dt = now_dt + timedelta(days=15)
                upd = {
                    "beta_gate_status": "ACTIVE",
                    "beta_cycles_used": new_cycles,
                    "beta_access_until": new_until_dt.isoformat(),
                }
                try:
                    res = airtable_update(players_table, p["record_id"], upd)
                    if res.get("ok"):
                        beta_cycles_used = new_cycles
                        beta_until_dt = new_until_dt
                        beta_renewed = True
                        print(f"🟢 beta_auto_renew: +15d (cycle {new_cycles}/3)", flush=True)
                    else:
                        print("🟠 beta_auto_renew: update failed", res, flush=True)
                except Exception as _e:
                    print("🟠 beta_auto_renew: exception", repr(_e), flush=True)
            else:
                try:
                    airtable_update(players_table, p["record_id"], {"beta_gate_status": "EXPIRED"})
                except Exception as _e:
                    print("🟠 beta_expire: update failed", repr(_e), flush=True)
                return jsonify({
                    "ok": False,
                    "error": "beta_expired",
                    "player_record_id": p["record_id"],
                }), 403

        # STRICT rule: beta active ONLY if beta_gate_status=ACTIVE AND beta_access_until is in the future.
        is_beta_active = bool(beta_until_dt and beta_until_dt > now_dt and beta_gate_status == "ACTIVE")

        if not is_beta_active:
            apply_free_gate = True
            remaining = int(player_fields.get("free_rituals_remaining") or 0)
            used = int(player_fields.get("free_rituals_used") or 0)

            # Backfill defaults for first-time players missing new fields
            backfill = {}
            if "free_rituals_remaining" not in player_fields:
                remaining = 3
                backfill["free_rituals_remaining"] = remaining
            if "free_rituals_used" not in player_fields:
                used = 0
                backfill["free_rituals_used"] = used
            if "active_attempt_label" not in player_fields:
                backfill["active_attempt_label"] = ""

            if backfill:
                try:
                    airtable_update(players_table, p["record_id"], backfill)
                except Exception as _e:
                    print("🔴 access_gate: backfill update failed:", repr(_e), flush=True)

            # No free rituals remaining → block start
            if remaining <= 0:
                print("🟠 access_gate: remaining<=0 → blocked", flush=True)
                return jsonify({
                    "ok": False,
                    "error": "no_free_rituals",
                    "player_record_id": p["record_id"]
                }), 403

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
        if apply_free_gate:
            fields["is_free"] = True

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


        # ===== Set active lock + (optional) consume free ritual =====
        try:
            upd_fields = {"active_attempt_label": created["data"]["id"]}
            if apply_free_gate:
                upd_fields.update({
                    "free_rituals_remaining": max(0, remaining - 1),
                    "free_rituals_used": used + 1,
                })
            upd = airtable_update(players_table, p["record_id"], upd_fields)
            if not upd.get("ok"):
                print("🔴 access_gate: failed to update player lock/counters:", upd, flush=True)
        except Exception as _e:
            print("🔴 access_gate: exception while updating lock/counters:", repr(_e), flush=True)

        return jsonify({
            "ok": True,
            "version": APP_VERSION,
            "attempt_id": created["data"]["id"],
            "player_record_id": p["record_id"],
            "beta_renewed": bool(beta_renewed),
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

    # ✅ Option A safety: if the player was created by the form first, link it now using telegram_username
    try:
        tg_un = payload.get("telegram_username") or payload.get("telegramUsername")
        link_form_player_by_telegram_username(players_table, str(telegram_user_id), tg_un)
    except Exception as _e:
        print("🟠 link_by_username (ritual_complete) failed:", repr(_e), flush=True)

    p = upsert_player_by_telegram_user_id(players_table, str(telegram_user_id))
    if not p.get("ok"):
        return jsonify({
            "ok": False,
            "error": "player_upsert_failed",
            "details": p
        }), 500

    # ✅ Update telegram_username if provided (can change over time)
    maybe_update_player_username(players_table, p.get("record_id"), payload.get("telegram_username") or payload.get("telegramUsername"))

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
                '{env}="BETA"',
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

        # ===== BETA qualification (Option A/B/C) =====
        # Extract key metrics from the just-completed attempt update.
        # This avoids NameError bugs and ensures qualification evaluates the current ritual.
        score_raw = _safe_int((upd.get("score_raw") if 'upd' in locals() else payload.get("score_raw") or payload.get("score")), None)
        score_max = _safe_int((upd.get("score_max") if 'upd' in locals() else payload.get("score_max") or payload.get("total") or 15), 15)
        time_total_seconds = _safe_int((upd.get("time_total_seconds") if 'upd' in locals() else payload.get("time_total_seconds") or payload.get("time_spent_seconds")), None)
        beta_qualification = {"qualified": False, "via": None}
        beta_player_update_ok = None
        beta_player_update = None
        try:
            # Evaluate only after a completed attempt update (best effort)
            if attempt_record_id and (attempt_update or {}).get("ok"):
                # Determine whether this attempt should count as a FREE trial attempt.
                # We treat it as free unless the player is already in an ACTIVE beta window.
                is_free_current = True
                try:
                    pf0 = airtable_find_one(players_table, f"{{telegram_user_id}}='{telegram_user_id}'")
                    pr0 = pf0.get("record") if pf0.get("ok") else None
                    f0 = (pr0.get("fields") or {}) if pr0 else {}
                    gate0 = str(f0.get("beta_gate_status") or "").strip().upper()
                    until0 = f0.get("beta_access_until")
                    if until0:
                        try:
                            u0 = datetime.fromisoformat(str(until0).replace("Z", "+00:00"))
                            if gate0 == "ACTIVE" and u0 > datetime.now(timezone.utc):
                                is_free_current = False
                        except Exception:
                            # If we can't parse the date, be conservative and keep it as free.
                            pass
                except Exception:
                    pass

                current_attempt = {
                    "id": str(attempt_record_id),
                    "fields": {
                        "score_raw": score_raw,
                        "score_max": score_max,
                        "time_total_seconds": time_total_seconds,
                        "is_free": is_free_current,
                        "completed_at": upd.get("completed_at") or datetime.now(timezone.utc).isoformat(),
                    },
                }

                beta_qualification = evaluate_beta_qualification(
                    attempts_table,
                    telegram_user_id,
                    current_attempt=current_attempt,
                )

                if beta_qualification.get("qualified"):
                    # Re-read player to respect MANUAL/DISQUALIFIED and avoid overriding ACTIVE
                    pf = airtable_find_one(players_table, f"{{telegram_user_id}}='{telegram_user_id}'")
                    player_rec = pf.get("record") if pf.get("ok") else None
                    player_fields = (player_rec.get("fields") or {}) if player_rec else {}

                    existing_gate = str(player_fields.get("beta_gate_status") or "").strip().upper()
                    existing_via = str(player_fields.get("qualified_via") or "").strip().upper()
                    existing_until = player_fields.get("beta_access_until")

                    # Do not override manual decisions
                    if existing_via in ("MANUAL", "DISQUALIFIED"):
                        pass
                    else:
                        # If already ACTIVE + access_until in the future, do nothing
                        already_active = False
                        if existing_gate == "ACTIVE" and existing_until:
                            try:
                                eu = datetime.fromisoformat(str(existing_until).replace("Z", "+00:00"))
                                already_active = eu > datetime.now(timezone.utc)
                            except Exception:
                                already_active = True

                        if not already_active:
                            now_utc = datetime.now(timezone.utc)
                            new_until = now_utc + timedelta(days=15)

                            # Preserve a later existing access_until if present
                            if existing_until:
                                try:
                                    eu = datetime.fromisoformat(str(existing_until).replace("Z", "+00:00"))
                                    if eu > new_until:
                                        new_until = eu
                                except Exception:
                                    pass

                            cycles_used = _safe_int(player_fields.get("beta_cycles_used"), 0) or 0
                            if cycles_used < 1:
                                cycles_used = 1

                            beta_player_update = {
                                "beta_gate_status": "ACTIVE",
                                "beta_access_until": new_until.isoformat(),
                                "beta_cycles_used": cycles_used,
                                "qualified_via": _map_qualified_via_choice(beta_qualification.get("via")),
                                "beta_decision_at": now_utc.isoformat(),
                            }

                            beta_player_update_ok = airtable_update(players_table, p["record_id"], beta_player_update)
        except Exception as _e:
            print("🟠 beta_qualification: exception:", repr(_e), flush=True)

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


    # ===== Clear active lock (best effort; all players) =====
    try:
        airtable_update(players_table, p["record_id"], {"active_attempt_label": ""})
    except Exception as _e:
        print("🔴 access_gate: clear lock failed:", repr(_e), flush=True)
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

        # BETA qualification debug (safe to ignore by clients)
        "beta_qualified":
        (beta_qualification or {}).get("qualified") if "beta_qualification" in locals() else None,
        "qualified_via":
        (beta_qualification or {}).get("via") if "beta_qualification" in locals() else None,
        "beta_player_updated":
        (beta_player_update_ok or {}).get("ok") if "beta_player_update_ok" in locals() and isinstance(beta_player_update_ok, dict) else None,
        "beta_access_until":
        (beta_player_update or {}).get("beta_access_until") if "beta_player_update" in locals() and isinstance(beta_player_update, dict) else None,
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