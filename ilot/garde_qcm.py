# -*- coding: utf-8 -*-
"""
Garde-fou des questions de l'îlot (hook PreToolUse, matcher ^mcp__ccd_turn__wrap_up$).

Coupé par défaut : il n'agit que si reglages.json contient "garde_fou": true. Le champ `ask` de wrap_up n'existe que
dans l'appli de bureau Claude.

Une décision qui revient à l'utilisateur se pose avec l'outil AskUserQuestion, qu'il voit dans l'îlot en haut de
l'écran, pas dans le champ `ask` du résumé de fin de tour (wrap_up) de l'appli Claude, qu'il ne voit qu'en ouvrant la
session :
- wrap_up sans `ask` : laissé passer, et l'éventuel refus en mémoire est oublié ;
- wrap_up avec `ask` et au moins un bouton d'action de l'appli (commit, create_pr, merge, archive…) : laissé passer,
  l'îlot ne sait pas déclencher ces boutons ;
- wrap_up avec `ask` et seulement des boutons de réponse : refusé, la raison renvoie vers AskUserQuestion ;
- même session qui insiste dans les 15 minutes après un refus : laissé passer, pour ne jamais tourner en rond
  (question ouverte, session sans AskUserQuestion qui n'a pas suivi la consigne).

État par session dans etat\\garde-questions du dossier de données (voir commun.py). Extension coupée, îlot qui ne peut
pas s'afficher sur ce PC, état illisible ou impossible à écrire, erreur quelconque : on laisse passer. Mieux vaut une
question dans la discussion qu'une session bloquée.
"""
import sys

if sys.platform != 'win32':  # l'îlot ne s'affiche que sous Windows : ailleurs, rien à imposer
    sys.exit(0)

import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402

ICI = os.path.dirname(os.path.abspath(__file__))
if ICI not in sys.path:
    sys.path.insert(0, ICI)
import commun  # noqa: E402

OUTIL = 'mcp__ccd_turn__wrap_up'
ETAT = os.path.join(commun.ETAT, 'garde-questions' + ('-essai' if commun.ESSAI else ''))
INSISTANCE = 15 * 60  # secondes pendant lesquelles un second wrap_up avec question passe

RAISON_FR = (
    commun.MARQUE_GARDE + " : une décision qui revient à l'utilisateur se pose avec l'outil AskUserQuestion, qu'il "
    "voit dans l'îlot en haut de l'écran, pas dans le `ask` de wrap_up. Pose maintenant cette question avec "
    "AskUserQuestion : une question qui se comprend seule, 2 à 4 options courtes, ta recommandation en premier suivie "
    "de « (recommandé) ». Agis selon sa réponse, puis rappelle wrap_up sans `ask` ni boutons de réponse. Si cette "
    "session n'a pas AskUserQuestion (tâche planifiée) ou si la question est ouverte (un nom, un montant, un texte à "
    "fournir), rappelle wrap_up sans `ask` et pose la question en une ligne à la fin de ton message."
)
RAISON_EN = (
    commun.MARQUE_GARDE + ": a decision that belongs to the user is asked with the AskUserQuestion tool, which they see "
    "in the island at the top of the screen, not in the `ask` field of wrap_up. Ask this question now with "
    "AskUserQuestion: a question that stands on its own, 2 to 4 short options, your recommendation first followed by "
    "\"(recommended)\". Act on their answer, then call wrap_up again without `ask` or reply buttons. If this session "
    "has no AskUserQuestion (scheduled task) or the question is open-ended (a name, an amount, a text to provide), call "
    "wrap_up again without `ask` and ask the question in one line at the end of your message."
)


def raison():
    return commun.t(RAISON_FR, RAISON_EN)


def chemin_etat(session_id):
    nom = re.sub(r'[^A-Za-z0-9_.-]', '_', str(session_id or 'inconnue'))
    return os.path.join(ETAT, nom + '.json')


def dernier_refus(session_id):
    try:
        with open(chemin_etat(session_id), encoding='utf-8') as f:
            return float(json.load(f).get('refus') or 0)
    except Exception:  # noqa: BLE001
        return 0.0


def oublier_refus(session_id):
    try:
        os.remove(chemin_etat(session_id))
    except OSError:
        pass


def noter_refus(session_id):
    try:
        os.makedirs(ETAT, exist_ok=True)
        with open(chemin_etat(session_id), 'w', encoding='utf-8') as f:
            json.dump({'refus': time.time()}, f)
        return True
    except OSError:
        return False


def boutons(actions):
    if isinstance(actions, str):  # certains clients passent le tableau en texte JSON
        try:
            actions = json.loads(actions)
        except ValueError:
            return []
    return actions if isinstance(actions, list) else []


def decision(entree):
    """Sortie du hook pour cette entrée, ou None pour laisser passer."""
    if str(entree.get('tool_name') or '') != OUTIL:
        return None
    outil = entree.get('tool_input')
    if not isinstance(outil, dict):
        outil = {}
    session = entree.get('session_id')
    question = outil['ask'].strip() if isinstance(outil.get('ask'), str) else ''
    if not question:
        oublier_refus(session)
        return None
    if any(isinstance(b, dict) and isinstance(b.get('action'), str) and b['action'].strip()
           for b in boutons(outil.get('actions'))):
        return None
    refus = dernier_refus(session)
    if refus and time.time() - refus < INSISTANCE:
        oublier_refus(session)
        commun.noter('garde', 'wrap_up avec question laissé passer : la session insiste après un refus')
        return None
    if not noter_refus(session):
        return None
    commun.noter('garde', 'wrap_up avec question refusé : renvoyé vers AskUserQuestion')
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                   'permissionDecisionReason': raison()}}


def main():
    try:
        brut = sys.stdin.buffer.read() if sys.stdin is not None else b''
        if not commun.oui(commun.reglages().get('garde_fou')) or commun.coupe() or commun.manque():
            return  # garde-fou pas activé, extension coupée, ou îlot qui ne peut pas s'afficher : on laisse passer
        entree = json.loads(brut.decode('utf-8', 'replace') or '{}')
        if not isinstance(entree, dict):
            return
        sortie = decision(entree)
        if sortie:
            sys.stdout.write(json.dumps(sortie))  # ASCII seulement : rien à craindre de l'encodage de la console
            sys.stdout.flush()
    except Exception as e:  # noqa: BLE001
        commun.noter('garde', f'erreur, wrap_up laissé passer : {e!r}')


if __name__ == '__main__':
    main()
