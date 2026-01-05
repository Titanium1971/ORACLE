# VELVET ORACLE — BASE CORE — STRUCTURE COMPLÈTE
## Base ID: appbAWvGXvRYj

================================================================================
## TABLE 1: players
================================================================================

### Champs principaux (visibles image 1-3):
- Name (Formula/Autonumber)
- telegram_user_id (Single line text) **[CLÉ PRIMAIRE]**
- telegram_username (Single line text)
- telegram_first_name (Single line text)
- telegram_last_name (Single line text)
- language (Single select: FR, EN, ES, DE, IT)
- country (Single line text)
- city (Single line text)
- is_beta_tester (Checkbox)
- created_at (Date with time)
- cognitive_signature (Single select: Stratège Silencieux, Esprit Fulgurant, Explorateur Patient, Éclaireur Instinctif, Oracle en Devenir)
- rituel_attempts (Link to rituel_attempts) [Multiple records]
- rituel_attempts 2 (Rollup/Count)
- rituel_feedback (Link to rituel_feedback) [Multiple records]
- rituel_feedback 2 (Rollup/Count)
- status (Single select: Pending, Active, Closed)
- access_granted (Checkbox)
- access_granted_until (Date - format Local DD/MM/YYYY)
- rituels_completed_count (Number)
- last_rituel_completed_at (Date with time)
- is_inactive (Checkbox)

### Champs avancés (analytics - image 3):
- avg_score_3 (Number)
- avg_time_3 (Number/Duration)
- max_time_3 (Number/Duration)
- eligible_beta (Checkbox)
- action_to_take (Single select: PENDING, EXTEND, GRANT, CLOSE)
- days_since_ref (Number)
- action_processed (Checkbox)
- action_processed_at (Date)
- decision_status (Single select: REQUESTED, autres...)
- READY_FOR_DECISION (Number)

### Vues Airtable:
- Players_Beta_State (default)
- BETA_PENDING
- BETA_ACTIVE
- BETA_CLOSED
- NEEDS_DECISION

### Joueurs de test actuels:
- Alex — FR (123456789, @alexjohn)
- Sofia — EN (987654321, @sofia_london)
- Cyril — FR (5052599647, KDT*1971)
- TEST_GRANT (900001)
- TEST_EXTEND (900002)
- TEST_GRANT_OK (900003)
- TEST_CLOSE_IMMEDIATE (900004)
- TEST_PLAYER_001
- LOCAL_TEST_001

================================================================================
## TABLE 2: rituel_attempts
================================================================================

### Champs principaux (images 4-6):
- Name (Formula - auto-généré ex: "EX-Alex-20251208-09-1")
- player (Link to players) **[RELATION]**
- mode (Single select: PROD, TEST)
- status (Single select: Completed, Pending, In progress, Aborted, Blocked)
- score_raw (Number)
- score_max (Number)
- score_percent (Number/Formula)
- time_total_seconds (Number)
- time_formatted (Text - format mm:ss)
- signature_cognitive (Text)
- started_at (Date with time, ISO format)
- completed_at (Date with time, ISO format)

### Champs calculés/analytics:
- pass_threshold (Number)
- result (Single select: Admis, Refusé, Élite, Non Noté, À revoir)
- completed_at (Date)
- duration_pretty (Formula - durée formatée)
- autonumber (Number auto)
- status_technique (Single select: INIT, EN_COURS, TERMINE...)
- retry_allowed (Number)
- retry_used (Number)
- From field:retry_vf_attempt (?)
- retry_token (Number)
- completed_flag (Checkbox)
- players (Link rollup/formula)
- players 2 (Count)

### Relations:
- answer_logs (Link to rituel_answers) [Multiple]
- feedback (Link to rituel_feedback) [Multiple]
- feedback 2 (Count)
- raw_payload (Link to rituel_webapp_payloads) [Single]
- attempt_id (Text - identifiant unique)
- exam_label (Formula)

### Vues:
- Exams — Résultats Premium
- Exams — Kanban Résultats
- Exams — À vérifier (anomalies)

================================================================================
## TABLE 3: rituel_answers
================================================================================

### Champs (image 7):
- Name (Formula - ex: "EX-Alex-20251209-1 — Q1")
- exam (Link to rituel_attempts) **[RELATION]**
- question_index (Number - 1 à 15)
- question_id (Single line text - ex: "0203-01-01")
- domain (Single select: Cinéma & Audiovisuel, Psychologie & Comportements humains, Arts & Littératures, Musiques & Arts sonores, Sciences & Nature, Technologies & Future Thinking, Mythologies & Religions anciennes, Géographie & Cultures du Monde, Sports, Jeux & Compétitions, Civilisations & Histoire humaine)
- level (Single select: N3, N4, N5...)
- answer_given (Single select: A, B, C, D)
- is_correct (Checkbox)
- time_spent_seconds (Number)
- was_timeout (Checkbox)

### Vues:
- Grid view (default)

================================================================================
## TABLE 4: rituel_feedback
================================================================================

### Champs principaux (images 8-10):
- Name (Formula - ex: "FB-Alex — EN-20251208-1")
- exam (Link to rituel_attempts) **[RELATION]**
- player (Link to players) **[RELATION]**
- exam_label (Lookup from exam)
- rating (Single select: 1-5)
- tags (Multiple select: Design, Temps, Difficulté, Expérience Globale, Bug, UX, Lisibilité, Technique, Ergonomie, Performance)
- comment_text (Long text)
- comment_length (Number - calculated)
- created_at (Date with time - ISO format)
- raw_payload (Link to rituel_webapp_payloads)

