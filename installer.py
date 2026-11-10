# -*- coding: utf-8 -*-
"""
Installation de Moonky Island (l'îlot) sur ce PC, à lancer après `claude plugin install moonky-island@moonky-island`.
Sans danger à relancer : ce qui est déjà en place est gardé. Messages en français ou en anglais selon la langue de
Windows (réglage « langue »), options dans les deux langues.

    py -3.12-64 installer.py                       installe ou répare les bibliothèques et les réglages, puis vérifie
    py -3.12-64 installer.py --verifier, --check   dit ce qui est en place et ce qui manque, sans rien changer
    py -3.12-64 installer.py --couper, --off       coupe l'extension sans la désinstaller
    py -3.12-64 installer.py --reprendre, --on     la remet en marche
    py -3.12-64 installer.py --whisper             ajoute la dictée locale (facultatif, environ 2 Go sur le disque)
    py -3.12-64 installer.py --forcer, --force     réinstalle les bibliothèques même si elles sont à jour

Tout s'écrit dans le dossier de données (%LOCALAPPDATA%\\moonky-ilot, voir ilot\\commun.py), jamais dans le
dossier de l'extension, qui est remplacé à chaque mise à jour. L'installateur n'ouvre aucune fenêtre et ne joue
aucun son.
"""
import sys

if sys.platform != 'win32':
    print('Moonky Island only runs on Windows: nothing to install here.')
    sys.exit(1)

import argparse  # noqa: E402
import glob  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import struct  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

RACINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(RACINE, 'ilot'))
import commun  # noqa: E402

# Versions installées ensemble sur le poste de maintenance (pywebview sur WebView2, par pythonnet).
PAQUETS = ['pywebview==6.2.1', 'pythonnet==3.2.1', 'clr_loader==0.3.1', 'cffi==2.1.1', 'pycparser==3.12',
           'bottle==0.13.4', 'proxy_tools==0.1.0', 'typing_extensions==4.16.0']
WHISPER_PAQUET = 'faster-whisper==1.2.1'
# le modèle « large-v3-turbo » de faster-whisper, et les fichiers que faster-whisper en télécharge
WHISPER_DEPOT = 'mobiuslabsgmbh/faster-whisper-large-v3-turbo'
WHISPER_FICHIERS = ['config.json', 'preprocessor_config.json', 'model.bin', 'tokenizer.json', 'vocabulary.*']
MODELE_COMPLET = ['config.json', 'preprocessor_config.json', 'model.bin', 'tokenizer.json', 'vocabulary.json']
# identifiant dans le catalogue de ce dépôt ; installée depuis un autre catalogue, l'extension est retrouvée par son dossier
EXTENSION = 'moonky-island@moonky-island'
LIEN_PYTHON = 'https://www.python.org/downloads/windows/'
LIEN_WEBVIEW2 = 'https://developer.microsoft.com/microsoft-edge/webview2/'
SANS_FENETRE = 0x08000000  # CREATE_NO_WINDOW
CETTE_COMMANDE = f'py -3.12-64 "{os.path.abspath(__file__)}"'


t = commun.t


def dire(texte=''):
    print(texte, flush=True)


def ligne(nom, valeur):
    dire(f'  {nom} : {valeur}' if commun.langue() == 'fr' else f'  {nom}: {valeur}')


# Python et lanceur py

def lanceur_py():
    """Le Python que lancent les hooks de l'extension (py.exe -3.12-64) : (chemin, version, bits), ou None."""
    py = shutil.which('py.exe')
    if not py:
        return None
    code = ('import struct, sys; print(sys.executable); print("%d.%d" % sys.version_info[:2]); '
            'print(struct.calcsize("P") * 8)')
    try:
        r = subprocess.run([py, '-3.12-64', '-I', '-X', 'utf8', '-c', code], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=60, creationflags=SANS_FENETRE)
    except (OSError, subprocess.SubprocessError):
        return None
    lignes = r.stdout.strip().splitlines()
    if r.returncode != 0 or len(lignes) != 3:
        return None
    return lignes[0].strip(), lignes[1].strip(), lignes[2].strip()


def python_store(chemin):
    return 'WindowsApps' in chemin or 'PythonSoftwareFoundation' in chemin


