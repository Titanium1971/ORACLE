# Test d'Intégration Velvet Oracle

Script de test complet pour vérifier l'intégration Airtable + Notion.

## Installation

```bash
pip install -r requirements_test.txt
```

## Variables d'Environnement Requises

Crée un fichier `.env` avec:

```bash
# Airtable
AIRTABLE_BASE_ID=appXXXXXXXXXXXXXX
AIRTABLE_API_KEY=patXXXXXXXXXXXXXX
AIRTABLE_PLAYERS_TABLE=players
AIRTABLE_ATTEMPTS_TABLE=rituel_attempts
AIRTABLE_PAYLOADS_TABLE=rituel_webapp_payloads
AIRTABLE_ANSWERS_TABLE=rituel_answers
AIRTABLE_FEEDBACK_TABLE=rituel_feedback

# Notion
NOTION_API_KEY=secret_XXXXXXXXXXXXXXXXXXXXXXXXXXXX
NOTION_EXAMS_DB_ID=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX

# Optionnel: pour tester le serveur local
SERVER_URL=http://localhost:5000
```

## Lancement

```bash
python3 test_integration.py
```

## Ce Que le Script Teste

### 1. Variables d'Environnement
✅ Vérifie que toutes les vars sont définies

### 2. Connexion Airtable
✅ Test de lecture sur la table `players`
✅ Vérifie l'authentification

### 3. Connexion Notion
✅ Test de lecture de la database
✅ Vérifie toutes les propriétés requises

### 4. Écriture Airtable
✅ Crée un record de test
✅ Le supprime après (nettoyage auto)

### 5. Écriture Notion
✅ Crée une page de test
⚠️  Note: la page reste (suppression manuelle requise)

### 6. Serveur Local (optionnel)
✅ Test du endpoint `/health`

## Résultats

Le script affiche:
- ✅ Tests passés en VERT
- ❌ Tests échoués en ROUGE
- ⚠️  Warnings en JAUNE
- ℹ️  Infos en BLEU

## Sortie de Code

- `0` = Tous les tests passés
- `1` = Au moins un test échoué

## Problèmes Courants

### Erreur 401 Airtable
→ Vérifie `AIRTABLE_API_KEY` (doit commencer par `pat`)

### Erreur 404 Airtable
→ Vérifie `AIRTABLE_BASE_ID` et noms de tables

### Erreur 401 Notion
→ Vérifie `NOTION_API_KEY` (doit commencer par `secret_`)

### Propriétés Notion manquantes
→ Va dans Notion et ajoute les champs requis à ta database

### Serveur local non accessible
→ Normal si tu n'as pas lancé le serveur en dev
→ Lance `RUN_LOCAL_SERVER=1 python3 server.py` pour tester
