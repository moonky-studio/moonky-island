# -*- coding: utf-8 -*-
"""
Chemins, réglages, langue et garde-fous communs aux scripts de Moonky Island (l'îlot).

Le dossier de l'extension est remplacé à chaque mise à jour : tout ce qu'elle écrit vit dans un dossier
de données à part, %LOCALAPPDATA%\\moonky-ilot par défaut, ou le dossier donné par la variable
MOONKY_ILOT_DONNEES (essais) :

    lib\\            pywebview et pythonnet, installés par installer.py
    reglages.json   son, dictée, pastille, garde-fou, langue (voir le README de l'extension)
    coupe           s'il existe, l'extension ne fait plus rien, sans être désinstallée
    journaux\\       un fichier par jour et par script, effacés au bout de 7 jours
    etat\\           garde-fou des questions, carte graphique écartée pour Whisper
    places\\         îlots ouverts, pour les empiler
    attente\\        pastilles « attend ta réponse » en cours
    webview\\        profils WebView2 des fenêtres
    dictees\\        enregistrements en cours de transcription, effacés aussitôt
    whisper\\        dictée locale, seulement si elle est installée (installer.py --whisper)

Aucune fonction de ce module ne lève d'erreur pour un fichier absent ou illisible : l'îlot ne doit
jamais gêner Claude.
"""
import functools
import glob
import hashlib
import json
import os
import struct
import sys
import time

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)  # dossier de l'extension
ESSAI = bool(os.environ.get('ILOT_ESSAI'))
VERSION_PYTHON = (3, 12)
JOURS_DE_JOURNAUX = 7
# début du message du garde-fou : la pastille reconnaît ainsi un wrap_up refusé ; l'ancienne marque reste
# reconnue, pour les discussions commencées avec une version précédente
MARQUE_GARDE = 'Moonky Island'
MARQUES_GARDE = (MARQUE_GARDE, 'Îlot Moonky :')
# début du titre des fenêtres de l'îlot et de la pastille ; l'ancien préfixe reste reconnu, une fenêtre d'avant
# le renommage pouvant encore être ouverte pendant une mise à jour
TITRE_FENETRE = 'Moonky Island · '
TITRES_FENETRE = (TITRE_FENETRE, 'Îlot · ')


def _donnees():
    choisi = os.environ.get('MOONKY_ILOT_DONNEES')
    if choisi:
        return os.path.abspath(choisi)
    return os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'moonky-ilot')


DONNEES = _donnees()
LIB = os.path.join(DONNEES, 'lib')
REGLAGES = os.path.join(DONNEES, 'reglages.json')
COUPE = os.path.join(DONNEES, 'coupe')
JOURNAUX = os.path.join(DONNEES, 'journaux')
ETAT = os.path.join(DONNEES, 'etat')
PLACES = os.path.join(DONNEES, 'places')
ATTENTES = os.path.join(DONNEES, 'attente' + ('-essai' if ESSAI else ''))
PROFILS = os.path.join(DONNEES, 'webview')
DICTEES = os.path.join(DONNEES, 'dictees')
WHISPER = os.path.join(DONNEES, 'whisper')
# propre au dossier de données : une installation d'essai ne croise jamais la vraie
SUFFIXE = hashlib.sha1(os.path.normcase(DONNEES).encode('utf-8')).hexdigest()[:8]

DEFAUTS = {
    'son': 'marimba',
    'dictee': False,
    'pastille': True,
    'pastille_plein_ecran': False,
    'whisper_python': '',
    'whisper_modele': '',
    'garde_fou': False,
    'langue': 'auto',
    'dictee_langue': 'auto',
}


def windows():
    return sys.platform == 'win32'


def coupe():
    """Coupe-circuit : tant que le fichier « coupe » existe, l'extension ne fait rien."""
    return os.path.exists(COUPE)


def oui(valeur):
    return valeur is True or str(valeur).strip().lower() in ('true', 'oui', 'yes', '1', 'on')


def reglages():
    """Réglages de reglages.json, complétés par les valeurs par défaut."""
    r = dict(DEFAUTS)
    try:
        with open(REGLAGES, encoding='utf-8-sig') as f:
            lus = json.load(f)
        if isinstance(lus, dict):
            r.update(lus)
    except (OSError, ValueError):
        pass
    return r