def verifier_python(lanceur):
    """True si ce Python convient pour installer ; sinon dit quoi faire."""
    if commun.python_attendu():
        if python_store(sys.executable):
            dire(t("  Ce Python vient du Microsoft Store : il range ses fichiers ailleurs que les autres programmes. "
                   f"Installe plutôt Python 3.12 64 bits depuis {LIEN_PYTHON}, puis relance.",
                   "  This Python comes from the Microsoft Store, which stores its files apart from other programs. "
                   f"Install Python 3.12 64-bit from {LIEN_PYTHON} instead, then run this again."))
            return False
        return True
    v = sys.version_info
    bits = struct.calcsize('P') * 8
    dire(t(f"  Ce Python est {v[0]}.{v[1]} {bits} bits ; l'îlot demande Python 3.12 64 bits.",
           f'  This Python is {v[0]}.{v[1]} {bits}-bit; Moonky Island needs Python 3.12 64-bit.'))
    if lanceur and lanceur[1:] == ('3.12', '64'):
        dire(t(f'  Python 3.12 64 bits est bien installé ({lanceur[0]}). Relance avec :',
               f'  Python 3.12 64-bit is installed ({lanceur[0]}). Run this again with:'))
    else:
        dire(t(f"  Installe Python 3.12 64 bits depuis {LIEN_PYTHON} (programme d'installation Windows 64 bits, "
               "case « py launcher » cochée), puis relance avec :",
               f'  Install Python 3.12 64-bit from {LIEN_PYTHON} (Windows installer 64-bit, with the '
               '"py launcher" box ticked), then run this again with:'))
    dire(f'    {CETTE_COMMANDE}')
    return False


def lanceur_ok(lanceur):
    return bool(lanceur) and lanceur[1:] == ('3.12', '64') and not python_store(lanceur[0])


def pythonw(lanceur):
    """pythonw.exe à côté du Python des hooks : l'îlot s'en sert pour lancer la pastille sans console."""
    return os.path.join(os.path.dirname(lanceur[0] if lanceur else sys.executable), 'pythonw.exe')


# Bibliothèques (pywebview, pythonnet)

def nom_normal(nom):
    return re.sub(r'[-_.]+', '_', nom).lower()


def versions(lib):
    """Paquets présents dans lib, {nom normalisé: version}, d'après leurs dossiers *.dist-info."""
    trouves = {}
    for chemin in glob.glob(os.path.join(lib, '*.dist-info')):
        nom, _, version = os.path.basename(chemin)[:-len('.dist-info')].partition('-')
        trouves[nom_normal(nom)] = version
    return trouves


def ecarts(lib):
    """Paquets absents de lib ou d'une autre version que celle attendue."""
    presents = versions(lib)
    resultat = []
    for paquet in PAQUETS:
        nom, version = paquet.split('==')
        trouve = presents.get(nom_normal(nom))
        if trouve != version:
            resultat.append(f'{nom} {version}' + (t(f' (trouvé {trouve})', f' (found {trouve})') if trouve else ''))
    return resultat


def renommer(source, cible, essais=5):
    """os.rename avec quelques secondes de patience (antivirus qui lit les fichiers tout juste écrits)."""
    for i in range(essais):
        try:
            os.rename(source, cible)
            return True
        except OSError:
            if i + 1 < essais:
                time.sleep(1)
    return False


def remplacer(nouveau, lib):
    """Met la nouvelle lib à la place de l'ancienne ; False si l'ancienne est en cours d'utilisation."""
    ancien = lib + '.ancien-' + time.strftime('%Y%m%d-%H%M%S')
    if os.path.exists(lib) and not renommer(lib, ancien):
        return False
    if not renommer(nouveau, lib):
        if os.path.exists(ancien):
            renommer(ancien, lib)
        return False
    shutil.rmtree(ancien, ignore_errors=True)
    return True


