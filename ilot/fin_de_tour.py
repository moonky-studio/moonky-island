# -*- coding: utf-8 -*-
"""
Questions de fin de tour, relayées dans l'îlot (hook PreToolUse sur mcp__ccd_turn__wrap_up, lancé par ilot.py).

Dans l'appli de bureau Claude, le résumé de fin de tour (outil wrap_up) peut porter une question (`ask`) et des
boutons de réponse ({"label": ...}), que l'utilisateur ne voit qu'en ouvrant la session. L'îlot les montre en haut de
l'écran comme une question AskUserQuestion, le résumé au-dessus. Une réponse dans l'îlot refuse l'appel avec la
réponse dans la raison : Claude la lit, continue son tour en conséquence et rappelle wrap_up sans question.

Laissé passer tel quel, sans rien afficher :
- wrap_up sans `ask`, ou sans aucun bouton de réponse (question ouverte : l'appli la montre avec son champ libre) ;
- wrap_up avec au moins un bouton d'action de l'appli (commit, create_pr, merge, archive…), que l'îlot ne sait pas
  déclencher ;
- la même question déjà relayée pour cette session dans les 15 dernières minutes, pour ne jamais tourner en rond ;
- réglage "questions_fin_de_tour": false.
« Répondre dans Claude » ou 9 minutes sans réponse laissent aussi passer : l'appli affiche alors sa propre question
de fin de tour, et la pastille « attend ta réponse » la signale.

État par session dans etat\\fin-de-tour du dossier de données (voir commun.py) : une empreinte de la dernière
question relayée, jamais son texte. Ce module ne fait que des calculs et ne lève pas d'erreur ; l'affichage reste à
ilot.py.
"""
import hashlib
import json
import os
import re
import time

import commun

OUTIL = 'mcp__ccd_turn__wrap_up'
REGLAGE = 'questions_fin_de_tour'
ETAT = os.path.join(commun.ETAT, 'fin-de-tour' + ('-essai' if commun.ESSAI else ''))
RELAIS_RECENT = 15 * 60  # secondes pendant lesquelles la même question n'est pas relayée une seconde fois


def active():
    return commun.oui(commun.reglages().get(REGLAGE, True))


def boutons(actions):
    if isinstance(actions, str):  # certains clients passent le tableau en texte JSON
        try:
            actions = json.loads(actions)
        except ValueError:
            return []
    return [b for b in actions if isinstance(b, dict)] if isinstance(actions, list) else []


def libelles(actions):
    """Libellés des boutons de réponse, ou None si un bouton d'action de l'appli est présent."""
    vus = []
    for b in boutons(actions):
        if isinstance(b.get('action'), str) and b['action'].strip():
            return None
        libelle = ' '.join(str(b.get('label') or '').split())
        if libelle and libelle not in vus:
            vus.append(libelle)
    return vus


def chemin_etat(session_id):
    nom = re.sub(r'[^A-Za-z0-9_.-]', '_', str(session_id or 'inconnue'))
    return os.path.join(ETAT, nom + '.json')


def empreinte(question):
    return hashlib.sha256(' '.join(question.split()).casefold().encode('utf-8')).hexdigest()


def relayee_recemment(session_id, question):
    try:
        with open(chemin_etat(session_id), encoding='utf-8') as f:
            lu = json.load(f)
        return (lu.get('question') == empreinte(question)
                and time.time() - float(lu.get('quand') or 0) < RELAIS_RECENT)
    except Exception:  # noqa: BLE001
        return False


def oublier(session_id):
    try:
        os.remove(chemin_etat(session_id))
    except OSError:
        pass


def noter_relais(session_id, question):
    try:
        os.makedirs(ETAT, exist_ok=True)
        with open(chemin_etat(session_id), 'w', encoding='utf-8') as f:
            json.dump({'question': empreinte(question), 'quand': time.time()}, f)
        return True
    except OSError:
        return False


def questions(entree):
    """Question à montrer dans l'îlot, au format d'AskUserQuestion, ou None pour laisser passer le wrap_up."""
    if str(entree.get('tool_name') or '') != OUTIL:
        return None
    outil = entree.get('tool_input')
    if not isinstance(outil, dict):
        return None
    session = entree.get('session_id')
    question = ' '.join(outil['ask'].split()) if isinstance(outil.get('ask'), str) else ''
    if not question:
        oublier(session)
        return None
    choix = libelles(outil.get('actions'))
    if not choix:
        return None  # bouton d'action de l'appli, ou question sans bouton de réponse
    if relayee_recemment(session, question):
        commun.noter('ilot', 'question de fin de tour déjà relayée : laissée à l’appli Claude')
        return None
    resume = ' '.join(outil['recap'].split()) if isinstance(outil.get('recap'), str) else ''
    options = [{'label': c} for c in choix[:9]]
    if len(options) > 1:
        options[0]['recommande'] = True  # le premier bouton est celui que Claude propose
    return [{'question': question, 'header': '', 'multiSelect': False, 'options': options, 'contexte': resume}]


def raison(question, reponse):
    """Raison du refus donnée à Claude : la réponse de l'utilisateur, et la suite à donner."""
    question = ' '.join(str(question).split())
    reponse = ' '.join(str(reponse).split())
    return commun.t(
        f"{commun.MARQUE_GARDE} : l'utilisateur a répondu dans l'îlot à la question de ton résumé de fin de tour. "
        f"Question : « {question} » Réponse : « {reponse} ». Ce wrap_up n'est pas passé. Continue ton tour selon "
        "cette réponse, sans lui reposer la question, puis rappelle wrap_up sans `ask` ni boutons de réponse.",
        f'{commun.MARQUE_GARDE}: the user answered the question of your end-of-turn summary in the island. '
        f'Question: "{question}" Answer: "{reponse}". This wrap_up did not go through. Carry on with your turn '
        'according to this answer, without asking it again, then call wrap_up again without `ask` or reply buttons.',
    )


def sortie(entree, reponses):
    """Sortie du hook pour une réponse donnée dans l'îlot (dict question -> texte), ou None si elle est vide."""
    outil = entree.get('tool_input') if isinstance(entree.get('tool_input'), dict) else {}
    question = ' '.join(str(outil.get('ask') or '').split())
    if not isinstance(reponses, dict):
        return None
    reponse = reponses.get(question)
    if not reponse:
        reponse = next((v for v in reponses.values() if v), '')
    if not str(reponse).strip():
        return None
    noter_relais(entree.get('session_id'), question)
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                   'permissionDecisionReason': raison(question, reponse)}}
