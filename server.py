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
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder='webapp', static_url_path='/webapp')

print("🟢 SERVER.PY LOADED - Flask app initialized")

from flask_cors import CORS

CORS(app, resources={r"/*": {"origins": "*"}})

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
    seuil = max(1, int(round(total_questions * 0.75))) if total_questions > 0 else 12
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
        time_seconds = payload.get("time_total_seconds") or payload.get("time_spent_seconds") or 0
        time_formatted = payload.get("time_formatted") or format_time_mmss(time_seconds)
        answers = payload.get("answers") or []
        comment = payload.get("comment_text") or payload.get("feedback_text") or "-"
        telegram_user_id = str(payload.get("telegram_user_id") or payload.get("user_id") or "unknown")
        
        # Compute profile and status
        profil = compute_player_profile(score, total, time_seconds)
        statut = compute_statut(score, total, "Prod")
        answers_text = format_answers_pretty(answers)
        
        now = datetime.now(timezone.utc).isoformat()
        
        properties = {
            NOTION_FIELDS["joueur_id"]: {
                "title": [{
                    "type": "text",
                    "text": {"content": telegram_user_id}
                }]
            },
            NOTION_FIELDS["mode"]: {
                "select": {"name": "Prod"}
            },
            NOTION_FIELDS["score"]: {
                "number": int(score)
            },
            NOTION_FIELDS["statut"]: {
                "select": {"name": statut}
            },
            NOTION_FIELDS["date"]: {
                "date": {"start": now}
            },
            NOTION_FIELDS["time_s"]: {
                "number": int(time_seconds)
            },
            NOTION_FIELDS["time_mmss"]: {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": time_formatted}
                }]
            },
            NOTION_FIELDS["reponses"]: {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": (answers_text or "-")[:1900]}
                }]
            },
            NOTION_FIELDS["commentaires"]: {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": (comment or "-")[:1900]}
                }]
            },
            NOTION_FIELDS["version_bot"]: {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": "rituel_full_v1_http"}
                }]
            },
            NOTION_FIELDS["profil_joueur"]: {
                "select": {"name": profil}
            },
            NOTION_FIELDS["nom_utilisateur"]: {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": "-"}
                }]
            },
            NOTION_FIELDS["username_telegram"]: {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": "-"}
                }]
            },
        }
        
        url = f"{NOTION_BASE_URL}/pages"
        notion_payload = {
            "parent": {"database_id": NOTION_EXAMS_DB_ID},
            "properties": properties
        }
        
        headers = get_notion_headers()
        resp = requests.post(url, headers=headers, json=notion_payload, timeout=20)
        
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

def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def airtable_quote(value) -> str:
    """Quote and escape a value for Airtable filterByFormula strings."""
    s = str(value)
    s = s.replace('"', '\\"')
    return f'"{s}"'



def _airtable_headers():
    key = os.getenv("AIRTABLE_API_KEY") or os.getenv("AIRTABLE_KEY")
    if not key:
        return None
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }


# -----------------------------------------------------
# BETA Airtable routing (Base + Table IDs dédiés)
# -----------------------------------------------------
BETA_AIRTABLE_BASE_ID = os.getenv("BETA_AIRTABLE_BASE_ID")
BETA_AIRTABLE_PLAYERS_TABLE_ID = os.getenv("BETA_AIRTABLE_PLAYERS_TABLE_ID")
BETA_AIRTABLE_ATTEMPTS_TABLE_ID = os.getenv("BETA_AIRTABLE_ATTEMPTS_TABLE_ID")

def beta_airtable_enabled():
    return bool(BETA_AIRTABLE_BASE_ID and BETA_AIRTABLE_PLAYERS_TABLE_ID and BETA_AIRTABLE_ATTEMPTS_TABLE_ID)

def beta_players_table():
    return BETA_AIRTABLE_PLAYERS_TABLE_ID or os.getenv("AIRTABLE_PLAYERS_TABLE", "players")

def beta_attempts_table():
    return BETA_AIRTABLE_ATTEMPTS_TABLE_ID or os.getenv("AIRTABLE_ATTEMPTS_TABLE", "rituel_attempts")

