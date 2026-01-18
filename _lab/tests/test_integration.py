#!/usr/bin/env python3
"""
Test d'intégration Velvet Oracle - Airtable + Notion
====================================================
Vérifie que toutes les connexions et écritures fonctionnent.
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Couleurs pour le terminal
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

def print_success(msg):
    print(f"{GREEN}✅ {msg}{RESET}")

def print_error(msg):
    print(f"{RED}❌ {msg}{RESET}")

def print_warning(msg):
    print(f"{YELLOW}⚠️  {msg}{RESET}")

def print_info(msg):
    print(f"{BLUE}ℹ️  {msg}{RESET}")

def print_section(title):
    print(f"\n{'='*60}")
    print(f"{BLUE}{title}{RESET}")
    print('='*60)

# ============================================================================
# 1. VÉRIFICATION DES VARIABLES D'ENVIRONNEMENT
# ============================================================================

def check_env_vars():
    print_section("1. VÉRIFICATION DES VARIABLES D'ENVIRONNEMENT")
    
    required_vars = {
        "Airtable": [
            "AIRTABLE_BASE_ID",
            "AIRTABLE_API_KEY",
            "AIRTABLE_PLAYERS_TABLE",
            "AIRTABLE_ATTEMPTS_TABLE",
            "AIRTABLE_PAYLOADS_TABLE",
            "AIRTABLE_ANSWERS_TABLE",
            "AIRTABLE_FEEDBACK_TABLE",
        ],
        "Notion": [
            "NOTION_API_KEY",
            "NOTION_EXAMS_DB_ID",
        ]
    }
    
    all_ok = True
    
    for service, vars_list in required_vars.items():
        print(f"\n{service}:")
        for var in vars_list:
            value = os.getenv(var)
            if value:
                masked = value[:8] + "..." if len(value) > 8 else value
                print_success(f"{var} = {masked}")
            else:
                print_error(f"{var} = NON DÉFINI")
                all_ok = False
    
    return all_ok

# ============================================================================
# 2. TEST CONNEXION AIRTABLE
# ============================================================================

def test_airtable_connection():
    print_section("2. TEST CONNEXION AIRTABLE")
    
    # Utiliser CORE base pour les tests de joueurs
    base_id = os.getenv("AIRTABLE_CORE_BASE_ID") or os.getenv("AIRTABLE_BASE_ID")
    api_key = os.getenv("AIRTABLE_API_KEY")
    
    if not base_id or not api_key:
        print_error("Variables Airtable manquantes")
        return False
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Test sur la table players (dans CORE base)
    table_name = os.getenv("AIRTABLE_PLAYERS_TABLE", "players")
    print_info(f"Test sur base CORE: {base_id[:10]}...")
    url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
    
    try:
        response = requests.get(
            url,
            headers=headers,
            params={"maxRecords": 1},
            timeout=10
        )
        
        if response.status_code == 200:
            print_success(f"Connexion Airtable OK (table: {table_name})")
            data = response.json()
            print_info(f"Nombre de records: {len(data.get('records', []))}")
            return True
        else:
            print_error(f"Erreur Airtable: {response.status_code}")
            print_error(f"Message: {response.text[:200]}")
            return False
            
    except Exception as e:
        print_error(f"Exception Airtable: {e}")
        return False

# ============================================================================
# 3. TEST CONNEXION NOTION
# ============================================================================

def test_notion_connection():
    print_section("3. TEST CONNEXION NOTION")
    
    api_key = os.getenv("NOTION_API_KEY")
    db_id = os.getenv("NOTION_EXAMS_DB_ID")
    
    if not api_key or not db_id:
        print_error("Variables Notion manquantes")
        return False
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    # Récupérer les infos de la database
    url = f"https://api.notion.com/v1/databases/{db_id}"
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            print_success("Connexion Notion OK")
            data = response.json()
            print_info(f"Database: {data.get('title', [{}])[0].get('plain_text', 'N/A')}")
            
            # Vérifier les propriétés
            props = data.get('properties', {})
            print_info(f"Nombre de propriétés: {len(props)}")
            
            required_props = [
                "Joueur ID", "Mode", "Score", "Statut", "Date/Heure",
                "Temps total (s)", "Temps total (mm:ss)", "Réponses",
                "Commentaires", "Version Bot", "Profil joueur"
            ]
            
            missing = []
            for prop in required_props:
                if prop in props:
                    print_success(f"  - {prop}")
                else:
                    print_error(f"  - {prop} (MANQUANT)")
                    missing.append(prop)
            
            if missing:
                print_warning(f"Propriétés manquantes: {', '.join(missing)}")
                return False
            
            return True
        else:
            print_error(f"Erreur Notion: {response.status_code}")
            print_error(f"Message: {response.text[:200]}")
            return False
            
    except Exception as e:
        print_error(f"Exception Notion: {e}")
        return False

# ============================================================================
# 4. TEST D'ÉCRITURE AIRTABLE
# ============================================================================

def test_airtable_write():
    print_section("4. TEST D'ÉCRITURE AIRTABLE")
    
    # Utiliser CORE base pour l'écriture de joueurs
    base_id = os.getenv("AIRTABLE_CORE_BASE_ID") or os.getenv("AIRTABLE_BASE_ID")
    api_key = os.getenv("AIRTABLE_API_KEY")
    table_name = os.getenv("AIRTABLE_PLAYERS_TABLE", "players")
    
    if not base_id or not api_key:
        print_error("Variables Airtable manquantes")
        return False
    
    print_info(f"Test d'écriture sur base CORE: {base_id[:10]}...")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
    
    # Créer un joueur de test
    test_id = f"TEST_{int(datetime.now(timezone.utc).timestamp())}"
    payload = {
        "fields": {
            "telegram_user_id": test_id,
        }
    }
    
    try:
        print_info(f"Création d'un joueur test: {test_id}")
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if response.status_code in [200, 201]:
            data = response.json()
            record_id = data.get("id")
            print_success(f"Écriture Airtable OK (record: {record_id})")
            
            # Nettoyer: supprimer le record de test
            delete_url = f"{url}/{record_id}"
            delete_response = requests.delete(delete_url, headers=headers, timeout=10)
            
            if delete_response.status_code == 200:
                print_success("Nettoyage du record test OK")
            else:
                print_warning(f"Impossible de supprimer le record test: {record_id}")
            
            return True
        else:
            print_error(f"Erreur écriture Airtable: {response.status_code}")
            print_error(f"Message: {response.text[:200]}")
            return False
            
    except Exception as e:
        print_error(f"Exception écriture Airtable: {e}")
        return False

# ============================================================================
# 5. TEST D'ÉCRITURE NOTION
# ============================================================================

def test_notion_write():
    print_section("5. TEST D'ÉCRITURE NOTION")
    
    api_key = os.getenv("NOTION_API_KEY")
    db_id = os.getenv("NOTION_EXAMS_DB_ID")
    
    if not api_key or not db_id:
        print_error("Variables Notion manquantes")
        return False
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    url = "https://api.notion.com/v1/pages"
    
    # Créer une page de test
    test_id = f"TEST_{int(datetime.now(timezone.utc).timestamp())}"
    now = datetime.now(timezone.utc).isoformat()
    
    payload = {
        "parent": {"database_id": db_id},
        "properties": {
            "Joueur ID": {
                "title": [{"type": "text", "text": {"content": test_id}}]
            },
            "Mode": {
                "select": {"name": "Test"}
            },
            "Score": {
                "number": 10
            },
            "Statut": {
                "select": {"name": "En cours"}
            },
            "Date/Heure": {
                "date": {"start": now}
            },
            "Temps total (s)": {
                "number": 120
            },
            "Temps total (mm:ss)": {
                "rich_text": [{"type": "text", "text": {"content": "02:00"}}]
            },
            "Réponses": {
                "rich_text": [{"type": "text", "text": {"content": "Test"}}]
            },
            "Commentaires": {
                "rich_text": [{"type": "text", "text": {"content": "Test integration"}}]
            },
            "Version Bot": {
                "rich_text": [{"type": "text", "text": {"content": "test_v1"}}]
            },
            "Profil joueur": {
                "select": {"name": "Oracle en Devenir"}
            },
            "Nom utilisateur": {
                "rich_text": [{"type": "text", "text": {"content": "-"}}]
            },
            "Username Telegram": {
                "rich_text": [{"type": "text", "text": {"content": "-"}}]
            },
        }
    }
    
    try:
        print_info(f"Création d'une page test: {test_id}")
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if response.status_code in [200, 201]:
            data = response.json()
            page_id = data.get("id")
            print_success(f"Écriture Notion OK (page: {page_id})")
            
            # Note: on ne supprime pas la page test car Notion n'a pas d'endpoint DELETE simple
            # Tu devras la supprimer manuellement ou via l'interface
            print_warning(f"⚠️  Pense à archiver la page test dans Notion: {page_id}")
            
            return True
        else:
            print_error(f"Erreur écriture Notion: {response.status_code}")
            print_error(f"Message: {response.text[:500]}")
            return False
            
    except Exception as e:
        print_error(f"Exception écriture Notion: {e}")
        return False

# ============================================================================
# 6. TEST DU SERVEUR LOCAL (si disponible)
# ============================================================================

def test_local_server():
    print_section("6. TEST DU SERVEUR LOCAL")
    
    server_url = os.getenv("SERVER_URL", "http://localhost:5000")
    
    # Test /health
    try:
        print_info(f"Test de {server_url}/health")
        response = requests.get(f"{server_url}/health", timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            print_success(f"Serveur OK - Version: {data.get('version', 'N/A')}")
            print_info(f"Airtable: {data.get('airtable_ok', False)}")
            return True
        else:
            print_error(f"Serveur erreur: {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        print_warning("Serveur local non démarré (normal si pas en dev)")
        return None
    except Exception as e:
        print_error(f"Exception serveur: {e}")
        return False

# ============================================================================
# MAIN
# ============================================================================

def main():
    print("\n" + "="*60)
    print(f"{BLUE}🔮 VELVET ORACLE - TEST D'INTÉGRATION{RESET}")
    print("="*60)
    
    results = {
        "env_vars": check_env_vars(),
        "airtable_connection": test_airtable_connection(),
        "notion_connection": test_notion_connection(),
        "airtable_write": test_airtable_write(),
        "notion_write": test_notion_write(),
        "local_server": test_local_server(),
    }
    
    # Résumé
    print_section("RÉSUMÉ")
    
    for test_name, result in results.items():
        if result is True:
            print_success(f"{test_name}")
        elif result is False:
            print_error(f"{test_name}")
        elif result is None:
            print_warning(f"{test_name} (non applicable)")
    
    # Conclusion
    failed = [k for k, v in results.items() if v is False]
    
    if not failed:
        print(f"\n{GREEN}{'='*60}")
        print("✅ TOUS LES TESTS SONT PASSÉS!")
        print(f"{'='*60}{RESET}\n")
        return 0
    else:
        print(f"\n{RED}{'='*60}")
        print(f"❌ {len(failed)} TEST(S) EN ÉCHEC:")
        for test in failed:
            print(f"   - {test}")
        print(f"{'='*60}{RESET}\n")
        return 1

if __name__ == "__main__":
    sys.exit(main())