def installer_lib(forcer):
    """(réussi, message)"""
    lib = commun.LIB
    nouveau = lib + '.nouveau'
    for reste in glob.glob(lib + '.ancien-*') + [nouveau]:
        shutil.rmtree(reste, ignore_errors=True)
    if not forcer and not ecarts(lib) and commun.lib_presente():
        return True, t('déjà à jour', 'already up to date')
    os.makedirs(commun.DONNEES, exist_ok=True)
    dire(t('  Téléchargement de pywebview et pythonnet (environ 7 Mo)…',
           '  Downloading pywebview and pythonnet (about 7 MB)…'))
    r = subprocess.run([sys.executable, '-m', 'pip', 'install', '--target', nouveau, '--prefer-binary',
                        '--no-input', '--disable-pip-version-check', '--no-warn-script-location', '-q', *PAQUETS])
    if r.returncode != 0 or ecarts(nouveau):
        shutil.rmtree(nouveau, ignore_errors=True)
        return False, t(f'pip a échoué (code {r.returncode}) : vérifie la connexion internet, puis relance',
                        f'pip failed (code {r.returncode}): check the internet connection, then run this again')
    if not remplacer(nouveau, lib):
        shutil.rmtree(nouveau, ignore_errors=True)
        return False, t("l'ancienne version est en cours d'utilisation : réponds ou ferme les îlots et la pastille "
                        "« attend ta réponse » affichés, puis relance",
                        'the old version is in use: answer or close the open islands and the "waiting for your '
                        'answer" pill, then run this again')
    return True, t('installées', 'installed')


def essai_import(python, webview2):
    """Charge pywebview et pythonnet dans un Python à part, sans ouvrir de fenêtre : '' si tout va bien."""
    code = 'import sys; sys.path.insert(0, sys.argv[1]); import webview, clr'
    if webview2:  # sans WebView2, pywebview se rabattrait sur Internet Explorer et l'écrirait dans le registre
        code += ("; from webview.platforms import winforms; "
                 "assert winforms.renderer == 'edgechromium', 'moteur ' + winforms.renderer")
    try:
        r = subprocess.run([python, '-I', '-X', 'utf8', '-c', code, commun.LIB], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=120, creationflags=SANS_FENETRE)
    except (OSError, subprocess.SubprocessError) as e:
        return repr(e)
    if r.returncode == 0:
        return ''
    fin = (r.stderr or r.stdout or '').strip().splitlines()[-3:]
    return ' / '.join(x.strip() for x in fin) or f'code {r.returncode}'


# Réglages

def lire_reglages():
    """reglages.json tel quel : dict, {} s'il n'existe pas, None s'il est illisible."""
    try:
        with open(commun.REGLAGES, encoding='utf-8-sig') as f:
            lus = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None
    return lus if isinstance(lus, dict) else None


