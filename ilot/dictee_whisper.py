# -*- coding: utf-8 -*-
"""
Dictée de l'îlot : transcrit en local les enregistrements du micro de l'îlot.

Lancé par l'îlot avec le Python de Whisper (réglage whisper_python, par défaut
whisper\\venv du dossier de données, où faster-whisper est installé) dès que
l'îlot s'affiche : le modèle se charge pendant que l'utilisateur lit la
question et parle. Écrit « pret cuda » ou « pret cpu » une fois le modèle
chargé, puis, pour chaque chemin de fichier reçu sur l'entrée standard, une
ligne JSON {"texte": …}. Rien n'est envoyé sur internet (HF_HUB_OFFLINE) : le
modèle est lu dans un dossier local que l'îlot passe dans ILOT_WHISPER_MODELE,
et seuls les fichiers du dossier des dictées (ILOT_DICTEES) sont transcrits.

Carte graphique (CUDA, float16) d'abord, processeur (int8) en repli ; variable
ILOT_WHISPER_CPU=1 pour forcer le processeur. C'est l'îlot qui borne les
attentes (chargement qui n'aboutit pas, transcription trop lente) et lance au
besoin un second travailleur sur le processeur. Le journal whisper note, ligne
par ligne avec le numéro du processus, le moteur et les durées, jamais le texte.
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ['HF_HUB_OFFLINE'] = '1'


def depuis_env(variable):
    valeur = os.environ.get(variable, '').strip()
    return Path(valeur).resolve() if valeur else None


MODELE = depuis_env('ILOT_WHISPER_MODELE')  # dossier local du modèle (model.bin, config.json, tokenizer.json…)
DICTEES = depuis_env('ILOT_DICTEES')  # seul dossier dont les fichiers peuvent être transcrits
# langue parlée choisie par l'îlot (fr, en, de…) ; vide : Whisper la reconnaît seul
LANGUE = os.environ.get('ILOT_WHISPER_LANGUE', '').strip().lower() or None
EN_ANGLAIS = os.environ.get('ILOT_LANGUE') == 'en'


def journal(message):
    print(time.strftime('%Y-%m-%d %H:%M:%S ') + f'[{os.getpid()}] ' + message, file=sys.stderr, flush=True)


def charger():
    processeur = bool(os.environ.get('ILOT_WHISPER_CPU'))
    journal('démarrage, ' + ('processeur imposé' if processeur else 'carte graphique d’abord'))
    depart = time.time()
    cuda = os.environ.get('CUDA_PATH')
    if cuda and os.path.isdir(os.path.join(cuda, 'bin')):
        os.add_dll_directory(os.path.join(cuda, 'bin'))
    import numpy as np
    from faster_whisper import WhisperModel
    journal(f'bibliothèques chargées en {time.time() - depart:.1f} s')

    moteurs = [('cpu', 'int8', 1)] if processeur else [('cuda', 'float16', 5), ('cpu', 'int8', 1)]
    for appareil, calcul, faisceau in moteurs:
        try:
            depart = time.time()
            modele = WhisperModel(str(MODELE), device=appareil, compute_type=calcul,
                                  cpu_threads=os.cpu_count() or 4)
            if appareil == 'cuda':
                # échauffement sur une seconde de silence : vérifie que la carte calcule vraiment. Pas sur le
                # processeur, où il coûterait un passage complet de l'encodeur sans rien vérifier de plus.
                segments, _ = modele.transcribe(np.zeros(16000, dtype=np.float32), language='fr', beam_size=1,
                                                vad_filter=False, without_timestamps=True)
                list(segments)
            journal(f'modèle chargé sur {appareil} ({calcul}) en {time.time() - depart:.1f} s')
            return modele, faisceau, appareil
        except Exception as e:  # noqa: BLE001
            journal(f'échec sur {appareil} : {e}')
    raise RuntimeError('aucun moteur de transcription disponible')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    if MODELE is None or DICTEES is None:
        journal('ILOT_WHISPER_MODELE ou ILOT_DICTEES manquant : ce travailleur se lance depuis l’îlot')
        sys.exit(2)
    modele, faisceau, appareil = charger()
    print(f'pret {appareil}', flush=True)
    for ligne in sys.stdin:
        if not ligne.strip():
            break
        chemin = Path(ligne.strip()).resolve()
        if DICTEES not in chemin.parents or not chemin.is_file():
            print(json.dumps({'erreur': 'file refused' if EN_ANGLAIS else 'fichier refusé'}), flush=True)
            continue
        try:
            depart = time.time()
            segments, info = modele.transcribe(str(chemin), language=LANGUE, beam_size=faisceau, vad_filter=True,
                                               without_timestamps=True, condition_on_previous_text=False)
            texte = ' '.join(s.text.strip() for s in segments).strip()
            journal(f'{info.duration:.1f} s d’audio transcrites en {time.time() - depart:.1f} s sur {appareil}')
            print(json.dumps({'texte': texte}), flush=True)
        except Exception as e:  # noqa: BLE001
            journal(f'échec de transcription sur {appareil} : {e}')
            print(json.dumps({'erreur': str(e)}), flush=True)


if __name__ == '__main__':
    main()
