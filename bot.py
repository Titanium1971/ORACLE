"""
bot.py — Velvet Oracle — WebApp Edition (PROD stable)

Objectif :
- WebApp ouverte depuis bouton Telegram (InlineKeyboardButton web_app)
- WebApp envoie Telegram.WebApp.sendData(payload)
- Bot reçoit WEB_APP_DATA (Update.message.web_app_data) et écrit dans Notion
- Flask backend unique (server.py) servi par ce même process (Run = Publish identiques)
"""

import os

AIRTABLE_PAYLOADS_BASE_ID = os.getenv("AIRTABLE_PAYLOADS_BASE_ID")

import json
import logging
import threading
import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

import requests

# ✅ backend UNIQUE importé
import server  # server.py — Velvet MCP Core (questions/random, feedback endpoint éventuel, health, CORS, etc.)

from telegram import (
    Update,
    WebAppInfo,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
    MenuButtonWebApp)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters)

# ============================================================================
#  CONFIG
# ============================================================================

BOT_VERSION = "webapp_prod_v7_menu_button_fullheight"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv(
    "TELEGRAM_F1_TOKEN")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_EXAMS_DB_ID = os.getenv("NOTION_EXAMS_DB_ID")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN manquant.")
if not NOTION_API_KEY:
    raise RuntimeError("NOTION_API_KEY manquant.")
if not NOTION_EXAMS_DB_ID:
    raise RuntimeError("NOTION_EXAMS_DB_ID manquant.")

ADMIN_IDS_RAW = os.getenv("VELVET_ADMIN_IDS") or os.getenv("ADMIN_IDS") or ""
ADMIN_IDS = {x.strip() for x in ADMIN_IDS_RAW.split(",") if x.strip()}

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

# ============================================================================
#  LOGGING
# ============================================================================

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)

# ============================================================================
#  HELPERS
# ============================================================================


def is_admin(joueur_id: str) -> bool:
    return str(joueur_id) in ADMIN_IDS


def _first_str(payload: Dict[str, Any], keys: List[str]) -> Optional[str]:
    for k in keys:
        v = payload.get(k)
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        return str(v)
    return None


def _first_int(payload: Dict[str, Any], keys: List[str]) -> Optional[int]:
    for k in keys:
        v = payload.get(k)
        if v is None:
            continue
        try:
            return int(float(v))
        except Exception:
            continue
    return None


def format_time_mmss(total_seconds: int) -> str:
    if total_seconds < 0:
        total_seconds = 0
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def compute_player_profile(score: int, total_questions: int,
                           total_time_s: int) -> str:
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


