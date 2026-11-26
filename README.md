# TinyInsta passe-t-elle à l'échelle ?

Campagne de mesures, projet Données massives et Cloud, édition 2026.
Rendu individuel · Hani Rahmoune · novembre 2026

- **Application déployée (version par défaut)** : https://tinyinsta-b.ew.r.appspot.com
- **Sujet** : [SUJET.md](SUJET.md) · Outils fournis : [TOOLS.md](TOOLS.md) (README d'origine du dépôt), [bench/README.md](bench/README.md)

**En résumé**

- **Données U et P :** TinyInsta passe à l'échelle. Multiplier U ou P par 100 ne change le temps serveur que de 2 % (U) et de 14 % (P).
- **Données F :** elle ne passe pas à l'échelle. Le temps est stable jusqu'à F = 25, puis il est multiplié par 17,6 entre F = 25 et F = 30, et croît ensuite linéairement. La cause, mesurée, est que Datastore refuse un filtre `IN` de plus de 30 valeurs. L'application avale l'erreur et interroge alors les auteurs un par un.
- **Ressources :** elle passe à l'échelle, avec ×2,30 puis ×3,67 de débit maximal pour 2 puis 4 instances. Une instance plafonne à ~24 timelines/s, et ce plafond est une file d'attente d'App Engine située avant l'instance. Ajouter des threads gunicorn (partie 3) ne la supprime pas.

**Reproduire.** Les 54 journaux Locust sont dans [`raw/`](raw/). Les preuves relevées sur le projet sont dans [`raw/verify/`](raw/verify/). Une commande régénère toutes les figures et tous les CSV :

```sh
make figures          # = python scripts/analyze.py
```

---

## 1. Montage

Toutes les valeurs ci-dessous sont relevées sur le projet par [`bench/verify.py`](bench/verify.py) ([`raw/verify/platform.json`](raw/verify/platform.json), [`raw/verify/version_events.json`](raw/verify/version_events.json)).

| Élément | Valeur |
|---|---|
| Projet GCP | `tinyinsta-b` |
| Région App Engine | `europe-west` (europe-west1), URL en `.ew.r.appspot.com` |
| Base | Firestore en mode Datastore (`DATASTORE_MODE`), emplacement `eur3`, créée le 23/11/2026 à 22:12 UTC |
| Index composite | `Post(author ASC, created DESC)`, état `READY` ([`index.yaml`](index.yaml)) |
| Application | `main.py` non modifié ; `python312`, Flask 3.0.0, gunicorn 21.2.0, google-cloud-datastore 2.19.0 ([`requirements.txt`](requirements.txt)) |
| Version par défaut | `20261123t222612` (100 % du trafic, F1, autoscaling ≤ 10, [`app.yaml`](app.yaml)) |
| Versions mesurées | `fixed1`, `fixed2`, `fixed4` ([`deploy_fixed.sh`](deploy_fixed.sh), B1, manual scaling) ; `fix1` ([`deploy_fix.sh`](deploy_fix.sh), partie 3). Toutes en `--no-promote` |
| Client de charge | **Cloud Shell**, Locust 2.47.0, Python 3.12.3, [`bench/locustfile.py`](bench/locustfile.py) non modifié |
| Alerte budgétaire | `tiny-budget`, 20 USD |
| Orchestration | [`bench/run_part1.sh`](bench/run_part1.sh) (partie 1), [`bench/run_sweep.sh`](bench/run_sweep.sh) (parties 2 et 3, le même script donc le même protocole), [`Makefile`](Makefile) pour les figures. Snakemake était conseillé ; nous avons utilisé des scripts bash. |

**Chronologie (UTC)**, d'après les journaux d'audit et les horodatages des journaux bruts :

| Version | Déployée | Mesures | Arrêtée |
|---|---|---|---|
| `fixed1` | 24/11 13:52 | partie 1 : 24/11 13:56-14:16 · partie 2 (N = 1) : 24/11 14:20-14:51 | **25/11 13:03** |
| `fixed2` | 25/11 13:03 | 25/11 13:04-13:13 | 25/11 13:20 |
| `fixed4` | 25/11 13:20, redéployée à 13:31 | 25/11 13:32-13:41 | 25/11 13:49 |
| `fix1` | 25/11 13:50 | 25/11 13:54-14:03 | 25/11 14:06 |

**Jeux de données.** Les 26 jeux du sujet ont été générés avec [`bench/seed_exact.py`](bench/seed_exact.py) (voir [`bench/seed_order.sh`](bench/seed_order.sh)). Ils totalisent 394 800 entités (`U` entités `User` + `U×P` entités `Post` par jeu). Un écart au sujet : le jeu U = 10 000 porte le préfixe `u10k` au lieu de `u10000`. Le premier seeding de `u10000` a échoué (`DeadlineExceeded`), et sa suppression a elle aussi échoué ([`bench/seed_essai1.sh`](bench/seed_essai1.sh), [`bench/supprimer_jeu.py`](bench/supprimer_jeu.py)). Nous avons donc régénéré le jeu sous un préfixe neuf, avec des paramètres identiques (U = 10 000, P = 20, F = 20). Les entités `u10000_*` partielles restent dans la base. Aucune requête mesurée ne les lit, car une timeline ne lit que les posts des auteurs du jeu interrogé ([`main.py:61-72`](main.py)).

**Traitement des journaux** ([`scripts/analyze.py`](scripts/analyze.py)) : les 10 premières secondes de chaque run sont écartées. Les médianes et les moyennes portent sur les réponses `200`. Le débit vaut `réponses 200 / durée de la fenêtre conservée`. Le nombre d'instances est celui des valeurs distinctes de l'en-tête `X-Instance`.

---

## 2. Résultats

### 2.1 Partie 1 : coût d'une requête

**Protocole** (imposé) : version `fixed1` (1 instance B1, manual scaling), `-u 1` (une requête à la fois), runs de 45 s. U ∈ {100, 1 000, 10 000} avec P = 20, F = 20 ; P ∈ {10, 100, 1 000} avec U = 100, F = 20 ; F ∈ {5, 10, …, 100} avec U = 120, P = 20.

#### Hypothèses (formulées avant la mesure, à la lecture de `main.py`)

`get_timeline` ([`main.py:38-73`](main.py)) lit l'entité `User` par sa clé ([`main.py:43`](main.py)). Il construit ensuite la liste des auteurs `follows = list({*follows, user})` ([`main.py:47`](main.py)), soit F + 1 auteurs. Enfin il lit les 20 posts les plus récents de ces auteurs, servis par l'index `Post(author, created DESC)`.

- **U : aucun effet attendu.** La lecture par clé est un accès direct, et la requête ne parcourt que les entrées d'index des auteurs suivis.
- **P : aucun effet attendu.** L'index est trié par `created DESC` pour chaque auteur, et `limit=20` arrête la lecture après 20 posts.
- **F : coût croissant attendu.** Il faut F + 1 plages d'index à parcourir et à fusionner.
- **Risque relevé dans le code.** Les requêtes sont enveloppées dans des `try / except Exception` ([`main.py:51-58`](main.py) et [`main.py:60-65`](main.py)). Si Datastore refuse la requête, l'erreur est avalée et le code bascule sur un repli : une requête par auteur, exécutées l'une après l'autre ([`main.py:66-72`](main.py)). Aucune erreur HTTP ne le signalerait.

#### Figures

![Fig. 1a](figures/fig1a.png)

*Fig. 1a : temps serveur médian (`Server-Timing`) en fonction de U (P = 20, F = 20) et de P (U = 100, F = 20). Version `fixed1`, 1 requête à la fois. Données : [`figures/fig1a.csv`](figures/fig1a.csv).*

![Fig. 1b](figures/fig1b.png)

*Fig. 1b : temps serveur médian et latence client médiane en fonction de F (U = 120, P = 20, limit = 20). Version `fixed1`, 1 requête à la fois. Les droites sont ajustées séparément de part et d'autre de F = 30. Données : [`figures/fig1b.csv`](figures/fig1b.csv).*

#### Interprétation

**U : hypothèse confirmée.** Le temps serveur médian vaut 30,2 / 30,8 / 30,5 ms pour U = 100 / 1 000 / 10 000. Pour un facteur 100 sur U, l'écart maximal est de 2 %.

**P : hypothèse confirmée.** Le temps serveur médian vaut 30,1 / 28,8 / 32,8 ms pour P = 10 / 100 / 1 000. L'écart maximal est de 14 % pour un facteur 100 sur P, et l'évolution n'est pas monotone.

**F : hypothèse confirmée dans le sens, mais pas dans la forme.** Nous attendions une croissance régulière. La mesure montre deux régimes séparés par une marche :

| F | 5 | 10 | 15 | 20 | 25 | **30** | 50 | 75 | 100 |
|---|---|---|---|---|---|---|---|---|---|
| temps serveur médian (ms) | 29,1 | 29,8 | 30,8 | 31,4 | 32,8 | **577,4** | 908,1 | 1 364,2 | 1 758,9 |
| débit (timelines/s) | 20,8 | 20,8 | 20,7 | 20,5 | 19,9 | **1,6** | 1,0 | 0,7 | 0,6 |

- **F ≤ 25 :** la pente est de 0,18 ms par followee.
- **De F = 25 à F = 30 :** le temps est multiplié par 17,6.
- **F ≥ 30 :** la pente est de 16,85 ms par followee.

**Mécanisme.** [`bench/verify.py`](bench/verify.py) exécute le vrai `get_timeline` de `main.py` contre la base du projet, en comptant les requêtes Datastore et les entités lues ([`raw/verify/reads_per_timeline.csv`](raw/verify/reads_per_timeline.csv)) :

| Jeu | F | Auteurs | Chemin exécuté | Requêtes réussies | Requêtes en échec | Entités lues |
|---|---|---|---|---|---|---|
| `base`, `u100`, `u10k`, `p10`, `p100`, `p1000`, `f05`, `f25` | 5 à 25 | 6 à 26 | `IN` ([`main.py:61-64`](main.py)) | 1 | 0 | 21 |
| `f30` | 30 | 31 | repli par auteur ([`main.py:66-72`](main.py)) | 31 | 1 | 621 |
| `f50` | 50 | 51 | repli par auteur | 51 | 1 | 1 021 |
| `f100` | 100 | 101 | repli par auteur | 101 | 1 | 2 021 |

L'exception avalée à [`main.py:65`](main.py) est, mot pour mot : `InvalidArgument: 400 IN supports up to 30 values. There are 31 values in the IN filter in your query.` Un test direct sur la base confirme la limite : un filtre `IN` à 30 valeurs réussit, un filtre à 31 valeurs échoue ([`raw/verify/in_limit.json`](raw/verify/in_limit.json)). Comme `main.py:47` ajoute l'utilisateur lui-même, la bascule a lieu exactement à F = 30. La pente de 16,85 ms par followee est le coût de chaque requête supplémentaire dans le repli, puisque celles-ci s'exécutent l'une après l'autre.

#### Réponses aux questions de la partie 1

**Vos hypothèses sont-elles confirmées ? Sinon, qu'aviez-vous manqué ?**

Pour U et P, oui. Pour F, nous avions manqué deux choses :

1. **La forme.** Ce n'est pas une croissance continue mais une marche, due à une limite dure de Datastore (30 valeurs dans un `IN`). Cette limite fait changer le code de chemin sans aucun signal d'erreur. En dessous de la limite, F n'a presque aucun effet (0,18 ms par followee).
2. **Le chemin de code.** À la lecture, nous pensions que la requête GQL de [`main.py:52-56`](main.py) était celle exécutée. Elle ne l'est jamais : la bibliothèque `google-cloud-datastore` 2.19.0 n'a pas de méthode `gql`, donc `hasattr(client, 'gql')` vaut `False`, ce que [`bench/verify.py`](bench/verify.py) a vérifié sur le projet. Le chemin réel est le filtre `IN` de [`main.py:61-64`](main.py), et le repli est déclenché par l'exception attrapée à [`main.py:65`](main.py).

**Quelle part de la latence client est due au réseau ?**

L'écart `latence client − temps serveur` (colonne `client_minus_server_ms` de [`figures/fig1b.csv`](figures/fig1b.csv)) est compris entre 12,8 et 17,0 ms sur les 20 valeurs de F. Il ne varie pas avec F, alors que le temps serveur passe de 29 à 1 759 ms. Cet écart contient le réseau et tout ce qui se passe hors de `get_timeline` : frontend App Engine, gunicorn, Flask, sérialisation JSON.

Le journal de requêtes App Engine permet de le décomposer (mesure à C = 1, N = 1, partie 2, [`raw/verify/pending_time.csv`](raw/verify/pending_time.csv)). La latence client médiane vaut 42,5 ms, la latence vue par App Engine (champ `latency`) 35,1 ms, et `get_timeline` 29,3 ms. Le trajet Cloud Shell ↔ App Engine représente donc ~7,4 ms, soit ~17 % de la latence client. Le traitement dans App Engine hors `get_timeline` en représente ~5,8 ms. Ce sont des différences de médianes, donc des ordres de grandeur. Dans le régime F ≥ 30, ces ~14 ms pèsent moins de 3 % de la latence.

**Combien d'entités Datastore une timeline lit-elle, selon U, P et F ? Coût de 1 million de timelines ?**

Le nombre d'entités lues découle du code et est confirmé par la mesure ci-dessus :

- F + 1 ≤ 30 : `1 + min(20, (F+1)·P)` = 21 entités, quels que soient U, P et F (1 `User` + 20 `Post`) ;
- F + 1 > 30 : `1 + (F+1)·min(20, P)` = 1 + 20·(F+1), soit 621 à F = 30 et 2 021 à F = 100.

Ce modèle est vérifié de deux façons indépendantes :

1. Il donne exactement les valeurs mesurées sur les 11 jeux instrumentés (0 écart, [`figures/cost_1M_timelines.csv`](figures/cost_1M_timelines.csv)).
2. Appliqué aux 92 485 timelines des journaux bruts qui ont reçu une réponse, il prédit 2 617 485 lectures. Cloud Monitoring en mesure 2 651 340 (lectures par clé et par requête, [`raw/verify/usage.json`](raw/verify/usage.json)), soit 1,3 % d'écart. Les 93 007 lectures par clé mesurées pour 92 485 timelines (+0,6 %) sont compatibles avec les requêtes faites en dehors de Locust : garde-fous `curl` des scripts, tests, `bench/verify.py`.

**Prix.** Le prix est lu dans la grille officielle via la Cloud Billing Catalog API ([`raw/verify/prices.json`](raw/verify/prices.json)) : SKU `Cloud Datastore Read Ops`, 6 × 10⁻⁷ $ par lecture. C'est le même prix que le SKU `Cloud Firestore Read Ops Europe 3`. Le catalogue indique aussi une franchise gratuite de 50 000 lectures. Elle est négligeable ici : elle réduit le coût d'un million de timelines d'au plus 0,03 $.

| Cas | Entités par timeline | Lectures pour 1 M de timelines | Coût de 1 M de timelines |
|---|---|---|---|
| tout U (100 … 10 000), tout P (10 … 1 000), F ≤ 29 | 21 | 21 M | **12,60 $** |
| F = 30 | 621 | 621 M | 372,60 $ |
| F = 50 | 1 021 | 1 021 M | 612,60 $ |
| F = 100 | 2 021 | 2 021 M | **1 212,60 $** |

Le détail des 26 jeux est dans [`figures/cost_1M_timelines.csv`](figures/cost_1M_timelines.csv). Le coût ne dépend ni de U ni de P. En revanche, il est multiplié par 96 dès qu'un utilisateur suit 100 comptes au lieu de 29.

### 2.2 Partie 2 : capacité

**Protocole** (imposé) : versions `fixed1`, `fixed2`, `fixed4` (N = 1, 2, 4 instances B1), jeu `base` (U = 1 000, P = 20, F = 20), C ∈ {1, 2, 4, 8, 16, 32, 64}, runs de 75 s. Une seule version déployée à la fois, comme le montre la chronologie du § 1.

#### Hypothèse (formulée avant la mesure)

[`app.yaml:2`](app.yaml) lance `gunicorn -b :$PORT main:app`, sans `--workers` ni `--threads`. Gunicorn démarre alors un seul worker synchrone, qui traite une requête à la fois. Nous prédisions trois choses :

1. Une instance sature dès C = 2, à environ `1 / temps de service`.
2. Au-delà, les requêtes ne font qu'attendre, et la latence suit la loi de Little.
3. Le débit maximal est proportionnel à N, puisque les instances ne partagent que Datastore.

Les journaux de `fixed1` confirment la configuration réellement démarrée : `Using worker: sync` et un seul `Booting worker` par démarrage ([`raw/verify/gunicorn_fixed1.json`](raw/verify/gunicorn_fixed1.json)).

#### Figures

![Fig. 2a](figures/fig2a.png)

*Fig. 2a : débit en fonction de C, une courbe par N. Jeu `base` (U = 1 000, P = 20, F = 20). Données : [`figures/fig2a.csv`](figures/fig2a.csv).*

![Fig. 2b](figures/fig2b.png)

*Fig. 2b : latence client médiane (trait plein), latence moyenne (croix) et prédiction de Little `C / débit` (pointillés). Données : [`figures/fig2b.csv`](figures/fig2b.csv).*

#### Interprétation

| N | 1 | 2 | 4 |
|---|---|---|---|
| débit maximal (timelines/s) | **24,0** (C = 4) | **55,3** (C = 32) | **88,3** (C = 64) |
| rapport à N = 1 | 1 | **2,30** | **3,67** |
| débit maximal par instance | 24,0 | 27,7 | 22,1 |
| temps serveur médian, toutes valeurs de C | 29,3 à 32,9 ms | 27,6 à 29,3 ms | 26,0 à 28,7 ms |

**Où se situe le point de saturation pour chaque N ?**

- **N = 1 :** le débit vaut 21,1 timelines/s à C = 1, puis plafonne dès C = 2 entre 20,2 et 24,0 jusqu'à C = 64.
- **N = 2 :** le plafond est atteint vers C = 32 (55,3 à C = 32, 54,9 à C = 64).
- **N = 4 :** le plafond est atteint vers C = 32 (87,9 à C = 32, 88,3 à C = 64).

**Quelle est la capacité d'une instance, et qu'est-ce qui la limite ?**

Une instance sert ~24 timelines/s. Le temps passé dans `get_timeline` ne bouge pas avec la charge : 29,3 ms à C = 1, 32,9 ms à C = 64. Pendant ce temps, la latence client passe de 42,5 à 3 121,6 ms. Le temps ajouté est donc de l'attente, pas du travail.

Le journal de requêtes App Engine montre où cette attente a lieu ([`raw/verify/pending_time.csv`](raw/verify/pending_time.csv)). Son champ `pendingTime` est défini par Google comme *« Time this request spent in the pending request queue »* ([`request_log.proto`](https://github.com/googleapis/googleapis/blob/master/google/appengine/logging/v1/request_log.proto)). Pour `fixed1`, dès C = 2, 96 à 100 % des requêtes passent par cette file, et le temps qu'elles y passent représente l'essentiel de leur latence :

| C | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|
| latence App Engine médiane (ms) | 68,1 | 150,5 | 319,1 | 656,3 | 1 416,6 | 3 101,1 |
| `pendingTime` médian (ms) | 26,2 | 107,3 | 276,2 | 612,4 | 1 368,9 | **3 053,2** |
| différence (ms) | 41,9 | 43,2 | 42,9 | 43,9 | 47,7 | 47,9 |

La différence, ~42 à 48 ms, est le temps que l'instance consacre à chaque requête : `get_timeline` (~30 ms) plus le reste du traitement de la requête. Elle est compatible avec le plafond mesuré : 1 / 41,9 ms ≈ 23,9 timelines/s. La limite d'une instance est donc la suivante : App Engine garde les requêtes dans sa file et ne les confie à l'instance qu'une à la fois. C'est cohérent avec l'indice du sujet : l'application est lancée avec un seul worker synchrone. La partie 3 montre cependant que ce n'est pas le seul verrou.

**La loi de Little est-elle vérifiée au-delà de la saturation ?**

Oui. La loi de Little relie C à la latence moyenne (`moyenne = C / débit`). Sur la moyenne, l'écart est inférieur à 1 % pour 20 des 21 points ; il vaut 5,8 % pour N = 2, C = 32 (colonne `little_vs_mean_pct` de [`figures/fig2b.csv`](figures/fig2b.csv)). Pour N = 1 :

| C | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| latence moyenne mesurée (ms) | 47,2 | 83,2 | 166,5 | 342,2 | 667,5 | 1 441,6 | 3 169,2 |
| prédiction `C / débit` (ms) | 47,3 | 83,3 | 166,4 | 342,1 | 667,1 | 1 442,8 | 3 163,7 |
| latence médiane mesurée (ms) | 42,5 | 75,3 | 159,1 | 328,3 | 664,3 | 1 423,4 | 3 121,6 |


1. **Le résultat est attendu.** En boucle fermée sans temps de réflexion, il y a toujours exactement C requêtes en cours, donc la loi tient par construction. Sa vérification montre surtout que les mesures de débit et de latence sont cohérentes entre elles.
2. **La figure demandée trace la médiane.** Sur la médiane, l'écart à Little reste faible pour N = 1 au-delà de la saturation (0,4 à 1,4 % pour C ≥ 16). Il atteint en revanche 29 à 35 % pour N = 2 à C = 32 et 64 (colonne `little_vs_median_pct`). Avec plusieurs instances, la distribution des latences s'étale vers le haut, et la moyenne s'écarte de la médiane.

**Passer de 1 à 4 instances multiplie-t-il le débit maximal par 4 ? Sinon, où est le goulot ?**

Presque : ×3,67 pour N = 4, et ×2,30 pour N = 2. Selon la définition du sujet (« multiplié par environ k »), les ressources passent à l'échelle. Les mesures écartent Datastore comme goulot : le temps serveur ne croît pas avec N (il est même légèrement plus bas à N = 4). L'écart à ×4 (8 %) est du même ordre que la variation de capacité d'une instance à l'autre, qui va de 22,1 à 27,7 timelines/s selon le déploiement. C'est aussi pourquoi N = 2 dépasse ×2. Nous ne pouvons donc pas attribuer ces 8 % à un goulot identifié. Pour N = 4 à C = 64, la file d'App Engine est encore présente (`pendingTime` médian de 509 ms sur 563 ms de latence) : la saturation est toujours une saturation par instance.

### 2.3 Partie 3 : corriger et re-mesurer

**Goulot choisi :** la capacité d'une instance (partie 2).

**Hypothèse (formulée avant la mesure) :** si la limite est le worker synchrone unique, il suffit de permettre plusieurs requêtes simultanées dans l'instance. Comme une timeline passe une partie de son temps à attendre Datastore, ces requêtes se chevaucheraient, et le débit d'une instance augmenterait nettement.

**Correction :** la version `fix1` ([`deploy_fix.sh`](deploy_fix.sh)) est identique à `fixed1` (B1, manual scaling, 1 instance, `--no-promote`), à une ligne près :

```
entrypoint: gunicorn -b :$PORT --workers 2 --threads 8 main:app
```

Les journaux confirment la configuration réellement démarrée : `Using worker: gthread` et deux `Booting worker` ([`raw/verify/gunicorn_fix1.json`](raw/verify/gunicorn_fix1.json)). Le protocole est exactement celui de la partie 2 pour N = 1 : même script [`bench/run_sweep.sh`](bench/run_sweep.sh), mêmes valeurs de C, même jeu, même durée.

![Fig. 3](figures/fig3.png)

*Fig. 3 : débit et latence avant (`fixed1`) et après (`fix1`), N = 1, jeu `base` (U = 1 000, P = 20, F = 20). Données : [`figures/fig3.csv`](figures/fig3.csv).*

#### Interprétation : hypothèse réfutée

| C | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| débit avant (timelines/s) | 21,1 | 24,0 | 24,0 | 23,4 | 24,0 | 22,2 | 20,2 |
| débit après (timelines/s) | 23,2 | 26,3 | 25,5 | 24,5 | 23,7 | 24,4 | 25,0 |
| écart | +9,5 % | +9,7 % | +5,9 % | +4,8 % | −1,2 % | +9,9 % | +23,6 % |
| temps serveur médian avant / après (ms) | 29,3 / 27,7 | 29,9 / 28,1 | 30,4 / 29,5 | 30,7 / 30,0 | 30,3 / 31,4 | 30,3 / 29,8 | 32,9 / 29,2 |

Le débit maximal passe de 24,0 à 26,3 timelines/s (+9,5 %). Cet écart n'est pas attribuable à la correction. À C = 1, il n'y a jamais qu'une requête à la fois, donc des threads supplémentaires ne peuvent rien changer. Pourtant l'écart y est déjà de +9,5 %. C'est la différence entre deux instances déployées à des moments différents, du même ordre que la variation de 22,1 à 27,7 timelines/s par instance observée en partie 2. Seul C = 64 sort de cette marge : le débit y est de 25,0 au lieu de 20,2 timelines/s, et la latence médiane de 2 550 au lieu de 3 122 ms. Chaque point n'a été mesuré qu'une fois (§ 4.2), donc nous ne concluons pas sur ce point isolé.

**Pourquoi la correction ne lève pas le goulot.** Le journal de requêtes de `fix1` montre la même file d'attente qu'avant ([`raw/verify/pending_time.csv`](raw/verify/pending_time.csv)). À C = 64, sur 2 537 ms de latence App Engine médiane, 2 494 ms se passent dans la file d'App Engine, contre 3 053 ms sur 3 101 ms avec `fixed1`. Le temps serveur reste à ~28-31 ms à toutes les valeurs de C. Les 16 threads de gunicorn ne reçoivent donc pas plus de requêtes simultanées qu'avant : l'attente a lieu avant l'instance, là où un changement de configuration de gunicorn ne peut pas agir.

Nos mesures établissent *où* se trouve la file. Elles n'établissent pas *pourquoi* App Engine ne confie pas davantage de requêtes simultanées à une instance B1 en manual scaling. Ce serait la prochaine expérience à mener, par exemple en faisant varier le mode de scaling ou la classe d'instance, toutes choses égales par ailleurs.

**Ce que coûte la correction :**

- **Complexité :** une ligne de configuration. Mais le `datastore.Client()` global ([`main.py:10`](main.py)) est désormais partagé entre 8 threads par processus. Nous n'avons pas vérifié que c'est sûr.
- **Argent :** même classe et même nombre d'instances, donc même prix à l'heure (0,05 $ par heure d'instance B, [`raw/verify/prices.json`](raw/verify/prices.json)). `fix1` a tourné 0,27 h.
- **Mémoire :** deux processus Python au lieu d'un. Ce n'est pas mesuré ici.
- **Cohérence des données :** aucun effet. Le chemin mesuré est en lecture seule.

**Bilan :** aucun gain démontré pour une hypothèse de concurrence supplémentaire. Nous ne recommandons pas de promouvoir `fix1` sur la foi de ces mesures.

**Le goulot que la partie 1 désigne.** La correction la plus directe de la marche à F = 30 serait de découper la liste d'auteurs en paquets d'au plus 30 valeurs, soit `⌈(F+1)/30⌉` requêtes `IN` au lieu de F + 1 requêtes individuelles, puis de fusionner les résultats. Une alternative serait une timeline matérialisée à l'écriture (*fan-out on write*), qui coûte des écritures et rend la timeline cohérente à terme. Aucune des deux n'a été déployée ni mesurée dans cette campagne.

---

## 3. Tableau des verdicts

| Dimension | Passe à l'échelle ? | Jusqu'où ? | Pourquoi (mécanisme) | Preuve |
|---|---|---|---|---|
| **Utilisateurs (U)** | **Oui** | Mesuré jusqu'à U = 10 000 : 30,2 → 30,5 ms | Lecture du `User` par clé ([`main.py:43`](main.py)) et requête sur l'index `Post(author, created DESC)` limitée aux auteurs suivis. Une timeline lit 21 entités quel que soit U (mesuré). | Fig. 1a, [`reads_per_timeline.csv`](raw/verify/reads_per_timeline.csv) |
| **Posts par utilisateur (P)** | **Oui** | Mesuré jusqu'à P = 1 000 : 28,8 à 32,8 ms | `ORDER BY created DESC` sur l'index et `limit=20` : 20 posts lus quel que soit P (mesuré). | Fig. 1a, [`reads_per_timeline.csv`](raw/verify/reads_per_timeline.csv) |
| **Followees (F)** | **Non** | Stable jusqu'à F = 25 (32,8 ms) ; ×17,6 à F = 30, puis +16,85 ms par followee | À F + 1 > 30 auteurs, Datastore refuse l'`IN` (`IN supports up to 30 values`, mesuré). L'exception est avalée ([`main.py:65`](main.py)) et le repli exécute F + 1 requêtes l'une après l'autre ([`main.py:66-72`](main.py)) : de 21 à 1 + 20(F+1) entités lues. | Fig. 1b, [`in_limit.json`](raw/verify/in_limit.json) |
| **Instances (N)** | **Oui** (≈ k) | ×2,30 à N = 2, ×3,67 à N = 4 | Les instances sont indépendantes et Datastore ne sature pas (temps serveur constant). Chaque instance plafonne à ~24 timelines/s : App Engine fait attendre les requêtes dans sa file avant l'instance (`pendingTime`), et ajouter des threads gunicorn n'y change rien. | Fig. 2a, Fig. 3, [`pending_time.csv`](raw/verify/pending_time.csv) |

---

## 4. Validité

### 4.1 Combien d'instances ont réellement servi chaque mesure ? Est-ce celles attendues ?

Elles sont comptées sur les valeurs distinctes de l'en-tête `X-Instance`, run par run (colonnes `instances_observed` et `instance_ids` de [`figures/summary.csv`](figures/summary.csv)) :

| Mesures | Attendu | Observé, dans chaque run |
|---|---|---|
| Partie 1 (26 runs) | 1 | 1, toujours la même instance (`00e8a408bd06…`) |
| Partie 2, N = 1 (7 runs) | 1 | 1, la même instance que la partie 1 |
| Partie 2, N = 2 (7 runs) | 2 | 2, toujours les mêmes deux instances |
| Partie 2, N = 4 (7 runs) | 4 | 4, toujours les mêmes quatre instances, y compris à C = 1 |
| Partie 3 (7 runs) | 1 | 1 (`00e8a408bddf…`) |

Toutes les mesures ont été servies par le nombre d'instances attendu. Le journal de requêtes App Engine donne les mêmes comptes pour les parties 2 et 3 (colonne `instances` de [`raw/verify/pending_time.csv`](raw/verify/pending_time.csv)).

### 4.2 Vos runs sont-ils indépendants ? L'ordre des mesures influence-t-il les résultats ?

Ils ne sont pas entièrement indépendants, et nous n'avons pas testé l'effet de l'ordre.

- **Même instance pour toute une série.** Les runs d'une même version s'enchaînent sur les mêmes instances, sans redémarrage. Pour `fixed1`, gunicorn a démarré une fois le 24/11 à 13:52:50, puis le 25/11 à 02:08 et à 09:22, après la fin de ses mesures ([`raw/verify/gunicorn_fixed1.json`](raw/verify/gunicorn_fixed1.json)). Les 33 runs de `fixed1` ont donc été servis par un même processus.
- **Ordre fixe.** Les runs ont été faits dans un ordre fixe et croissant (U, puis P, puis F ; C croissant), sans ordre aléatoire. Pour N = 1, les runs C = 32 et C = 64 ont été faits 21 minutes après C = 16, à la suite d'une interruption du script.
- **Une seule mesure par point.** Nous n'avons donc pas d'estimation directe de la dispersion. Deux indices indirects la situent autour de 10 % :
  - les sept runs de la partie 1 qui ont F = 20 (jeux `u100`, `base`, `u10k`, `p10`, `p100`, `p1000`, `f20`) donnent un temps serveur médian entre 28,8 et 32,8 ms ;
  - à C = 1, `fixed1` et `fix1`, qui ne diffèrent que par une option sans effet sans concurrence, diffèrent de 9,5 % en débit.
- **Conséquence.** Les effets de l'ordre de ×17,6 (F) ou ×3,67 (N) sont largement au-dessus de cette dispersion. Les écarts de moins de ~10 %, dont ceux de la partie 3, ne sont pas interprétables.

### 4.3 Quelle part de la latence est due au réseau ?

Voir le § 2.1. L'écart `latence client − temps serveur` vaut 12,8 à 17,0 ms en partie 1, sans dépendre de F. À C = 1, le journal App Engine permet de le décomposer : ~7,4 ms entre Cloud Shell et App Engine (~17 % des 42,5 ms de latence client), et ~5,8 ms de traitement dans App Engine hors `get_timeline`. Au-delà de la saturation, la latence est faite d'attente dans la file d'App Engine (§ 2.2), et la part du réseau devient négligeable (< 1 % à C = 64, N = 1).

### 4.4 Qu'avez-vous compté comme un échec ? Quels codes HTTP avez-vous observés ?

Tout ce qui n'est pas un `200` compte comme un échec. Locust enregistre `STATUS = 0` pour une requête qui n'a reçu aucune réponse HTTP, avec le type d'exception côté client dans la colonne `ERROR`.

Sur les 92 547 requêtes de la campagne (colonnes `http_codes_all` et `client_errors_all` de [`figures/summary.csv`](figures/summary.csv)) :

- **Codes observés :** `200` et `0` uniquement. Aucune réponse 4xx ou 5xx.
- **62 requêtes `0`** (0,07 %), dans 15 runs, toutes à C ≥ 4, avec deux types d'exceptions côté client : `ConnectionRefusedError` (28) et `gaierror` (échec de résolution DNS, 34).
- **61 de ces 62** ont lieu dans les 10 premières secondes, au moment où Locust lance ses C utilisateurs. L'analyse les écarte. Il reste 1 échec dans les données analysées (`p2_n2_c16`, 1 sur 3 303).

À noter pour la partie 1 : aucune réponse en erreur à F ≥ 30, alors que le service y est jusqu'à 54 fois plus lent qu'à F = 25. L'erreur Datastore existe (`InvalidArgument 400`), mais `main.py:65` l'avale. Elle est invisible pour qui ne regarde que les codes HTTP.

### 4.5 Avez-vous vérifié que votre mesure exerce bien le chemin de code que vous croyez ?

Oui, et la vérification a corrigé notre lecture du code (§ 2.1). Quatre mesures indépendantes, toutes produites par [`bench/verify.py`](bench/verify.py) :

1. **Le chemin de code.** Le vrai `get_timeline` a été exécuté sur chaque type de jeu, avec un compteur de requêtes et d'entités ([`raw/verify/reads_per_timeline.csv`](raw/verify/reads_per_timeline.csv)). La branche GQL ([`main.py:52-56`](main.py)) n'est jamais exécutée, car `hasattr(client, 'gql')` vaut `False`. Pour F ≤ 25, c'est une requête `IN` unique ([`main.py:61-64`](main.py)). Pour F ≥ 30, c'est le repli par auteur ([`main.py:66-72`](main.py)), avec le message d'erreur exact de Datastore.
2. **La limite.** Un `IN` à 30 valeurs réussit, à 31 valeurs il échoue ([`raw/verify/in_limit.json`](raw/verify/in_limit.json)).
3. **La configuration réellement déployée.** `Using worker: sync` pour `fixed1` ; `Using worker: gthread` avec deux workers pour `fix1` ([`raw/verify/gunicorn_fixed1.json`](raw/verify/gunicorn_fixed1.json), [`raw/verify/gunicorn_fix1.json`](raw/verify/gunicorn_fix1.json)).
4. **Le volume de travail.** Les lectures Datastore mesurées par Cloud Monitoring pendant la campagne (2 651 340) correspondent à 1,3 % près à ce que prédit le chemin de code pour les 92 485 timelines journalisées (§ 2.1).

### 4.6 Combien votre campagne a-t-elle coûté (lectures, écritures, heures d'instance) ?

Voir le § 5.

---

## 5. Coût de la campagne

Quantités consommées, mesurées par Cloud Monitoring sur le projet ([`raw/verify/usage.json`](raw/verify/usage.json), [`figures/campaign_cost.csv`](figures/campaign_cost.csv)) :

| Poste | Quantité |
|---|---|
| Lectures d'entités par clé | 93 007 |
| Lectures d'entités par requête | 2 558 333 |
| Lectures *keys-only* (suppressions de jeux) | 50 601 |
| Écritures d'entités | 610 392 |
| Suppressions d'entités | 39 599 |
| Heures d'instance B1 : `fixed1` / `fixed2` / `fixed4` / `fix1` | 23,20 / 0,60 / 1,89 / 0,27 h (total 25,96 h) |
| Heures d'instance F1 : version par défaut | 0,25 h |

Montant facturé, d'après la page Facturation (compte « Billing Account for Education », du 1er au 26 novembre 2026) :

| Coût | Économies (crédits éducation) | Total payé |
|---|---|---|
| 3,12 $ | −3,12 $ | 0,00 $ |

`fixed1` est restée démarrée 23,2 heures, dont 22,73 heures sans mesure, entre la fin de ses mesures (24/11 14:51) et son arrêt (25/11 13:03). Cela contredit la consigne du sujet (§ 9 : « Arrêtez chaque version `fixedN` dès la fin de ses mesures »).

---

## Annexe : reproduire la campagne

```sh
pip install -r bench/requirements.txt -r scripts/requirements.txt

# 1. les 26 jeux de données (une seule fois)
./bench/seed_order.sh

# 2. partie 1 + partie 2 (N=1), sur une seule version
./deploy_fixed.sh 1
URL=https://fixed1-dot-<projet>.ew.r.appspot.com ./bench/run_part1.sh
URL=https://fixed1-dot-<projet>.ew.r.appspot.com N=1 ./bench/run_sweep.sh
gcloud app versions stop fixed1

# 3. partie 2, N=2 puis N=4 (une version à la fois, arrêtée aussitôt)
./deploy_fixed.sh 2 && URL=https://fixed2-dot-<projet>.ew.r.appspot.com N=2 ./bench/run_sweep.sh
gcloud app versions stop fixed2
./deploy_fixed.sh 4 && URL=https://fixed4-dot-<projet>.ew.r.appspot.com N=4 ./bench/run_sweep.sh
gcloud app versions stop fixed4

# 4. partie 3
./deploy_fix.sh
URL=https://fix1-dot-<projet>.ew.r.appspot.com N=1 TAG=p3 ./bench/run_sweep.sh
gcloud app versions stop fix1

# 5. preuves relevées sur le projet (chemin de code, limite IN, journaux,
#    Cloud Monitoring, grille tarifaire) -> raw/verify/
python3 bench/verify.py

# 6. toutes les figures et tous les CSV
make figures
```