def ecrire_reglages(valeurs):
    os.makedirs(commun.DONNEES, exist_ok=True)
    temporaire = commun.REGLAGES + '.nouveau'
    with open(temporaire, 'w', encoding='utf-8') as f:
        json.dump(valeurs, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(temporaire, commun.REGLAGES)


# Claude Code

def config_claude():
    return os.environ.get('CLAUDE_CONFIG_DIR') or os.path.join(os.path.expanduser('~'), '.claude')


def extensions_installees():
    """{identifiant: entrées} de installed_plugins.json ; {} s'il est absent ou illisible."""
    try:
        with open(os.path.join(config_claude(), 'plugins', 'installed_plugins.json'), encoding='utf-8-sig') as f:
            plugins = json.load(f).get('plugins') or {}
    except (OSError, ValueError, AttributeError):
        return {}
    return {k: v for k, v in plugins.items() if isinstance(v, list)} if isinstance(plugins, dict) else {}


def meme_dossier(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def extension_installee():
    """(identifiant, description) de cette extension dans Claude Code, retrouvée par son dossier d'installation (ou à
    défaut par son nom) quel que soit le catalogue d'où elle vient ; ('', '') si elle n'y est pas."""
    plugins = extensions_installees()
    identifiant = next((k for k, entrees in plugins.items()
                        if any(isinstance(e, dict) and e.get('installPath') and meme_dossier(e['installPath'], RACINE)
                               for e in entrees)), '')
    identifiant = identifiant or (EXTENSION if EXTENSION in plugins else '')
    identifiant = identifiant or next((k for k in plugins if k.startswith('moonky-island@')), '')
    morceaux = []
    for e in plugins.get(identifiant, []):
        if isinstance(e, dict):
            portee = (t('pour tous les dossiers', 'for all folders') if e.get('scope') == 'user'
                      else t('dans ', 'in ') + str(e.get('projectPath') or '?'))
            morceaux.append(f"version {e.get('version') or '?'}, {portee}")
    return identifiant, ' ; '.join(morceaux)


def autres_ilots(identifiant):
    """Autres extensions de l'îlot installées en plus de celle-ci (ancien nom moonky-ilot, autre catalogue)."""
    return sorted(k for k in extensions_installees()
                  if k != identifiant and k.split('@')[0] in ('moonky-ilot', 'moonky-island'))


def ilot_en_double():
    """Hooks de settings.json qui lancent déjà un îlot hors de cette extension (installation à la main)."""
    try:
        with open(os.path.join(config_claude(), 'settings.json'), encoding='utf-8-sig') as f:
            hooks = json.load(f).get('hooks') or {}
    except (OSError, ValueError, AttributeError):
        return []
    trouves = []
    for evenement, groupes in (hooks.items() if isinstance(hooks, dict) else []):
        for groupe in groupes if isinstance(groupes, list) else []:
            for hook in (groupe.get('hooks') or []) if isinstance(groupe, dict) else []:
                if not isinstance(hook, dict):
                    continue
                texte = ' '.join([str(hook.get('command') or '')] + [str(a) for a in hook.get('args') or []])
                if re.search(r'ilot\.py|attente\.py|qcm_ilot_guard', texte, re.I):
                    trouves.append(f'{evenement} : {texte.strip()[:120]}')
    return trouves


# Coupe-circuit

def couper():
    os.makedirs(commun.DONNEES, exist_ok=True)
    with open(commun.COUPE, 'w', encoding='utf-8') as f:
        f.write(f'Moonky Island off since {time.strftime("%Y-%m-%d %H:%M")}. To turn it back on: '
                f'{CETTE_COMMANDE} --on, or delete this file.\n')
    dire(t('Moonky Island coupé : les questions de Claude restent dans la discussion, sans îlot, pastille ni garde-fou.',
           "Moonky Island is off: Claude's questions stay in the chat, with no island, pill or guard."))
    dire(t("Un îlot ou une pastille déjà affichés restent jusqu'à leur réponse ou leur fermeture.",
           'An island or pill already on screen stays until it is answered or closed.'))
    dire(t(f'Pour le remettre en marche : {CETTE_COMMANDE} --reprendre',
           f'To turn it back on: {CETTE_COMMANDE} --on'))
    return 0


def reprendre():
    try:
        os.remove(commun.COUPE)
    except FileNotFoundError:
        dire(t("Moonky Island n'était pas coupé.", 'Moonky Island was not off.'))
        return 0
    except OSError as e:
        dire(t(f'Impossible de supprimer {commun.COUPE} : {e}', f'Could not delete {commun.COUPE}: {e}'))
        return 1
    dire(t("Moonky Island remis en marche : l'îlot s'affiche à la prochaine question de Claude.",
           "Moonky Island is back on: the island shows up at Claude's next question."))
    return 0


# Dictée (facultative)

def installer_whisper():
    dire()
    dire(t('Dictée locale : Whisper large-v3-turbo, environ 1,8 Go à télécharger et 2 Go sur le disque.',
           'Local dictation: Whisper large-v3-turbo, about 1.8 GB to download and 2 GB on disk.'))
    dire(t("  Compte 5 à 20 minutes selon la connexion. Tout reste sur ce PC : rien de ce qui est dicté n'est envoyé.",
           '  Allow 5 to 20 minutes depending on the connection. Everything stays on this PC: nothing you dictate '
           'is sent anywhere.'))
    venv = os.path.join(commun.WHISPER, 'venv')
    python_venv = os.path.join(venv, 'Scripts', 'python.exe')
    modele = os.path.join(commun.WHISPER, 'modele')
    if not os.path.isfile(python_venv):
        dire(t(f'  Environnement Python de la dictée : {venv}', f'  Python environment for dictation: {venv}'))
        r = subprocess.run([sys.executable, '-m', 'venv', venv])
        if r.returncode != 0 or not os.path.isfile(python_venv):
            dire(t("  La création de l'environnement Python de la dictée a échoué.",
                   '  Creating the Python environment for dictation failed.'))
            return False
    dire(t(f'  Installation de {WHISPER_PAQUET} et de ses dépendances (environ 150 Mo)…',
           f'  Installing {WHISPER_PAQUET} and its dependencies (about 150 MB)…'))
    r = subprocess.run([python_venv, '-m', 'pip', 'install', '--prefer-binary', '--no-input',
                        '--disable-pip-version-check', WHISPER_PAQUET])
    if r.returncode != 0:
        dire(t('  pip a échoué : vérifie la connexion internet, puis relance avec --whisper.',
               '  pip failed: check the internet connection, then run this again with --whisper.'))
        return False
    if all(os.path.isfile(os.path.join(modele, f)) for f in MODELE_COMPLET):
        dire(t(f'  Modèle déjà là : {modele}', f'  Model already there: {modele}'))
    else:
        dire(t(f'  Téléchargement du modèle (environ 1,6 Go) dans {modele}…',
               f'  Downloading the model (about 1.6 GB) to {modele}…'))
        code = ('import sys; from huggingface_hub import snapshot_download; '
                'snapshot_download(sys.argv[1], local_dir=sys.argv[2], allow_patterns=sys.argv[3:])')
        r = subprocess.run([python_venv, '-I', '-c', code, WHISPER_DEPOT, modele, *WHISPER_FICHIERS])
        if r.returncode != 0 or not os.path.isfile(os.path.join(modele, 'model.bin')):
            dire(t("  Téléchargement interrompu : relance avec --whisper, il reprend où il s'est arrêté.",
                   '  Download interrupted: run this again with --whisper, it resumes where it stopped.'))
            return False
    lus = lire_reglages()
    if lus is None:
        dire(t(f'  {commun.REGLAGES} est illisible : mets-y "dictee": true à la main.',
               f'  {commun.REGLAGES} cannot be read: add "dictee": true to it by hand.'))
        return False
    valeurs = dict(commun.DEFAUTS)
    valeurs.update(lus)
    valeurs['dictee'] = True
    ecrire_reglages(valeurs)
    if str(valeurs.get('whisper_python') or '').strip() or str(valeurs.get('whisper_modele') or '').strip():
        dire(t('  Les réglages whisper_python ou whisper_modele pointent ailleurs : la dictée utilise ces chemins-là, '
               "pas ce qui vient d'être installé. Vide-les pour utiliser cette installation.",
               '  The whisper_python or whisper_modele settings point elsewhere: dictation uses those paths, not '
               'what was just installed. Empty them to use this installation.'))
    dire(t("  Carte graphique : la dictée s'en sert si CUDA 12 et cuDNN 9 sont installés (variable CUDA_PATH) ; "
           'sinon elle tourne sur le processeur, plus lentement.',
           '  Graphics card: dictation uses it if CUDA 12 and cuDNN 9 are installed (CUDA_PATH variable); '
           'otherwise it runs on the processor, more slowly.'))
    return True


# Vérification et installation

def verifier():
    """Dit ce qui est en place ; True si l'îlot peut s'afficher sur ce PC."""
    lanceur = lanceur_py()
    v = sys.version_info
    bits = struct.calcsize('P') * 8
    ligne(t('Python qui lance ce script', 'Python running this script'),
          f"{v[0]}.{v[1]}.{v[2]} {t(f'{bits} bits', f'{bits}-bit')} ({sys.executable})")
    nom_lanceur = t('Python des hooks (py -3.12-64)', 'Python for the hooks (py -3.12-64)')
    if lanceur_ok(lanceur):
        ligne(nom_lanceur, lanceur[0])
    else:
        ligne(nom_lanceur, t('introuvable : installe Python 3.12 64 bits de python.org, case « py launcher » cochée',
                             'not found: install Python 3.12 64-bit from python.org, with the "py launcher" box '
                             'ticked'))
    ok = lanceur_ok(lanceur)
    if ok and not os.path.isfile(pythonw(lanceur)):
        ligne('pythonw.exe', t(f"absent à côté de {lanceur[0]} : la pastille s'ouvrira avec une console",
                               f'missing next to {lanceur[0]}: the pill will open with a console window'))
    webview2 = commun.webview2_version()
    ligne('WebView2', webview2 or t(f'absent : installe le « Evergreen Bootstrapper » depuis {LIEN_WEBVIEW2}',
                                    f'missing: install the "Evergreen Bootstrapper" from {LIEN_WEBVIEW2}'))
    ok = ok and bool(webview2)
    manquants = ecarts(commun.LIB)
    nom_lib = t('Bibliothèques', 'Libraries')
    if manquants:
        ligne(nom_lib, t('à installer (', 'to install (') + ', '.join(manquants) + ')')
        ok = False
    else:
        ligne(nom_lib, t(f'à jour dans {commun.LIB}', f'up to date in {commun.LIB}'))
        if lanceur_ok(lanceur):
            erreur = essai_import(lanceur[0], bool(webview2))
            ligne(t('Chargement de pywebview', 'Loading pywebview'),
                  t('réussi', 'OK') if not erreur else t(f'échec : {erreur}', f'failed: {erreur}'))
            ok = ok and not erreur
    r = commun.reglages()
    lus = lire_reglages()
    nom_reglages = t('Réglages', 'Settings')

    def oui_non(valeur):
        return t('oui', 'yes') if commun.oui(valeur) else t('non', 'no')

    if lus is None:
        ligne(nom_reglages, t(f'{commun.REGLAGES} illisible : valeurs par défaut utilisées',
                              f'{commun.REGLAGES} cannot be read: default values used'))
    else:
        pastille = r.get('pastille')
        pastille = 'observation' if str(pastille).strip().lower() == 'observation' else oui_non(pastille)
        ou = commun.REGLAGES if os.path.exists(commun.REGLAGES) else t(
            'valeurs par défaut, fichier pas encore créé', 'default values, file not created yet')
        ligne(nom_reglages, t(f"son {r.get('son')}, pastille {pastille}, dictée {oui_non(r.get('dictee'))}, "
                              f"garde-fou {oui_non(r.get('garde_fou'))}, langue {r.get('langue')} ({ou})",
                              f"sound {r.get('son')}, pill {pastille}, dictation {oui_non(r.get('dictee'))}, "
                              f"guard {oui_non(r.get('garde_fou'))}, language {r.get('langue')} ({ou})"))
    nom_dictee = t('Dictée', 'Dictation')
    if commun.dictee_active():
        ligne(nom_dictee, t(f'prête ({commun.whisper_python()})', f'ready ({commun.whisper_python()})'))
    elif commun.oui(r.get('dictee')):
        ligne(nom_dictee, t(f'activée mais Whisper ou son modèle manquent : {CETTE_COMMANDE} --whisper',
                            f'turned on but Whisper or its model is missing: {CETTE_COMMANDE} --whisper'))
    else:
        ligne(nom_dictee, t('pas installée (facultative : --whisper)', 'not installed (optional: --whisper)'))
    identifiant, installee = extension_installee()
    ligne(t('Extension dans Claude Code', 'Plugin in Claude Code'),
          f'{identifiant}, {installee}' if installee else t(f'pas trouvée : claude plugin install {EXTENSION}',
                                                           f'not found: claude plugin install {EXTENSION}'))
    autres = autres_ilots(identifiant)
    if autres and not identifiant:
        ligne(t('Autre installation', 'Other installation'), ', '.join(autres))
    elif autres:
        ligne(t('Attention', 'Warning'),
              t("une autre installation de l'îlot est active : chaque question ouvrirait deux îlots. "
                'Désinstalle-la avec claude plugin uninstall ',
                'another installation of the island is active: each question would open two islands. '
                'Uninstall it with claude plugin uninstall ') + ', '.join(autres))
        ok = False
    doubles = ilot_en_double()
    if doubles:
        ligne(t('Attention', 'Warning'),
              t('settings.json lance déjà un îlot installé à la main : chaque question en ouvrirait deux. '
                'Retire ces hooks (voir le README) :',
                'settings.json already runs an island installed by hand: each question would open two. '
                'Remove these hooks (see the README):'))
        for d in doubles:
            dire(f'      {d}')
        ok = False
    if commun.coupe():
        ligne(t('Coupe-circuit', 'Off switch'),
              t(f"actif, l'îlot ne fait rien ({CETTE_COMMANDE} --reprendre le rallume)",
                f'on, the island does nothing ({CETTE_COMMANDE} --on turns it back on)'))
    return ok


def installer(forcer, whisper):
    dire(t(f'Moonky Island : installation sur ce PC (dossier de données {commun.DONNEES})',
           f'Moonky Island: setting up on this PC (data folder {commun.DONNEES})'))
    lanceur = lanceur_py()
    if not verifier_python(lanceur):
        return 1
    if not lanceur_ok(lanceur):
        dire(t("  Le lanceur py ne trouve pas Python 3.12 64 bits : les hooks de l'extension, qui passent par "
               '« py.exe -3.12-64 », ne pourraient pas tourner.',
               '  The py launcher cannot find Python 3.12 64-bit: the plugin hooks, which go through '
               '"py.exe -3.12-64", could not run.'))
        dire(t(f'  Réinstalle Python 3.12 64 bits depuis {LIEN_PYTHON} avec la case « py launcher » cochée, '
               'puis relance.',
               f'  Reinstall Python 3.12 64-bit from {LIEN_PYTHON} with the "py launcher" box ticked, then run '
               'this again.'))
        return 1
    if importlib.util.find_spec('pip') is None:
        dire(t('  pip manque dans ce Python : lance « py -3.12-64 -m ensurepip --upgrade », puis relance.',
               '  pip is missing from this Python: run "py -3.12-64 -m ensurepip --upgrade", then run this again.'))
        return 1
    reussi, message = installer_lib(forcer)
    ligne(t('Bibliothèques', 'Libraries'), message)
    if not reussi:
        return 1
    lus = lire_reglages()
    if lus == {} and not os.path.exists(commun.REGLAGES):
        ecrire_reglages(dict(commun.DEFAUTS))
        ligne(t('Réglages', 'Settings'), t(f'créés avec les valeurs par défaut ({commun.REGLAGES})',
                                           f'created with default values ({commun.REGLAGES})'))
    if whisper and not installer_whisper():
        return 1
    dire()
    dire(t('État :', 'Status:'))
    ok = verifier()
    dire()
    if ok:
        dire(t("L'îlot est prêt. Les sessions Claude ouvertes avant l'installation de l'extension n'ont pas ses "
               'hooks : ouvre une nouvelle session.',
               'The island is ready. Claude sessions opened before the plugin was installed do not have its '
               'hooks: open a new session.'))
        dire(t("Pour voir un îlot de démonstration (avec son, rien n'est envoyé) :",
               'To see a demo island (with sound, nothing is sent):'))
        dire(f'    py -3.12-64 "{os.path.join(RACINE, "ilot", "ilot.py")}" --demo')
    else:
        dire(t("L'îlot ne peut pas encore s'afficher : règle les points ci-dessus, puis relance cette commande. "
               'En attendant, Claude pose ses questions dans la discussion, comme avant.',
               'The island cannot show up yet: fix the points above, then run this command again. '
               'Until then, Claude asks its questions in the chat, as usual.'))
    return 0 if ok else 1


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    parser = argparse.ArgumentParser(description=t('Installe, vérifie ou coupe Moonky Island sur ce PC.',
                                                   'Set up, check or turn off Moonky Island on this PC.'))
    choix = parser.add_mutually_exclusive_group()
    choix.add_argument('--verifier', '--check', action='store_true',
                       help=t('dire ce qui est en place, sans rien changer', 'say what is in place, change nothing'))
    choix.add_argument('--couper', '--off', action='store_true',
                       help=t("couper l'îlot sans désinstaller l'extension", 'turn the island off, keep the plugin'))
    choix.add_argument('--reprendre', '--on', action='store_true',
                       help=t("remettre l'îlot en marche", 'turn the island back on'))
    choix.add_argument('--whisper', action='store_true',
                       help=t('installer aussi la dictée locale (environ 2 Go)',
                              'also install local dictation (about 2 GB)'))
    parser.add_argument('--forcer', '--force', action='store_true',
                        help=t('réinstaller les bibliothèques même à jour',
                               'reinstall the libraries even if up to date'))
    args = parser.parse_args()
    if args.couper:
        return couper()
    if args.reprendre:
        return reprendre()
    if args.verifier:
        dire(t(f'Moonky Island sur ce PC (dossier de données {commun.DONNEES}) :',
               f'Moonky Island on this PC (data folder {commun.DONNEES}):'))
        ok = verifier()
        dire()
        if ok:
            dire(t("L'îlot peut s'afficher.", 'The island can show up.'))
        else:
            dire(t("L'îlot ne peut pas s'afficher : voir ci-dessus.", 'The island cannot show up: see above.'))
        return 0 if ok else 1
    return installer(args.forcer, args.whisper)


if __name__ == '__main__':
    sys.exit(main())
