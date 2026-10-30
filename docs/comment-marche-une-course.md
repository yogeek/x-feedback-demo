# Ce qui se passe quand on lance une course

Le serveur Python de la démo (`server.py`, lancé en local) orchestre tout, mais **aucun
modèle ne tourne en local**. Chaque modèle est hébergé chez son fournisseur (TypeSafe,
Liquid, Anthropic, Mistral...). Le serveur leur envoie des requêtes HTTP via OpenRouter,
qui sert d'intermédiaire avec une seule clé API, et récupère les réponses.

```
Navigateur ──POST /api/race──▶ server.py (local)
                                  │  1 thread par modèle choisi
                                  ├──▶ Jev        ┐
                                  ├──▶ Liquid d1  │  requêtes HTTPS vers OpenRouter,
                                  ├──▶ Haiku      │  qui les transmet au fournisseur
                                  └──▶ Sonnet     ┘  de chaque modèle
Navigateur ◀── flux SSE (progression en direct) ──┘
```

## Étape par étape

1. **Le navigateur envoie les réglages** : les questions, les modèles, le nombre de
   réponses et le mode d'appel des LLM (par lots de 20 ou une par une). La clé OpenRouter
   reste sur le serveur, elle n'est jamais envoyée au navigateur.
2. **Le serveur prend les N réponses X les plus likées** dans `data/replies.jsonl`. Elles
   ont été téléchargées une fois pour toutes (`fetch_replies.py`) et pseudonymisées
   (`anonymize.py`) ; X n'est pas interrogé pendant la course.
3. **Il démarre un thread par modèle, tous en même temps** : c'est ce qui fait la « course »
   (classe `Race` dans `server.py`).
4. **Chaque thread appelle son modèle**, de deux façons différentes selon la famille
   (`engine.py`). Les deux sont décrites dans la section suivante.
5. **Le serveur suit la course** : après chaque appel, il envoie au navigateur un événement
   de progression par Server-Sent Events (réponses traitées, coût réel renvoyé par
   OpenRouter, temps écoulé). C'est ce qui fait avancer les couloirs.
6. **Quand un modèle termine**, le serveur calcule ses scores (`metrics()` dans
   `server.py`) en comparant ses étiquettes au **corrigé** (`data/reference.json`). Ce
   corrigé a été produit une fois à l'avance par Claude Sonnet 5.5 sur les 581 réponses
   (`build_reference.py`) ; il n'est pas recalculé pendant la course.
7. **À la fin**, tout est enregistré dans `results/race-<date>-<id>.json` : réglages, réponse
   brute de chaque modèle pour chaque réponse X, et métriques. C'est ce fichier qui alimente
   l'explorateur « Reply by reply ».

## Les deux façons d'appeler un modèle

### Modèle de décision (Jev, Liquid d1...)

- **Une requête par réponse X**, jusqu'à 32 en parallèle, sur l'API Decisions
  d'OpenRouter (`POST /api/alpha/decisions`).
- Il envoie un **état** (le post et la réponse) et les **sous-questions typées**
  définies dans `questions.py`. Par exemple, pour « What do they think of Episode 1? » :
  deux Noul (« parle-t-il de l'épisode ? », « donne-t-il un avis ? ») et un Choice
  (positif, négatif ou mitigé). Les sous-questions de toutes les questions choisies
  partent dans la même requête, donc l'état n'est lu et payé qu'une fois.
- Le modèle renvoie des probabilités, par exemple `on_topic: 0.83`,
  `opinion: {negative: 1, ...}`. Il n'écrit pas de texte, et seule l'entrée est facturée.
- **Du code Python combine ces probabilités en une étiquette finale** (`decide()` dans
  `questions.py`). S'il est hors sujet, c'est `off_topic` ; s'il ne donne pas d'avis,
  c'est `neutral` ; sinon c'est le Choice. Si un Noul tombe entre 0,3 et 0,7, la réponse
  est marquée « pas sûr ».

### LLM (Haiku, Sonnet, Mistral Nemo...)

- **Une requête par lot de 20 réponses**, jusqu'à 8 lots en parallèle (ou une réponse
  par requête et 32 en parallèle en mode « One by one »), sur l'API Chat d'OpenRouter
  (`POST /api/v1/chat/completions`).
- Il envoie un prompt avec les consignes, la liste des étiquettes autorisées et les
  réponses numérotées. Il impose aussi un **schéma JSON** dont chaque champ n'accepte que
  les étiquettes de la liste.
- Le LLM **écrit** un texte JSON, par exemple
  `{"labels": [{"i": 0, "opinion": "negative"}, ...]}`. Le code le lit et le vérifie.
- Si le JSON est cassé, s'il manque une réponse ou s'il y a une étiquette hors liste, le
  code réessaie jusqu'à 3 fois, puis compte ces réponses comme **perdues**. Les essais
  ratés sont quand même facturés.

## En résumé

- Le seul code exécuté, c'est le serveur Python : il prépare les requêtes, les envoie en
  parallèle, lit les réponses, combine et compare. Il ne fait pas raisonner les modèles ;
  il leur pose une question et lit ce qu'ils renvoient.
- Pour les modèles de décision, la logique métier (comment trois sous-réponses donnent un
  avis) est **dans le code**. Pour les LLM, elle est **dans le prompt**, et le résultat
  dépend de ce que le modèle écrit.
- Chaque course coûte de l'argent réel sur le compte OpenRouter : de quelques centimes à
  environ 0,20 $ selon les modèles et le nombre de réponses.
