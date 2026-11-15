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

## Import MangaDex (fiches + chapitres)
Admin → **Importer** : recherche un titre sur MangaDex (API publique, sans clé), choisis la section (Galerie ou La Sainte Culture) et le type,
puis « Importer fiche + chapitres » crée le titre (couverture copiée dans la base) et ses chapitres lisibles dans la langue choisie.
- Les **pages ne sont pas copiées** : le serveur les relaie depuis MangaDex à chaque lecture (`/api/mangadex/page/…`), avec des liens signés valables 6 h,
  délivrés uniquement par les routes déjà protégées (visibilité + 18+). MangaDex interdit l'affichage direct depuis un navigateur.
- **Conditions MangaDex** : créditer MangaDex et les groupes de traduction (fait dans la fiche et le lecteur), aucune publicité ni service payant,
  honorer les demandes de retrait (supprimer le titre dans Mangas). Limite ~5 requêtes/s : un seul import à la fois.
- Un titre classé adulte par MangaDex (erotica / pornographic) n'est importable que dans **La Sainte Culture**, et uniquement en webtoon ou bande dessinée.
- « Mettre à jour » (icône ↻ dans Mangas) récupère les nouveaux chapitres d'un titre déjà importé.

## Import intelligent (VF, chapitres complets, annonces)
- **Aperçu avant publication** : pour chaque titre trouvé, l'admin affiche « Chapitres 1 → 12 · 12 chapitre(s) · ✓ complet » (une requête
  légère `/manga/{id}/aggregate` par titre, en français par défaut). Les trous sont listés (« ⚠ 2 manquants (4, 7) »).
- **Filtres** : « Séries terminées seulement » (filtre MangaDex) et « Seulement si tous les chapitres existent dans cette langue ». Un titre à
  0 chapitre dans la langue choisie est masqué et refusé à l'import.
- **Pas de chapitre 0** : les chapitres sont numérotés à partir du premier qui existe (1 → 12…). Chapitre 0 et chapitres sans numéro sont ignorés ;
  la création manuelle refuse aussi un numéro ≤ 0. Les lecteurs ne voient **jamais** un titre qui n'a aucun chapitre publié.
- **Synopsis VF** : celui de MangaDex s'il existe ; sinon traduction automatique gratuite depuis l'anglais (MyMemory, 5 000 caractères/jour sans
  e-mail, 50 000 avec `MYMEMORY_EMAIL`), signalée « traduit automatiquement » ; sinon l'anglais.
- **Annonces** : quand un titre public reçoit son **premier chapitre publié** (import ou publication manuelle), chaque utilisateur actif reçoit
  une notification dans l'application et un message du bot (couverture + bouton « Lire maintenant » qui ouvre directement la fiche). Une seule
  annonce par titre (`announced_at`). Les titres de La Sainte Culture ne sont annoncés qu'aux utilisateurs ayant confirmé avoir 18 ans.
  Case « Prévenir les utilisateurs » à décocher pour publier sans annonce. Les utilisateurs qui n'ont jamais démarré le bot reçoivent seulement
  la notification dans l'application.

## « Bientôt » (titres à venir)
- Page Importer → case **Mode « Bientôt »** : la recherche n'est plus limitée aux titres déjà traduits ; seuls les titres **pas encore complets** en français
  s'affichent (« 0 chapitre » ou « 1 → 3 ») avec le bouton « Ajouter à Bientôt ». On crée alors la fiche (couverture, synopsis VF) **sans chapitres**.
- Dans l'application : rangée « 🕒 Bientôt disponibles » sur l'accueil (et dans La Sainte Culture pour les titres adultes), badge « Bientôt » sur la couverture,
  fiche sans chapitres avec explication. Le cœur sert d'alerte (« Tu seras prévenu à sa sortie »).
- **Sortie automatique** : toutes les `COMING_SOON_CHECK_HOURS` heures (6 par défaut, 0 = jamais) et avec le bouton « Vérifier maintenant », chaque titre « Bientôt »
  venant de MangaDex est contrôlé ; dès que la série est **terminée et complète en VF** (aucun numéro manquant), tous les chapitres sont importés, le titre quitte
  « Bientôt » et l'annonce part (notification + bot). Render gratuit s'endort : la vérification tourne quand le serveur est éveillé, sinon utilise le bouton.
- Création manuelle : case « Bientôt » dans « Publier un titre » ; le titre sort tout seul au premier chapitre publié.
