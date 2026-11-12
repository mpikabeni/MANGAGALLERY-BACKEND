# Manga Gallery FR — Backend (Flask + PostgreSQL)

Un projet **Nexa** · canal : **@Nexa_CG** · version **Finale**

## Liens du projet
- Mini app (Netlify) : https://mangagalleryzone.netlify.app
- API (Render) : https://mangagallery-backend-8d98.onrender.com — santé : `/health`, config publique : `/api/config`
- **Diagnostic du bot** : https://mangagallery-backend-8d98.onrender.com/api/telegram/health

## Deux espaces
- **Galerie** (normale) : manga, webtoon, bande dessinée.
- **La Sainte Culture** (18+) : webtoon et bande dessinée adultes uniquement. Publiée par l'administrateur depuis
  `admin/mangas.html` (onglet « La Sainte Culture »). Côté serveur, chaque manga a une `section` (`normal` ou
  `sainte_culture`) et un `content_type` (`manga`, `webtoon`, `comic`). Le serveur refuse `manga` dans La Sainte Culture.
- L'accès est **verrouillé côté serveur** : tant que l'utilisateur n'a pas confirmé avoir 18 ans ou plus
  (`POST /api/auth/adult-confirm`, retirable avec `DELETE`), les listes, fiches, chapitres, favoris, historique et
  commentaires de La Sainte Culture répondent `403 ADULT_REQUIRED` ou sont simplement absents. L'administrateur y a toujours accès.

## /start ne répond pas ? (corrigé)
Causes corrigées dans cette version :
1. Le secret du webhook généré par Render contient souvent `+ / =`, que Telegram **refuse** : le webhook n'était jamais
   enregistré. Le serveur dérive maintenant un jeton compatible (SHA-256 hexadécimal).
2. Le webhook n'était enregistré que si quelqu'un lançait `python bot.py --webhook` à la main. Le serveur le fait
   désormais **tout seul à chaque démarrage** (webhook + commandes + bouton de menu).
3. Les tables n'étaient créées qu'avec `AUTO_CREATE_TABLES=true` : sur une base neuve, la connexion de la mini app
   répondait 500. Elles sont maintenant créées/complétées automatiquement (sans toucher aux données existantes).

Si le bot reste muet, ouvrez `/api/telegram/health` : il liste les problèmes (webhook, token, bot non administrateur du canal…).

## Sécurité en bref
- Connexion **uniquement par Telegram** : le backend vérifie la signature `initData` (HMAC) avec le token du bot.
- **Canal obligatoire** : sans avoir rejoint `@Nexa_CG`, `/api/auth/telegram` répond `403 NOT_MEMBER`.
  `REQUIRED_CHANNEL=off` désactive cette porte (utile tant que le bot n'est pas administrateur du canal).
- **Un seul admin** : le compte dont l'identifiant Telegram vaut `ADMIN_TELEGRAM_ID`.
- Webhook Telegram : secret **obligatoire**, comparaison à temps constant.
- Contenu réservé aux utilisateurs connectés ; seuls les contenus `public/published` sont visibles par les non-admins.
- Textes utilisateurs nettoyés, URLs d'images limitées à http(s).

## Déploiement (Render)
0. Démarrage : `gunicorn --workers 2 --threads 4 --timeout 300 main:app` (les gros PDF demandent du temps). **Python 3.12 obligatoire** : variable `PYTHON_VERSION=3.12.11` (déjà dans `render.yaml`).
1. Créer une base PostgreSQL et un *Web Service* sur ce dossier (`render.yaml` fourni).
2. Variables : voir `.env.example`. Obligatoires : `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `PUBLIC_BACKEND_URL`,
   `TELEGRAM_MINI_APP_URL`, `ADMIN_TELEGRAM_ID` (votre identifiant numérique, via @userinfobot), `CORS_ORIGINS`.
3. Ajouter le bot comme **administrateur du canal @Nexa_CG** (sinon Telegram refuse la liste des membres).
4. Déployer. Au démarrage le serveur crée les tables, ajoute les colonnes manquantes et configure le bot.
5. Ouvrez le bot depuis votre compte Telegram : votre compte admin est créé automatiquement.

## Local
```
pip install -r requirements.txt
cp .env.example .env   # remplir, APP_ENV=development
python main.py          # API sur :5000
python bot.py           # bot en long polling (sans webhook)
```

## Notes
- Limiteur de débit en mémoire (par processus gunicorn).
- **Téléversement par l'administrateur** (`/api/uploads/…`) : couvertures, bannières et chapitres complets s'envoient directement
  depuis l'admin, sans lien. Formats de chapitre : **PDF, CBZ, ZIP, CBT** et images (jpg, png, webp, gif). Un CBR qui est en
  réalité un ZIP est accepté ; un vrai RAR ou 7z doit être converti en CBZ. Les images sont optimisées (JPEG, 1600 px max) et
  **stockées dans PostgreSQL** (table `media_blobs`) : elles survivent aux redéploiements de Render. 150 Mo maximum par envoi,
  400 pages maximum par envoi. Les images d'un chapitre ou d'un titre supprimé sont libérées automatiquement.
- Les liens d'images (https) restent possibles en complément.
