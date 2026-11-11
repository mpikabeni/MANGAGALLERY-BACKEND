# Nexa Manga — Backend (Flask + PostgreSQL)

Un projet **Nexa** · canal obligatoire : **@Nexa_CG** · version **V2.05**

## Liens du projet
- Mini app (Netlify) : https://mangagalleryzone.netlify.app
- API (Render) : https://mangagallery-backend-8d98.onrender.com  — santé : `/health`, config publique : `/api/config`

## Données stockées côté serveur (V2.05)
Favoris, reprise de lecture (page par chapitre, chapitres lus) et préférences (langue, thème, mode de lecteur) sont enregistrés
dans PostgreSQL, donc synchronisés entre appareils : `/api/library/favorites`, `/history`, `/progress`, `/prefs`, `/summary`.
Les trois tables (`favorites`, `reading_progress`, `user_prefs`) sont **créées automatiquement au démarrage** (sans toucher aux données existantes).

## Sécurité en bref
- Connexion **uniquement par Telegram** : le backend vérifie la signature `initData` (HMAC) avec le token du bot. Un faux `telegram_id` est refusé.
- **Canal obligatoire** : sans avoir rejoint `@Nexa_CG`, `/api/auth/telegram` répond `403 NOT_MEMBER` (le bot applique la même règle avant d'afficher le mini app).
- **Un seul admin** : le compte dont l'identifiant Telegram vaut `ADMIN_TELEGRAM_ID`. Plus aucune règle « id == 1 ». Tout autre compte portant le rôle `admin` est rétrogradé à la connexion suivante.
- Le compte admin ne peut être ni modifié (statut/rôle), ni désactivé, ni supprimé via l'API.
- Connexion par mot de passe **désactivée** par défaut (`ADMIN_PASSWORD_LOGIN=false`) ; si activée : limitée aux tentatives, sans journaliser les mots de passe.
- Webhook Telegram : secret **obligatoire**, comparaison à temps constant.
- Contenu (mangas, chapitres, commentaires) réservé aux utilisateurs connectés ; seuls les contenus `public/published` sont visibles par les non-admins.
- Textes utilisateurs nettoyés (pas de HTML dans les noms), URLs d'images limitées à http(s), uploads vérifiés avec Pillow et renommés aléatoirement.

## Déploiement (Render)
0. **Python 3.12 obligatoire** : sur Render, ajoute la variable `PYTHON_VERSION=3.12.11` (par défaut Render prend 3.14, pour lequel `psycopg-binary` et `Pillow` n'ont pas de version précompilée et le build échoue).
1. Créer une base PostgreSQL et un *Web Service* sur ce dossier (`render.yaml` fourni).
2. Variables d'environnement : voir `.env.example` (`SECRET_KEY`, `JWT_SECRET_KEY`, `TELEGRAM_WEBHOOK_SECRET` : 48+ caractères aléatoires).
3. **Votre identifiant Telegram** (numérique, via @userinfobot) → `ADMIN_TELEGRAM_ID`.
4. Premier démarrage : `AUTO_CREATE_TABLES=true`, puis remettre `false`.
5. Ajouter le bot comme **administrateur du canal @Nexa_CG** (sinon Telegram refuse la liste des membres et personne ne passe).
6. Enregistrer le webhook : `python bot.py --webhook` puis `python bot.py --setup` (commandes + bouton de menu). `python bot.py --info` vérifie le bot et le canal.
7. Ouvrez le bot depuis votre compte Telegram : votre compte admin est créé automatiquement.

## Local
```
pip install -r requirements.txt
cp .env.example .env   # remplir, APP_ENV=development
python main.py          # API sur :5000
python bot.py           # bot en long polling (sans webhook)
```

## Notes
- Limiteur de débit en mémoire (par processus gunicorn).
- Le disque de Render gratuit est éphémère : utilisez des URLs d'images externes pour les pages de chapitres, ou un disque persistant sur `MEDIA_UPLOAD_DIR`.
- Pas de migrations Alembic fournies : `flask --app main init-db` crée les tables. Recommandé (anti-doublons de pseudo) :
  `CREATE UNIQUE INDEX IF NOT EXISTS ux_users_username_lower ON users (lower(username));`