def format_answers_pretty(answers: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for a in answers:
        qid = a.get("question_id") or "?"
        letter = a.get("choice_letter") or "-"
        status = (a.get("status") or "").lower()
        if status == "correct":
            mark = "✅"
        elif status == "timeout":
            mark = "⏳"
        else:
            mark = "❌"
        lines.append(f"{qid} : {letter} {mark}")
    return "\n".join(lines) if lines else "-"


# ============================================================================
#  NOTION API
# ============================================================================

NOTION_BASE_URL = "https://api.notion.com/v1"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def notion_query(database_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{NOTION_BASE_URL}/databases/{database_id}/query"
    resp = requests.post(url, headers=NOTION_HEADERS, json=payload, timeout=20)
    if not resp.ok:
        logger.error("Erreur Notion (query) %s : %s", resp.status_code,
                     resp.text)
        resp.raise_for_status()
    return resp.json()


def notion_create_page(database_id: str, properties: Dict[str, Any]) -> str:
    url = f"{NOTION_BASE_URL}/pages"
    payload = {
        "parent": {
            "database_id": database_id
        },
        "properties": properties
    }
    resp = requests.post(url, headers=NOTION_HEADERS, json=payload, timeout=20)
    if not resp.ok:
        logger.error("Erreur Notion (create) %s : %s", resp.status_code,
                     resp.text)
        resp.raise_for_status()
    return resp.json().get("id")


def notion_update_page(page_id: str, properties: Dict[str, Any]) -> None:
    url = f"{NOTION_BASE_URL}/pages/{page_id}"
    payload = {"properties": properties}
    resp = requests.patch(url,
                          headers=NOTION_HEADERS,
                          json=payload,
                          timeout=20)
    if not resp.ok:
        logger.error("Erreur Notion (update) %s : %s", resp.status_code,
                     resp.text)
        resp.raise_for_status()


def has_already_taken_exam(joueur_id: str, mode: str = "Prod") -> bool:
    try:
        payload = {
            "filter": {
                "and": [
                    {
                        "property": NOTION_FIELDS["joueur_id"],
                        "title": {
                            "equals": joueur_id
                        }
                    },
                    {
                        "property": NOTION_FIELDS["mode"],
                        "select": {
                            "equals": mode
                        }
                    },
                ]
            },
            "page_size": 1,
        }
        data = notion_query(NOTION_EXAMS_DB_ID, payload)
        return len(data.get("results", [])) > 0
    except Exception as e:
        logger.error("has_already_taken_exam — échec : %s", e)
        return False


def compute_statut(score: int, total_questions: int, mode: str) -> str:
    # Si on ne connaît pas le total (ex: feedback seul), on évite un statut arbitraire.
    if total_questions <= 0:
        return "En cours"
    if mode != "Prod":
        return "En cours"
    seuil = max(1, int(round(total_questions *
                             0.75))) if total_questions > 0 else 12
    return "Admis" if score >= seuil else "Refusé"


def create_exam_in_notion(
    joueur_id: str,
    mode: str,
    score: int,
    total_questions: int,
    total_time_s: int,
    time_mmss: str,
    answers_pretty: str,
    commentaires: str,
    profil_joueur: str,
    nom_utilisateur: str,
    username_telegram: str,
    version_bot: str) -> Optional[str]:
    now = datetime.now(timezone.utc).isoformat()
    statut_value = compute_statut(score, total_questions, mode)

    properties: Dict[str, Any] = {
        NOTION_FIELDS["joueur_id"]: {
            "title": [{
                "type": "text",
                "text": {
                    "content": joueur_id
                }
            }]
        },
        NOTION_FIELDS["mode"]: {
            "select": {
                "name": mode
            }
        },
        NOTION_FIELDS["score"]: {
            "number": int(score)
        },
        NOTION_FIELDS["statut"]: {
            "select": {
                "name": statut_value
            }
        },
        NOTION_FIELDS["date"]: {
            "date": {
                "start": now
            }
        },
        NOTION_FIELDS["time_s"]: {
            "number": int(total_time_s)
        },
        NOTION_FIELDS["time_mmss"]: {
            "rich_text": [{
                "type": "text",
                "text": {
                    "content": time_mmss
                }
            }]
        },
        NOTION_FIELDS["reponses"]: {
            "rich_text": [{
                "type": "text",
                "text": {
                    "content": (answers_pretty or "-")[:1900]
                }
            }]
        },
        NOTION_FIELDS["commentaires"]: {
            "rich_text": [{
                "type": "text",
                "text": {
                    "content": (commentaires or "-")[:1900]
                }
            }]
        },
        NOTION_FIELDS["version_bot"]: {
            "rich_text": [{
                "type": "text",
                "text": {
                    "content": (version_bot or BOT_VERSION)[:1900]
                }
            }]
        },
        NOTION_FIELDS["nom_utilisateur"]: {
            "rich_text": [{
                "type": "text",
                "text": {
                    "content": (nom_utilisateur or "-")[:1900]
                }
            }]
        },
        NOTION_FIELDS["username_telegram"]: {
            "rich_text": [{
                "type": "text",
                "text": {
                    "content": (username_telegram or "-")[:1900]
                }
            }]
        },
        NOTION_FIELDS["profil_joueur"]: {
            "select": {
                "name": profil_joueur
            }
        },
    }

    try:
        page_id = notion_create_page(NOTION_EXAMS_DB_ID, properties)
        logger.info("✅ Notion page créée=%s | time=%s (%s)", page_id,
                    total_time_s, time_mmss)
        return page_id
    except Exception as e:
        logger.error("❌ Erreur création Notion : %s", e)
        return None


def get_last_exam_page_for_player(joueur_id: str) -> Optional[str]:
    try:
        payload = {
            "filter": {
                "property": NOTION_FIELDS["joueur_id"],
                "title": {
                    "equals": joueur_id
                }
            },
            "sorts": [{
                "property": NOTION_FIELDS["date"],
                "direction": "descending"
            }],
            "page_size":
            1,
        }
        data = notion_query(NOTION_EXAMS_DB_ID, payload)
        results = data.get("results", [])
        return results[0]["id"] if results else None
    except Exception as e:
        logger.error("Erreur recherche dernière page : %s", e)
        return None


def update_exam_feedback(page_id: str, feedback: str) -> bool:
    try:
        properties = {
            NOTION_FIELDS["commentaires"]: {
                "rich_text": [{
                    "type": "text",
                    "text": {
                        "content": (feedback or "-")[:1900]
                    }
                }]
            }
        }
        notion_update_page(page_id, properties)
        return True
    except Exception as e:
        logger.error("❌ Erreur update feedback : %s", e)
        return False


# ============================================================================
#  TELEGRAM — COMMANDES
# ============================================================================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return

    joueur_id = str(user.id)
    admin = is_admin(joueur_id)
    context.user_data["exam_mode"] = "Prod"

    # ✅ retire l'ancien clavier
    await msg.reply_text("⟡", reply_markup=ReplyKeyboardRemove())

    if has_already_taken_exam(joueur_id, mode="Prod") and not admin:
        await msg.reply_text(
            "🕯️ Tu as déjà franchi l'épreuve officielle, une seule fois suffit."
        )
        return

    # ✅ cache-buster réel
    v = int(time.time())
    webapp_url = (
        "https://oracle--Velvet-elite.replit.app/webapp/"
        f"?api=https://oracle--Velvet-elite.replit.app&v={v}")
    logger.info("🔗 WEBAPP_URL_SENT=%s", webapp_url)

    # ✅ iOS/viewport: définir aussi le bouton Menu du chat vers la WebApp.
    # Sur certains clients iOS, l'ouverture via le Menu est plus fiable en hauteur.
    try:
        await context.bot.set_chat_menu_button(
            chat_id=msg.chat_id,
            menu_button=MenuButtonWebApp(text="Velvet Oracle", web_app=WebAppInfo(url=webapp_url)))
        logger.info("✅ CHAT_MENU_BUTTON_WEBAPP_SET chat_id=%s", msg.chat_id)
    except Exception as e:
        logger.warning("⚠️ set_chat_menu_button failed: %s", e)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(text="Lancer le Rituel Velvet Oracle",
                             web_app=WebAppInfo(url=webapp_url))
    ]])
    await msg.reply_text("🕯️ Lorsque tu es prêt, touche le bouton ci-dessous.",
                         reply_markup=keyboard)


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg:
        return
    username = f"@{user.username}" if user.username else "—"
    await msg.reply_text(
        f"ID={user.id}\nNom={user.first_name or ''} {user.last_name or ''}\nUsername={username}"
    )