### Champs analytics (images 9-10):
- feedback_id (Text - unique ID)
- created_at_formula (Formula)
- autonumber (Number)
- player_name (Lookup/Formula)
- rating_num (Number)
- is_negative (Checkbox)
- has_comment (Checkbox)
- tag_primary (Single select)
- created_date_only (Date only)
- weekday (Single select: Tuesday, Wednesday, Sunday...)
- tag_count (Number)
- has_tags (Checkbox)
- urgency_score (Number)

### Vues:
- Feedback — Premium Review
- Feedback — Kanban Qualité
- Feedback — Insights

================================================================================
## TABLE 5: rituel_webapp_payloads
================================================================================

### Champs (image 11):
- telegram_user_id (Single line text) **[CLÉ]**
- mode (Single select: RITUAL, LOCAL_FULL, autres...)
- score (Number)
- total (Number)
- time_total_seconds (Number)
- time_formatted (Text mm:ss)
- feedback_text (Long text)
- analysis_mode (Single select: local, autres...)
- answers_json (Long text - JSON array)
- raw_json (Long text - payload complet)
- Date de création (Date with time)
- session_id (Text - ex: "SESSION-001", "SESSION_LOCAL_001")

### Vues:
- Grid view (default)

================================================================================
## RELATIONS ENTRE TABLES
================================================================================

players (1) ←→ (N) rituel_attempts
    ↓
players (1) ←→ (N) rituel_feedback
    ↓
rituel_attempts (1) ←→ (N) rituel_answers
    ↓
rituel_attempts (1) ←→ (N) rituel_feedback
    ↓
rituel_attempts (1) ←→ (1) rituel_webapp_payloads

================================================================================
## CHAMPS OBLIGATOIRES POUR SERVER.PY
================================================================================

### players (minimum pour upsert):
- telegram_user_id (string) **REQUIRED**
- created_at (date) - auto si absent

### rituel_attempts (minimum pour /ritual/start):
- player (link array) **REQUIRED**
- started_at (date ISO) **REQUIRED**
- mode (select: PROD/TEST) **REQUIRED**
- status (select) **REQUIRED**
- status_technique (select: INIT) **REQUIRED**

### rituel_attempts (pour /ritual/complete):
- completed_at (date ISO)
- status (select: Completed)
- score_raw (number)
- score_max (number)
- time_total_seconds (number)
- result (select: Admis/Refusé)

### rituel_answers (pour logging):
- player (link array)
- exam (link array)
- question_id (string)
- selected_index (number) ou answer_given (A/B/C/D)
- correct_index (number)
- is_correct (checkbox)
- time_seconds (number)
- utc (date ISO)

### rituel_feedback (pour logging):
- player (link array)
- exam (link array)
- text (long text)
- rating (number)
- utc (date ISO)

### rituel_webapp_payloads (pour logging brut):
- telegram_user_id (string)
- payload (long text JSON)
- utc (date ISO)

================================================================================
## SINGLE SELECT OPTIONS (pour validation)
================================================================================

### mode (rituel_attempts):
- PROD
- TEST

### status (rituel_attempts):
- Completed
- Pending
- In progress
- Aborted
- Blocked

### result (rituel_attempts):
- Admis (vert)
- Refusé (rouge)
- Élite (bleu)
- Non Noté (gris)
- À revoir (orange)

### rating (rituel_feedback):
- 1 (rouge foncé)
- 2 (rouge)
- 3 (orange)
- 4 (vert clair)
- 5 (vert foncé)

### tags (rituel_feedback - Multiple select):
- Design
- Temps
- Difficulté
- Expérience Globale
- Bug
- UX
- Lisibilité
- Technique
- Ergonomie
- Performance

### language (players):
- FR
- EN
- ES
- DE
- IT

### status (players):
- Pending
- Active
- Closed

### cognitive_signature (players):
- Stratège Silencieux
- Esprit Fulgurant
- Explorateur Patient
- Éclaireur Instinctif
- Oracle en Devenir

### domain (rituel_answers):
- Cinéma & Audiovisuel
- Psychologie & Comportements humains
- Arts & Littératures
- Musiques & Arts sonores
- Sciences & Nature
- Technologies & Future Thinking
- Mythologies & Religions anciennes
- Géographie & Cultures du Monde
- Sports, Jeux & Compétitions
- Civilisations & Histoire humaine

### level (rituel_answers):
- N1
- N2
- N3
- N4
- N5

### answer_given (rituel_answers):
- A
- B
- C
- D

================================================================================
## NOTES IMPORTANTES POUR L'INTÉGRATION
================================================================================

1. **Base QUESTIONS** (appz7jqc...) = Lecture seule des 14,000 questions
2. **Base CORE** (appbAWvGXvRYj) = Écriture de toutes les données joueurs

3. Le serveur doit TOUJOURS utiliser `AIRTABLE_CORE_BASE_ID` pour:
   - players
   - rituel_attempts
   - rituel_answers
   - rituel_feedback
   - rituel_webapp_payloads

4. Format dates: ISO 8601 avec timezone UTC
   Exemple: "2025-12-09T15:49:00Z"

5. Les champs "Name" dans toutes les tables sont des FORMULAS auto-générées
   → Ne JAMAIS essayer de les écrire

6. Les links entre tables utilisent des ARRAYS de record IDs:
   Exemple: {"player": ["recXXXXXXXXXXXXXX"]}

7. Status workflow typique:
   /ritual/start → status="STARTED", status_technique="INIT"
   /ritual/complete → status="COMPLETED", result="Admis/Refusé"

================================================================================
## FIN DU DOCUMENT
================================================================================

Base documentée le: 2026-01-05
Environnement: Production Replit
Prêt pour intégration avec server.py v0.9+
