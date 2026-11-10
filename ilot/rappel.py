# -*- coding: utf-8 -*-
"""
Rappel de démarrage de Moonky Island (hook SessionStart, aussi après un /clear ou un résumé de la discussion).

Dit à Claude de poser les décisions de l'utilisateur avec l'outil AskUserQuestion, que l'îlot affiche en haut de
l'écran. Rien quand l'extension est coupée ou hors de Windows. Si l'îlot ne peut pas encore s'afficher sur ce PC, le
rappel le dit à Claude avec la commande qui termine l'installation, sans lui imposer la règle. Texte en français ou en
anglais selon commun.langue().
"""
import sys

if sys.platform != 'win32':
    sys.exit(0)

import json  # noqa: E402
import os  # noqa: E402

ICI = os.path.dirname(os.path.abspath(__file__))
if ICI not in sys.path:
    sys.path.insert(0, ICI)
import commun  # noqa: E402

REGLE_FR = (
    "Moonky Island : quand une décision revient à l'utilisateur (un choix, un accord pour envoyer, valider ou "
    "supprimer), pose-la avec l'outil AskUserQuestion, qu'il voit dans l'îlot en haut de l'écran, plutôt que dans le "
    "texte ou dans le `ask` de wrap_up : une question qui se comprend seule, 2 à 4 options courtes, ta recommandation "
    "en premier suivie de « (recommandé) ». Restent dans le texte les questions ouvertes (un nom, un montant, un texte "
    "à fournir) et celles des sessions sans AskUserQuestion (tâches planifiées)."
)
REGLE_EN = (
    "Moonky Island: when a decision belongs to the user (a choice, an approval to send, validate or delete), ask it "
    "with the AskUserQuestion tool, which they see in the island at the top of the screen, rather than in your text "
    "or in the `ask` field of wrap_up: a question that stands on its own, 2 to 4 short options, your recommendation "
    "first followed by \"(recommended)\". Open-ended questions (a name, an amount, a text to provide) and questions "
    "from sessions without AskUserQuestion (scheduled tasks) stay in the text."
)


def contexte():
    if commun.coupe():
        return ''
    manque = commun.manque()
    if manque:
        installer = os.path.join(commun.RACINE, 'installer.py')
        return commun.t(
            "Moonky Island : l'extension est installée mais l'îlot ne peut pas encore s'afficher sur ce PC "
            f"({manque}). Si l'utilisateur demande pourquoi ses questions n'apparaissent pas en haut de l'écran, "
            f"la commande py -3.12-64 \"{installer}\" termine l'installation et dit ce qui manque.",
            "Moonky Island: the plugin is installed but the island cannot show up on this PC yet "
            f"({manque}). If the user asks why their questions do not appear at the top of the screen, "
            f'the command py -3.12-64 "{installer}" finishes the setup and says what is missing.')
    return commun.t(REGLE_FR, REGLE_EN)


def main():
    try:
        try:
            if sys.stdin is not None:
                sys.stdin.buffer.read()
        except Exception:  # noqa: BLE001
            pass
        texte = contexte()
        if texte:
            sortie = {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': texte}}
            sys.stdout.write(json.dumps(sortie))  # ASCII seulement (accents échappés)
            sys.stdout.flush()
    except Exception as e:  # noqa: BLE001
        commun.noter('rappel', f'erreur : {e!r}')


if __name__ == '__main__':
    main()