# ============================================================================
#  TELEGRAM — WEBAPP DATA (FIX CANON)
# ============================================================================


async def handle_any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fallback: if a message carries web_app_data, route it to the WebApp handler."""
    msg = update.effective_message
    try:
        if msg and getattr(msg, "web_app_data", None):
            logger.info("🟣 WEBAPP_DATA_FALLBACK — routing to handle_webapp_data")
            return await handle_webapp_data(update, context)
    except Exception:
        logger.exception("WEBAPP_DATA_FALLBACK_FAILED")
    return

async def handle_webapp_data(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not getattr(msg, "web_app_data", None):
        return

    joueur_id = str(user.id)
    exam_mode_value = context.user_data.get("exam_mode", "Prod")

    full_name = (
        f"{user.first_name or ''} {user.last_name or ''}").strip() or "-"
    username = f"@{user.username}" if user.username else "-"

    raw = msg.web_app_data.data
    logger.info("🟣 WEBAPP_DATA_RX len=%s raw(first200)=%r", len(raw or ""),
                (raw or "")[:200])

    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            payload = {"raw": raw, "parsed_type": str(type(payload))}
    except Exception:
        payload = {"raw": raw}

    payload_mode = (_first_str(payload, ["mode", "type"]) or "").strip()
    # Fallback : certains builds n'envoient pas de champ mode/type sur le dernier bouton.
    if not payload_mode:
        if any(k in payload
               for k in ("score", "answers", "total", "time_total_seconds",
                         "time_spent_seconds")):
            payload_mode = "rituel_full_v1"
        elif any(k in payload for k in ("feedback_text", "commentaires",
                                        "feedback", "text")):
            payload_mode = "rituel_feedback_v1"
        else:
            payload_mode = "unknown"
    logger.info("📩 WEBAPP_DATA mode=%s keys=%s", payload_mode,
                list(payload.keys()))

    # compat
    if payload_mode in ("ritual_full_v1", "ritual_v1"):
        payload_mode = payload_mode.replace("ritual_", "rituel_")

    # 1) RITUEL (création page)
    if payload_mode in ("rituel_full_v1", "rituel_v1"):
        score = _first_int(payload, ["score"]) or 0
        total = _first_int(payload, ["total"]) or 15

        total_time_s = _first_int(
            payload,
            [
                "time_total_seconds", "time_spent_seconds",
                "total_time_seconds", "duration_seconds"
            ])
        if total_time_s is None:
            total_time_s = 0

        time_mmss = _first_str(
            payload, ["time_formatted"]) or format_time_mmss(total_time_s)

        answers = payload.get("answers") or []
        if not isinstance(answers, list):
            answers = []
        answers_pretty = format_answers_pretty(answers)

        profil = compute_player_profile(score, total, total_time_s)

        commentaires = _first_str(
            payload,
            ["feedback_text", "commentaires", "commentaire", "message"]) or "-"

        page_id = create_exam_in_notion(
            joueur_id=joueur_id,
            mode=exam_mode_value,
            score=score,
            total_questions=total,
            total_time_s=total_time_s,
            time_mmss=time_mmss,
            answers_pretty=answers_pretty,
            commentaires=commentaires,
            profil_joueur=profil,
            nom_utilisateur=full_name,
            username_telegram=username,
            version_bot=payload_mode)

        await msg.reply_text("🕯️ Payload reçu. Trace inscrite." if page_id else
                             "❌ Payload reçu, mais Notion a refusé.")
        return

    # 2) FEEDBACK (update dernière page)
    if payload_mode in ("rituel_feedback_v1", "feedback", "rituel_feedback"):
        feedback_text = (_first_str(
            payload, ["feedback_text", "commentaires", "feedback", "text"])
                         or "-").strip() or "-"

        page_id = get_last_exam_page_for_player(joueur_id)
        if not page_id:
            # Aucun rituel trouvé : on crée une trace minimale (statut=En cours via compute_statut total_questions<=0)
            created = create_exam_in_notion(
                joueur_id=joueur_id,
                mode=exam_mode_value,
                score=0,
                total_questions=0,
                total_time_s=0,
                time_mmss="00:00",
                answers_pretty="-",
                commentaires=feedback_text,
                profil_joueur="Oracle en Devenir",
                nom_utilisateur=full_name,
                username_telegram=username,
                version_bot="rituel_feedback_v1")
            await msg.reply_text("🕯️ Feedback noté." if created else
                                 "❌ Feedback reçu, mais Notion a refusé.")
            return

        ok = update_exam_feedback(page_id, feedback_text)
        await msg.reply_text("🕯️ Feedback noté." if ok else
                             "❌ Feedback reçu, mais Notion a refusé.")
        return

    await msg.reply_text("Payload reçu mais mode inconnu.")
    logger.warning("Mode inconnu: %s", payload_mode)


# ============================================================================
#  FLASK BACKEND (UNIFIÉ)
# ============================================================================

app = server.app


def run_flask():
    port = int(os.getenv("PORT", "5000"))
    logger.info("🔵 FLASK STARTING on 0.0.0.0:%s", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    logger.info("🔴 FLASK STOPPED")


# ============================================================================
#  DEBUG (anti-hallucination : preuve d'updates)
# ============================================================================


async def debug_any_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        d = update.to_dict()
        logger.info("🧪 UPDATE_RX keys=%s", list(d.keys()))
        m = getattr(update, "message", None)
        if m:
            wad = getattr(m, "web_app_data", None)
            logger.info("🧪 MSG_RX text=%r has_web_app_data=%s", m.text,
                        bool(wad))
            if wad:
                logger.info("🧪 WEBAPP_DATA_RX len=%s",
                            len(getattr(wad, "data", "") or ""))
    except Exception as e:
        logger.exception("🧪 debug_any_update error: %s", e)


# ============================================================================
#  MAIN
# ============================================================================


async def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Commandes
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("whoami", whoami))

    # WebApp data handler - ONLY for web_app_data messages
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))

    # Debug global
    application.add_handler(TypeHandler(Update, debug_any_update), group=-1)
    async with application:
        await application.start()
        logger.info("🕯️ Bot lancé.")
        logger.info("🧪 BEFORE_START_POLLING")

        await application.updater.start_polling()
        logger.info("🧪 AFTER_START_POLLING")

        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await application.updater.stop()
            await application.stop()


if __name__ == "__main__":
    # Token present → run both: Flask API + Telegram bot
    flask_thread = threading.Thread(target=run_flask, daemon=False)
    flask_thread.start()

    try:
        asyncio.run(main())
    except Exception as e:
        logger.exception("Telegram bot crashed; keeping Flask API alive. Error: %s", e)
        flask_thread.join()