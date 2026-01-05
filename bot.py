"""
bot.py — Velvet Oracle — WebApp Edition (V8 PROD)
Corrections : Mappage CSV, Intégration Airtable, Stabilité WebApp
"""

import os
import json
import logging
import threading
import asyncio
import time
import requests
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

import server  # server.py — Backend Flask
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
#  CONFIG & SECRETS
# ============================================================================

BOT_VERSION = "webapp_prod_v8_airtable_sync"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_EXAMS_DB_ID = os.getenv("NOTION_EXAMS_DB_ID")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_PAYLOADS_BASE_ID")
AIRTABLE_TABLE_NAME = "Attempts"  # Nom d'onglet vérifié dans tes CSV

ADMIN_IDS_RAW = os.getenv("VELVET_ADMIN_IDS") or ""
ADMIN_IDS = {x.strip() for x in ADMIN_IDS_RAW.split(",") if x.strip()}

# Mappage corrigé d'après tes fichiers CSV
NOTION_FIELDS = {
    "joueur_id": "player",
    "mode": "mode",
    "score": "score_raw",
    "statut": "status",
    "date": "completed_at",
    "time_s": "time_total_seconds",
    "time_mmss": "time_formatted",
    "reponses": "answer_logs",
    "commentaires": "feedback",
    "version_bot": "status_technique",
    "profil_joueur": "signature_cognitive",
    "nom_utilisateur": "display_name",
    "username_telegram": "telegram_handle",
}

# ============================================================================
#  LOGGING
# ============================================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ============================================================================
#  HELPERS
# ============================================================================

def is_admin(joueur_id: str) -> bool:
    return str(joueur_id) in ADMIN_IDS

def format_time_mmss(total_seconds: int) -> str:
    minutes, seconds = divmod(max(0, total_seconds), 60)
    return f"{minutes:02d}:{seconds:02d}"

def compute_player_profile(score: int, total: int, time_s: int) -> str:
    if total <= 0: return "Oracle en Devenir"
    ratio = score / total
    if ratio >= 0.85: return "Esprit Fulgurant" if time_s / total <= 5 else "Stratège Silencieux"
    return "Explorateur Patient" if ratio >= 0.65 else "Oracle en Devenir"

# ============================================================================
#  AIRTABLE API
# ============================================================================

def create_record_in_airtable(payload: Dict[str, Any]):
    """Enregistre une copie de sécurité dans Airtable."""
    if not AIRTABLE_API_KEY or not AIRTABLE_BASE_ID:
        logger.warning("⚠️ Airtable non configuré.")
        return

    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}", "Content-Type": "application/json"}
    
    # Préparation des champs selon la structure CSV
    record = {
        "fields": {
            "player": str(payload.get("joueur_id")),
            "score_raw": int(payload.get("score", 0)),
            "time_total_seconds": int(payload.get("time_total_seconds", 0)),
            "status": payload.get("statut", "Inconnu"),
            "mode": payload.get("mode", "Prod"),
            "feedback": payload.get("commentaires", ""),
            "status_technique": BOT_VERSION
        }
    }
    try:
        r = requests.post(url, headers=headers, json=record, timeout=15)
        if r.ok: logger.info("✅ Succès Airtable")
        else: logger.error(f"❌ Échec Airtable: {r.text}")
    except Exception as e:
        logger.error(f"❌ Exception Airtable: {e}")

# ============================================================================
#  NOTION API
# ============================================================================

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

def create_exam_in_notion(data: Dict[str, Any]) -> Optional[str]:
    url = "https://api.notion.com/v1/pages"
    now = datetime.now(timezone.utc).isoformat()
    
    props = {
        NOTION_FIELDS["joueur_id"]: {"title": [{"text": {"content": str(data['joueur_id'])}}]},
        NOTION_FIELDS["score"]: {"number": int(data['score'])},
        NOTION_FIELDS["statut"]: {"select": {"name": data['statut']}},
        NOTION_FIELDS["date"]: {"date": {"start": now}},
        NOTION_FIELDS["time_s"]: {"number": int(data['time_s'])},
        NOTION_FIELDS["commentaires"]: {"rich_text": [{"text": {"content": data['commentaires'][:1900]}}]},
        NOTION_FIELDS["profil_joueur"]: {"select": {"name": data['profil']}},
    }
    
    payload = {"parent": {"database_id": NOTION_EXAMS_DB_ID}, "properties": props}
    try:
        r = requests.post(url, headers=NOTION_HEADERS, json=payload, timeout=20)
        if r.ok: return r.json().get("id")
        logger.error(f"Notion Error: {r.text}")
    except Exception as e:
        logger.error(f"Notion Exception: {e}")
    return None

# ============================================================================
#  TELEGRAM HANDLERS
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    v = int(time.time())
    webapp_url = f"https://oracle--Velvet-elite.replit.app/webapp/?v={v}"
    
    # Configuration du bouton de menu pour iOS/Android
    await context.bot.set_chat_menu_button(
        chat_id=update.effective_chat.id,
        menu_button=MenuButtonWebApp(text="Velvet Oracle", web_app=WebAppInfo(url=webapp_url))
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(text="✨ Lancer le Rituel", web_app=WebAppInfo(url=webapp_url))
    ]])
    await update.message.reply_text("🕯️ Prêt pour l'épreuve ?", reply_markup=keyboard)

async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Capture les données envoyées par la WebApp."""
    msg = update.effective_message
    if not msg or not msg.web_app_data:
        return

    user = update.effective_user
    raw_data = msg.web_app_data.data
    logger.info(f"📥 Données WebApp reçues: {raw_data}")

    try:
        data = json.loads(raw_data)
        score = data.get("score", 0)
        total = data.get("total", 15)
        time_s = data.get("time_spent_seconds", 0)
        
        processed_payload = {
            "joueur_id": user.id,
            "score": score,
            "time_s": time_s,
            "time_total_seconds": time_s,
            "statut": "Admis" if score >= (total * 0.75) else "Refusé",
            "commentaires": data.get("feedback", "Aucun"),
            "profil": compute_player_profile(score, total, time_s),
            "mode": "Prod"
        }

        # Double sauvegarde
        notion_id = create_exam_in_notion(processed_payload)
        create_record_in_airtable(processed_payload)

        await msg.reply_text("🕯️ Vos résultats ont été gravés dans l'Oracle." if notion_id 
                             else "⚠️ Résultats reçus mais erreur de stockage.")

    except Exception as e:
        logger.error(f"Erreur traitement WebApp: {e}")
        await msg.reply_text("❌ Erreur de lecture des données du Rituel.")

# ============================================================================
#  MAIN RUNNER
# ============================================================================

async def main():
    app_tg = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app_tg.add_handler(CommandHandler("start", start))
    # Utilisation de filters.ALL pour capturer les données WebApp même si le message est mal typé
    app_tg.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))

    # Lancement Flask en thread
    threading.Thread(target=lambda: server.app.run(host="0.0.0.0", port=5000), daemon=True).start()

    async with app_tg:
        await app_tg.initialize()
        await app_tg.start()
        await app_tg.updater.start_polling()
        logger.info("🚀 Bot & Serveur démarrés.")
        while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())