def _airtable_base_id(table_name=""):
    # ROUTING BETA (prioritaire) : si on écrit dans players/attempts de la base BETA
    if beta_airtable_enabled():
        beta_tables = {
            BETA_AIRTABLE_PLAYERS_TABLE_ID,
            BETA_AIRTABLE_ATTEMPTS_TABLE_ID,
            "players_beta",
            "rituel_attempts_beta",
        }
        if table_name in beta_tables:
            return BETA_AIRTABLE_BASE_ID

    # Si c'est une table de questions, utiliser AIRTABLE_BASE_ID
    # Sinon utiliser AIRTABLE_CORE_BASE_ID pour players/attempts/etc
    questions_table = os.getenv("AIRTABLE_TABLE_ID", "")

    # Liste des tables qui vont dans CORE (players/attempts/etc)
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

    # Si c'est la table de questions -> base QUESTIONS
    if table_name == questions_table:
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

    payload = _json()
    telegram_user_id = payload.get("telegram_user_id") or payload.get("user_id") or payload.get("tg_user_id")
    if not telegram_user_id:
        return jsonify({"ok": False, "error": "missing_telegram_user_id"}), 400

    # BETA: on ne crée pas de tentative au start (table minimaliste). On ancre seulement le player.
    if beta_airtable_enabled():
        p = upsert_player_by_telegram_user_id(beta_players_table(), str(telegram_user_id))
        if not p.get("ok"):
            return jsonify({"ok": False, "error": "player_upsert_failed", "details": p}), 500

        return jsonify({
            "ok": True,
            "env": "BETA",
            "player_record_id": p["record_id"],
            "started_at": payload.get("started_at") or _utc_now_iso()
        })

    # CORE (legacy): comportement historique
    try:
        print("🔵 DEBUG /ritual/start appelé")

        p = upsert_player_by_telegram_user_id(os.getenv("AIRTABLE_PLAYERS_TABLE") or "players", str(telegram_user_id))
        if not p.get("ok"):
            return jsonify({"ok": False, "error": "player_upsert_failed", "details": p}), 500

        # Translate mode for Airtable (app.js sends "rituel_full_v1" but Airtable expects "PROD" or "TEST")
        raw_mode = payload.get("mode") or payload.get("env") or "PROD"
        if raw_mode in ("rituel_full_v1", "ritual_full_v1", "rituel_v1", "ritual_v1"):
            airtable_mode = "PROD"
        elif raw_mode == "TEST":
            airtable_mode = "TEST"
        else:
            airtable_mode = "PROD"  # fallback

        attempts_table = os.getenv("AIRTABLE_ATTEMPTS_TABLE") or "rituel_attempts"

        # Create attempt (write only whitelisted raw fields; never computed/system fields)
        fields = {
            "player": [p["record_id"]],
            "started_at": payload.get("started_at") or datetime.now(timezone.utc).isoformat(),
            "mode": airtable_mode,
            "status": payload.get("status") or "STARTED",
            "status_technique": "INIT",
        }
        if payload.get("Players"):
            fields["Players"] = payload.get("Players")

        # Idempotence (BETA): évite les doublons si /ritual/complete est appelé plusieurs fois.

        # Un rituel est unique par (player.telegram_user_id + started_at + completed_at + env).

        try:

            formula = (

                "AND("

                f"{{env}}={airtable_quote('BETA')},"

                f"ARRAYJOIN({{player}})={airtable_quote(str(telegram_user_id))},"

                f"IS_SAME({{started_at}}, DATETIME_PARSE({airtable_quote(started_at)}), 'second'),"

                f"IS_SAME({{completed_at}}, DATETIME_PARSE({airtable_quote(completed_at)}), 'second')"

                ")"

            )

            existing = airtable_find_one(attempts_table, formula)

            if existing.get("ok") and existing.get("records"):

                rec_id = existing["records"][0].get("id")

                return jsonify({"ok": True, "deduped": True, "attempt_record_id": rec_id, "env": "BETA"}), 200

        except Exception:

            # En cas d'échec du check, on continue et on tente l'écriture (meilleur effort)

            pass



        created = airtable_create(attempts_table, fields)
        if created.get("ok"):
            return jsonify({
                "ok": True,
                "action": "created",
                "attempt_record_id": created["data"]["id"]
            })

        return jsonify({"ok": False, "error": "attempt_create_failed", "details": created}), 500

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/ritual/complete", methods=["POST", "OPTIONS"])
def ritual_complete():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = _json()
    telegram_user_id = payload.get("telegram_user_id") or payload.get(
        "user_id") or payload.get("tg_user_id")
    attempt_record_id = payload.get("attempt_record_id") or payload.get(
        "exam_record_id") or payload.get("attempt_id")

    if not telegram_user_id:
        return jsonify({"ok": False, "error": "missing_telegram_user_id"}), 400

    
    # BETA: écriture minimale + Notion (si configuré)
    if beta_airtable_enabled():
        players_table = beta_players_table()
        attempts_table = beta_attempts_table()

        p = upsert_player_by_telegram_user_id(players_table, str(telegram_user_id))
        if not p.get("ok"):
            return jsonify({"ok": False, "error": "player_upsert_failed", "details": p}), 500

        # Normalisation des champs (tolérant aux payloads WebApp différents)
        started_at = payload.get("started_at") or (payload.get("ritual") or {}).get("started_at") or _utc_now_iso()
        completed_at = payload.get("completed_at") or (payload.get("ritual") or {}).get("completed_at") or _utc_now_iso()

        score_raw = payload.get("score_raw") or payload.get("score") or (payload.get("ritual") or {}).get("score_raw") or 0
        score_max = payload.get("score_max") or payload.get("total") or (payload.get("ritual") or {}).get("score_max") or 15
        time_total_seconds = payload.get("time_total_seconds") or payload.get("time_spent_seconds") or (payload.get("ritual") or {}).get("time_total_seconds") or 0

        # answers_json: string JSON (jamais objet)
        answers_any = payload.get("answers_json") or payload.get("answers") or (payload.get("ritual") or {}).get("answers_json") or (payload.get("ritual") or {}).get("answers")
        if isinstance(answers_any, str):
            answers_json = answers_any
        else:
            try:
                answers_json = json.dumps(answers_any or {}, ensure_ascii=False)
            except Exception:
                answers_json = "{}"

        feedback_text = payload.get("feedback_text") or payload.get("comment_text") or (payload.get("ritual") or {}).get("feedback_text") or ""

        # WHITELIST (anti-422)
        fields = {
            "player": [p["record_id"]],
            "started_at": started_at,
            "completed_at": completed_at,
            "score_raw": int(score_raw) if str(score_raw).isdigit() else score_raw,
            "score_max": int(score_max) if str(score_max).isdigit() else score_max,
            "time_total_seconds": int(time_total_seconds) if str(time_total_seconds).isdigit() else time_total_seconds,
            "answers_json": answers_json,
            "feedback_text": feedback_text,
            "env": "BETA",
        }

        created = airtable_create(attempts_table, fields)
        if not created.get("ok"):
            return jsonify({"ok": False, "error": "beta_attempt_create_failed", "details": created}), 500

        # Notion (on conserve la logique existante)
        notion_payload = {
            "telegram_user_id": str(telegram_user_id),
            "score": int(score_raw) if str(score_raw).isdigit() else score_raw,
            "total": int(score_max) if str(score_max).isdigit() else score_max,
            "time_total_seconds": int(time_total_seconds) if str(time_total_seconds).isdigit() else time_total_seconds,
            "time_formatted": None,
            "answers": payload.get("answers") or (payload.get("ritual") or {}).get("answers") or [],
            "comment_text": feedback_text,
        }
        notion_res = write_rituel_to_notion(notion_payload)

        return jsonify({
            "ok": True,
            "env": "BETA",
            "attempt_record_id": created["data"]["id"],
            "notion_written": notion_res.get("ok") if isinstance(notion_res, dict) else False
        })

    players_table = os.getenv("AIRTABLE_PLAYERS_TABLE", "players")
    attempts_table = os.getenv("AIRTABLE_ATTEMPTS_TABLE", "rituel_attempts")
    payloads_table = os.getenv("AIRTABLE_PAYLOADS_TABLE",
                               "rituel_webapp_payloads")
    answers_table = os.getenv("AIRTABLE_ANSWERS_TABLE", "rituel_answers")
    feedback_table = os.getenv("AIRTABLE_FEEDBACK_TABLE", "rituel_feedback")

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

    # 2) Update attempt if we have its record id
    attempt_update = None
    if attempt_record_id:
        upd = {
            "completed_at":
            payload.get("completed_at")
            or datetime.now(timezone.utc).isoformat(),
            "status":
            payload.get("status") or "COMPLETED",
        }
        # scoring fields (only if provided)
        for k_src, k_dst in [
            ("score_raw", "score_raw"),
            ("score_max", "score_max"),
            ("time_total_seconds", "time_total_seconds"),
            ("result", "result"),
        ]:
            if payload.get(k_src) is not None:
                upd[k_dst] = payload.get(k_src)
        
        # Translate mode for Airtable
        if payload.get("mode") is not None:
            raw_mode = payload.get("mode")
            if raw_mode in ("rituel_full_v1", "ritual_full_v1", "rituel_v1", "ritual_v1"):
                upd["mode"] = "PROD"
            elif raw_mode == "TEST":
                upd["mode"] = "TEST"
            else:
                upd["mode"] = "PROD"
        
        attempt_update = airtable_update(attempts_table,
                                         str(attempt_record_id), upd)

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
            print(f"✅ NOTION WRITE SUCCESS: page_id={notion_res.get('page_id')}")
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
