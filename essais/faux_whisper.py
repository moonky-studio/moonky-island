# Faux Whisper pour essai_dictee.py : même protocole que dictee_whisper.py, sans modèle ni audio.
# Le comportement vient de FAUX_MODE_CARTE / FAUX_MODE_CPU :
#   rapide              prêt en 0,2 s, transcrit en 0,1 s
#   jamais_pret         ne dit jamais « pret »
#   crash_chargement    s'arrête au chargement, sans « pret »
#   lent_transcription  prêt vite, chaque transcription dure 30 s
#   crash_transcription prêt vite, s'arrête à la première transcription
#   pret_cpu            lancé pour la carte, se replie lui-même sur le processeur (« pret cpu »)
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
processeur = bool(os.environ.get('ILOT_WHISPER_CPU'))
mode = os.environ.get('FAUX_MODE_CPU' if processeur else 'FAUX_MODE_CARTE', 'rapide')
appareil = 'cpu' if processeur else 'cuda'

journal = os.environ.get('FAUX_JOURNAL')
if journal:
    with open(journal, 'a', encoding='utf-8') as f:
        f.write(f'{os.getpid()} {appareil} {mode}\n')

if mode == 'jamais_pret':
    time.sleep(60)  # filet : ne survit jamais plus d'une minute
    sys.exit(0)
if mode == 'crash_chargement':
    time.sleep(0.2)
    sys.exit(3)
time.sleep(0.2)
if mode == 'pret_cpu':
    appareil = 'cpu'
print(f'pret {appareil}', flush=True)
for ligne in sys.stdin:
    if not ligne.strip():
        break
    if mode == 'crash_transcription':
        sys.exit(4)
    time.sleep(30 if mode == 'lent_transcription' else 0.1)
    print(json.dumps({'texte': f'texte {appareil}'}), flush=True)