@functools.lru_cache(maxsize=1)
def langue():
    """'fr' ou 'en' : réglage « langue » s'il vaut fr ou en, sinon la langue de l'interface de Windows. La variable
    d'environnement ILOT_LANGUE passe avant le réglage (les essais l'utilisent pour ne pas dépendre de Windows)."""
    choisi = str(os.environ.get('ILOT_LANGUE') or reglages().get('langue') or '').strip().lower()
    if choisi in ('fr', 'en'):
        return choisi
    try:
        import ctypes
        # identifiant de langue principal (10 bits du bas) : 0x0C pour le français, quel que soit le pays
        return 'fr' if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x0C else 'en'
    except Exception:  # noqa: BLE001
        return 'en'


def t(fr, en):
    """Texte dans la langue de l'utilisateur."""
    return fr if langue() == 'fr' else en


def purger_journaux(jours=JOURS_DE_JOURNAUX):
    limite = time.time() - jours * 86400
    for f in glob.glob(os.path.join(JOURNAUX, '*.log')):
        try:
            if os.path.getmtime(f) < limite:
                os.remove(f)
        except OSError:
            pass


def chemin_journal(nom):
    """Journal du jour de ce script (nom-AAAAMMJJ.log) ; le premier du jour efface ceux de plus de 7 jours."""
    chemin = os.path.join(JOURNAUX, f'{nom}-{time.strftime("%Y%m%d")}.log')
    if not os.path.exists(chemin):
        try:
            os.makedirs(JOURNAUX, exist_ok=True)
            purger_journaux()
        except OSError:
            pass
    return chemin


def noter(nom, message):
    """Une ligne datée dans le journal du jour du script nom."""
    try:
        with open(chemin_journal(nom), 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + ('[essai] ' if ESSAI else '') + message + '\n')
    except Exception:  # noqa: BLE001
        pass


def lib_presente():
    return (os.path.isfile(os.path.join(LIB, 'webview', '__init__.py'))
            and os.path.isfile(os.path.join(LIB, 'pythonnet', '__init__.py')))


def webview2_version():
    """Version du runtime WebView2 installé (clés de registre documentées par Microsoft), ou ''."""
    try:
        import winreg
    except ImportError:
        return ''
    cle = 'Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    for racine, chemin in ((winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\WOW6432Node\\' + cle),
                           (winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\' + cle),
                           (winreg.HKEY_CURRENT_USER, 'Software\\' + cle)):
        try:
            with winreg.OpenKey(racine, chemin) as k:
                version = str(winreg.QueryValueEx(k, 'pv')[0] or '').strip()
        except OSError:
            continue
        if version and version != '0.0.0.0':
            return version
    return ''


def python_attendu():
    return sys.version_info[:2] == VERSION_PYTHON and struct.calcsize('P') == 8


def manque():
    """Ce qui empêche l'îlot de s'afficher sur ce PC, en clair ; '' si rien ne manque."""
    if not windows():
        return t('pas sous Windows', 'not on Windows')
    if not python_attendu():
        v = sys.version_info
        bits = struct.calcsize('P') * 8
        return t(f'Python {v[0]}.{v[1]} {bits} bits au lieu de 3.12 64 bits',
                 f'Python {v[0]}.{v[1]} {bits}-bit instead of 3.12 64-bit')
    if not lib_presente():
        return t('bibliothèques pas installées', 'libraries not installed')
    if not webview2_version():
        return t('WebView2 absent', 'WebView2 missing')
    return ''


def whisper_python():
    choisi = str(reglages().get('whisper_python') or '').strip()
    if choisi:
        return os.path.expandvars(choisi)
    return os.path.join(WHISPER, 'venv', 'Scripts', 'python.exe')


def whisper_modele():
    choisi = str(reglages().get('whisper_modele') or '').strip()
    if choisi:
        return os.path.expandvars(choisi)
    return os.path.join(WHISPER, 'modele')


def dictee_langue():
    """Langue parlée pour Whisper : réglage « dictee_langue » (fr, en, de…) ; « auto » : le français si l'îlot
    est en français, sinon '' et Whisper reconnaît la langue seul."""
    choisi = str(reglages().get('dictee_langue') or '').strip().lower()
    if choisi and choisi != 'auto':
        return choisi
    return 'fr' if langue() == 'fr' else ''


def dictee_active():
    """Micro proposé seulement si la dictée est activée et que Whisper et son modèle sont bien là."""
    return (oui(reglages().get('dictee')) and os.path.isfile(whisper_python())
            and os.path.isfile(os.path.join(whisper_modele(), 'model.bin')))
