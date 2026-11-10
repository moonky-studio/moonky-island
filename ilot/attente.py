# -*- coding: utf-8 -*-
r"""
Pastille « attend ta réponse » de l'îlot (Windows).

Hook Stop de Claude Code. Quand une session finit son tour en attendant l'utilisateur, une pastille
de l'îlot montre le titre de la session et ce qu'elle attend ; un clic ouvre la discussion dans
Claude. On ne répond pas ici : c'est un rappel, en complément des questions de l'îlot.

Le hook ne fait que lancer un guetteur détaché puis rend la main : jamais rien sur la sortie,
jamais de blocage, toujours le code 0.

Le guetteur (--guetter) décide s'il y a attente :
- le tour finit par un wrap_up accepté qui pose une question (ask) ;
- sinon, le résumé de fin de tour de l'appli (postTurnSummary) demande une action
  (needs_action, rempli seulement en catégorie « blocked »).
Il se tait si l'utilisateur a déjà la session sous les yeux dans Claude, ou si un nouveau tour a
commencé entre-temps.

Ces renseignements viennent des fiches de session de l'appli Claude
(%APPDATA%\Claude\claude-code-sessions), un format interne que l'appli ne documente pas : s'il
change, la pastille se tait, sans rien gêner d'autre.

Chaque attente est un fichier du dossier de données (attente\, voir commun.py) au nom de la
session. Une seule fenêtre (--fenetre) les montre toutes, sous les îlots de questions, et retire
une attente quand l'utilisateur répond, ouvre ou ignore la session, ou qu'un nouveau tour commence.

L'îlot crée aussi une attente (--question) quand il rend à Claude une question restée 9 minutes
sans réponse : l'appli Claude couperait sinon la session, car une question qui attend dans un
hook compte pour elle comme du silence.

Comme les notifications de Windows, la pastille attend la fin d'un plein écran (jeu, vidéo,
diaporama), du mode présentation ou de l'écran verrouillé : elle se cache si elle était là, puis
revient. Le réglage pastille_plein_ecran la fait passer quand même.

Réglage « pastille » de reglages.json : true (par défaut), false (jamais de pastille) ou
"observation" (rien ne s'affiche, le journal note ce qui l'aurait été).

Démo, sans rien lire ni ouvrir : py -3.12-64 attente.py --demo (ILOT_TEST_AUTO=1 la déroule seule).
"""
import sys

if sys.platform != 'win32':  # la pastille ne sait s'afficher que sous Windows : ailleurs, rien
    if __name__ == '__main__':
        sys.exit(0)
    raise ImportError('la pastille ne fonctionne que sous Windows')

import ctypes
import glob
import json
import math
import os
import re
import subprocess
import threading
import time
import traceback
from ctypes import wintypes

ICI = os.path.dirname(os.path.abspath(__file__))
if '--demo' in sys.argv:
    os.environ['ILOT_ESSAI'] = '1'  # avant d'importer commun et ilot : ni son ni ouverture pendant la démo
if ICI not in sys.path:
    sys.path.insert(0, ICI)
import commun  # noqa: E402

ESSAI = commun.ESSAI
TEST = bool(os.environ.get('ILOT_TEST_AUTO'))
PAGE = os.path.join(ICI, 'attente.html')
# tout ce que la pastille écrit vit dans le dossier de données de l'extension (voir commun.py)
PLACES = commun.PLACES  # îlots de questions ouverts : la pastille se range sous eux
ENTREES = commun.ATTENTES
TRAITES = os.path.join(commun.ETAT, 'tours-traites' + ('-essai' if ESSAI else ''))
PROFIL = os.path.join(commun.PROFILS, 'attente-essai' if ESSAI else 'attente')
MUTEX = 'Local\\moonky-ilot-attente-' + commun.SUFFIXE + ('-essai' if ESSAI else '')
# fiches de session de l'appli Claude : format interne, non documenté (voir le README de l'extension)
FICHES = os.path.join(os.environ.get('APPDATA', ''), 'Claude', 'claude-code-sessions')
PYTHONW = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
TITRE = commun.t('En attente de ta réponse', 'Waiting for your answer')
DUREE_MAX = 12 * 3600  # une attente plus vieille que ça n'intéresse plus personne
NOM_SUR = re.compile(r'[A-Za-z0-9_-]{1,80}')


def noter(message):
    commun.noter('attente', message)


def mode_pastille():
    """Réglage « pastille » : 'oui' (par défaut), 'non' (jamais de pastille) ou 'observation'
    (rien ne s'affiche, le journal note ce qui l'aurait été)."""
    valeur = commun.reglages().get('pastille', True)
    if str(valeur).strip().lower() == 'observation':
        return 'observation'
    return 'oui' if commun.oui(valeur) else 'non'


def plein_ecran_permis():
    """Réglage pastille_plein_ecran : la pastille passe même pendant un plein écran ou une présentation."""
    return commun.oui(commun.reglages().get('pastille_plein_ecran'))


# ---------------------------------------------------------------------------
# Windows : fonctions natives (instances à part, pour ne pas toucher celles d'ilot et de pywebview)
# ---------------------------------------------------------------------------

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.OpenMutexW.restype = wintypes.HANDLE
k32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
k32.CreateMutexW.restype = wintypes.HANDLE
k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.OpenProcess.restype = wintypes.HANDLE
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                           ctypes.POINTER(wintypes.DWORD)]
usr = ctypes.WinDLL('user32', use_last_error=True)
usr.GetForegroundWindow.restype = ctypes.c_void_p
usr.GetForegroundWindow.argtypes = []
usr.GetWindowThreadProcessId.restype = wintypes.DWORD
usr.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
usr.GetWindowTextW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR, ctypes.c_int]


# ---------------------------------------------------------------------------
# Fiches de session de l'appli et transcription
# ---------------------------------------------------------------------------

def fiches_recentes():
    """(date, chemin) des fiches de session de l'appli, de la plus récemment écrite à la plus ancienne."""
    liste = []
    for chemin in glob.glob(os.path.join(FICHES, '*', '*', 'local_*.json')):
        try:
            liste.append((os.path.getmtime(chemin), chemin))
        except OSError:
            pass
    liste.sort(reverse=True)
    return liste


def tete(chemin, n=1024):
    try:
        with open(chemin, 'rb') as f:
            return f.read(n)
    except OSError:
        return b''


def trouver_fiche(cli):
    """Fiche de la session dont l'identifiant Claude Code est cli (il figure dans les 100 premiers octets)."""
    motif = re.compile(rb'"cliSessionId"\s*:\s*"' + re.escape(cli.encode('ascii')) + rb'"')
    for _, chemin in fiches_recentes():
        if motif.search(tete(chemin)):
            return chemin
    return None


def lire_fiche(chemin):
    for _ in range(4):
        try:
            with open(chemin, encoding='utf-8') as f:
                fiche = json.load(f)
            return fiche if isinstance(fiche, dict) else None
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            time.sleep(0.15)  # fiche en cours d'écriture par l'appli
    return None


def attendre(chemin, condition, delai, abandon=None, pas=0.5):
    """Relit la fiche à chaque changement jusqu'à condition(fiche).
    Renvoie (issue, dernière fiche lue), issue valant 'ok', 'abandon', 'delai' ou 'absente'."""
    limite = time.time() + delai
    vue, fiche = None, None
    while True:
        try:
            date = os.stat(chemin).st_mtime_ns
        except OSError:
            return 'absente', fiche
        if date != vue:
            lue = lire_fiche(chemin)
            if lue is not None:
                vue, fiche = date, lue
                if condition(fiche):
                    return 'ok', fiche
                if abandon is not None and abandon(fiche):
                    return 'abandon', fiche
        if time.time() >= limite:
            return 'delai', fiche
        time.sleep(pas)


def fin_transcription(chemin, taille=262144):
    try:
        with open(chemin, 'rb') as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - taille))
            brut = f.read()
    except OSError:
        return []
    lignes = brut.split(b'\n')
    if n > taille:
        lignes = lignes[1:]  # première ligne coupée
    entrees = []
    for ligne in lignes:
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            e = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(e, dict):
            entrees.append(e)
    return entrees


def texte_resultat(bloc):
    contenu = bloc.get('content')
    if isinstance(contenu, list):
        return ' '.join(str(x.get('text', '')) for x in contenu if isinstance(x, dict))
    return str(contenu or '')


def analyser_tour(entrees):
    """Dernier message de Claude (uuid) et question du dernier wrap_up accepté de ce tour ('' sans question)."""
    u0, debut = None, 0
    for i, e in enumerate(entrees):
        if e.get('isSidechain'):
            continue
        if e.get('type') == 'assistant':
            u0 = e.get('uuid') or u0
        elif e.get('type') == 'user' and not e.get('isMeta') and not e.get('isCompactSummary'):
            contenu = (e.get('message') or {}).get('content')
            if isinstance(contenu, list) and any(isinstance(b, dict) and b.get('type') == 'tool_result'
                                                 for b in contenu):
                continue  # résultat d'outil, pas un message de l'utilisateur
            debut = i  # dernier vrai message : début du tour
    appels, resultats = [], {}
    for e in entrees[debut:]:
        if e.get('isSidechain'):
            continue
        contenu = (e.get('message') or {}).get('content')
        if not isinstance(contenu, list):
            continue
        for b in contenu:
            if not isinstance(b, dict):
                continue
            if b.get('type') == 'tool_use' and b.get('name') == 'mcp__ccd_turn__wrap_up':
                appels.append(b)
            elif b.get('type') == 'tool_result' and b.get('tool_use_id'):
                resultats[b['tool_use_id']] = b
    for b in reversed(appels):
        r = resultats.get(b.get('id'))
        if r is not None and (r.get('is_error')
                              or any(m in texte_resultat(r) for m in commun.MARQUES_GARDE)):
            continue  # wrap_up refusé (par le garde-fou des questions ou autre) : la session l'a refait ensuite
        return u0, str((b.get('input') or {}).get('ask') or '').strip()
    return u0, ''


def propre(texte, limite=600):
    t = str(texte or '').replace('**', '').replace('`', '')
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\s*\n\s*', '\n', t).strip()
    if len(t) > limite:
        t = t[:limite - 1].rstrip() + '…'
    return t


# Le résumé de fin de tour de l'appli est parfois en anglais (7 sur 18 du 04 au 09/11/2026), même quand la
# session parle français : quand l'îlot est en français, la pastille montre alors un texte en français.
MOTS_ANGLAIS = frozenset('the to and or of for with into then if is are does do it its this that your you '
                         'reply answer choose decide send share paste say resume confirm approve review run '
                         'open should would which what when'.split())
MOTS_FRANCAIS = frozenset('le la les un une des du de au aux et ou à en pour avec sur dans par puis si que qui '
                          'ce cet cette ces je tu il elle nous vous moi toi ta ton tes mon ma mes sa son ses '
                          'est sont pas ne dire répondre faire ça'.split())
TEXTE_FRANCAIS = 'Attend ta réponse dans Claude'


def en_anglais(texte):
    """Vrai si le texte est surtout en anglais, même s'il cite quelques mots en français."""
    mots = re.findall(r'[a-zà-öø-ÿœ]+', str(texte or '').lower())
    anglais = sum(m in MOTS_ANGLAIS for m in mots)
    return anglais >= 2 and anglais > sum(m in MOTS_FRANCAIS for m in mots)


# ---------------------------------------------------------------------------
# Ce que l'utilisateur a sous les yeux
# ---------------------------------------------------------------------------

def titre_de(hwnd):
    tampon = ctypes.create_unicode_buffer(256)
    try:
        usr.GetWindowTextW(hwnd, tampon, 256)
    except Exception:  # noqa: BLE001
        return ''
    return tampon.value


def exe_de(pid):
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ''
    try:
        tampon = ctypes.create_unicode_buffer(1024)
        taille = wintypes.DWORD(1024)
        if k32.QueryFullProcessImageNameW(h, 0, tampon, ctypes.byref(taille)):
            return os.path.basename(tampon.value).lower()
        return ''
    finally:
        k32.CloseHandle(h)


def claude_au_premier_plan():
    h = usr.GetForegroundWindow()
    if not h or titre_de(h).startswith(commun.TITRES_FENETRE):
        return False
    pid = wintypes.DWORD(0)
    usr.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return bool(pid.value) and exe_de(pid.value) == 'claude.exe'


def session_au_premier_plan():
    """Session affichée dans Claude : celle dont lastFocusedAt est le plus récent (avant le 1er Ko)."""
    meilleur, local = 0, None
    for date, chemin in fiches_recentes():
        if date * 1000 + 2000 < meilleur:
            break  # fiche écrite avant ce focus : la sienne ne peut pas être plus récente
        h = tete(chemin, 4096)
        m = re.search(rb'"lastFocusedAt"\s*:\s*(\d+)', h)
        if m and int(m.group(1)) > meilleur:
            s = re.search(rb'"sessionId"\s*:\s*"([^"]+)"', h)
            if s:
                meilleur, local = int(m.group(1)), s.group(1).decode('ascii', 'replace')
    return local


sh32 = ctypes.WinDLL('shell32')
sh32.SHQueryUserNotificationState.argtypes = [ctypes.POINTER(ctypes.c_int)]
RETENUES = {1: 'écran verrouillé', 2: 'plein écran', 3: 'plein écran', 4: 'mode présentation'}


def occupe():
    """Ce qui retient la pastille, comme Windows retient ses notifications : plein écran (jeu, vidéo,
    diaporama), mode présentation ou écran verrouillé. None si rien. Les QCM de l'îlot passent toujours."""
    if TEST or plein_ecran_permis():
        return None
    etat = ctypes.c_int(0)
    try:
        if sh32.SHQueryUserNotificationState(ctypes.byref(etat)) != 0:
            return None
    except Exception:  # noqa: BLE001
        return None
    raison = RETENUES.get(etat.value)
    if raison in ('plein écran', 'mode présentation') and claude_au_premier_plan():
        return None  # Claude lui-même en plein écran : la pastille montre les autres sessions
    return raison


# ---------------------------------------------------------------------------
# Attentes (un fichier par session) et fenêtre unique
# ---------------------------------------------------------------------------

POIGNEE = None
VERROU_POIGNEE = threading.Lock()


def chemin_entree(local):
    return os.path.join(ENTREES, local + '.json')


def ecrire_entree(entree):
    os.makedirs(ENTREES, exist_ok=True)
    chemin = chemin_entree(entree['local'])
    provisoire = f'{chemin}.{os.getpid()}.tmp'
    with open(provisoire, 'w', encoding='utf-8') as f:
        json.dump(entree, f, ensure_ascii=False)
    os.replace(provisoire, chemin)  # la fenêtre ne lit jamais un fichier à moitié écrit
    return chemin


def lire_entrees():
    liste = []
    for chemin in glob.glob(os.path.join(ENTREES, '*.json')):
        try:
            with open(chemin, encoding='utf-8') as f:
                e = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(e, dict) and NOM_SUR.fullmatch(str(e.get('local', ''))):
            liste.append(e)
    liste.sort(key=lambda e: float(e.get('depuis') or 0), reverse=True)
    return liste


def retirer_entree(local, depuis=None):
    """Supprime l'attente, sauf si une plus récente l'a remplacée entre-temps."""
    if not NOM_SUR.fullmatch(str(local or '')):
        return False
    chemin = chemin_entree(local)
    try:
        if depuis is not None:
            with open(chemin, encoding='utf-8') as f:
                if json.load(f).get('depuis') != depuis:
                    return False
        os.remove(chemin)
        return True
    except (OSError, ValueError):
        return False


def deja_traite(local, u0):
    """Le hook Stop repasse à la reprise ou au compactage d'une session : un même tour ne compte qu'une fois."""
    try:
        with open(os.path.join(TRAITES, local), encoding='ascii') as f:
            return f.read().strip() == u0
    except (OSError, ValueError):
        return False


def marquer_traite(local, u0):
    try:
        os.makedirs(TRAITES, exist_ok=True)
        with open(os.path.join(TRAITES, local), 'w', encoding='ascii') as f:
            f.write(u0)
    except (OSError, ValueError):
        noter(f'{local} : tour non mémorisé : ' + traceback.format_exc())


def motif_retrait(e, focus=None, cache=None, vus=None):
    """Pourquoi retirer cette attente maintenant (None : elle reste).
    focus : session affichée dans Claude au premier plan ; vus compte les passages où elle l'était."""
    local, depuis = e.get('local'), float(e.get('depuis') or 0)
    if time.time() - depuis > DUREE_MAX:
        return 'plus de 12 h'
    chemin = e.get('fiche') or ''
    if not chemin:
        return None  # attente de démonstration
    try:
        date = os.stat(chemin).st_mtime_ns
    except OSError:
        return 'session supprimée'
    connu = cache.get(local) if cache is not None else None
    if not connu or connu[0] != date:
        fiche = lire_fiche(chemin)
        if fiche is None:
            return None
        connu = (date, fiche)
        if cache is not None:
            cache[local] = connu
    fiche = connu[1]
    if fiche.get('isArchived'):
        return 'session archivée'
    if (fiche.get('latestUserFrameAt') or 0) > depuis * 1000:
        return 'réponse donnée'
    bord = e.get('bord') or 0
    if bord and (fiche.get('lastTurnEdgeAt') or 0) > bord:
        return 'nouveau tour'
    if vus is not None:
        if focus and focus == local:
            vus[local] = vus.get(local, 0) + 1
            if vus[local] >= 2:
                return 'vue dans Claude'
        else:
            vus[local] = 0
    return None


def purger(liste, focus=None, cache=None, vus=None):
    """Retire du disque les attentes périmées et renvoie celles qui restent."""
    gardees = []
    for e in liste:
        pourquoi = motif_retrait(e, focus, cache, vus)
        if not pourquoi:
            gardees.append(e)
        elif retirer_entree(e.get('local'), e.get('depuis')):
            noter(f'attente retirée ({pourquoi}) : {str(e.get("titre", ""))[:60]}')
    return gardees


def vue(e):
    return {'local': str(e.get('local') or ''), 'titre': str(e.get('titre') or ''),
            'texte': str(e.get('texte') or ''), 'depuis': float(e.get('depuis') or 0)}


def signature(liste):
    return [(e.get('local'), e.get('depuis'), e.get('titre'), e.get('texte')) for e in liste]


def fenetre_ouverte():
    h = k32.OpenMutexW(0x00100000, False, MUTEX)  # SYNCHRONIZE
    if h:
        k32.CloseHandle(h)
        return True
    return False


def prendre_verrou():
    """Une seule fenêtre à la fois ; si l'autre est en train de se fermer, on lui laisse 3 s."""
    global POIGNEE
    limite = time.time() + 3
    while True:
        ctypes.set_last_error(0)
        h = k32.CreateMutexW(None, False, MUTEX)
        deja = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
        if h and not deja:
            with VERROU_POIGNEE:
                POIGNEE = h
            return True
        if h:
            k32.CloseHandle(h)
        if time.time() > limite:
            return False
        time.sleep(0.25)


def lacher_verrou():
    global POIGNEE
    with VERROU_POIGNEE:
        h, POIGNEE = POIGNEE, None
    if h:
        k32.CloseHandle(h)


def lancer_detache(args):
    exe = PYTHONW if os.path.isfile(PYTHONW) else sys.executable
    subprocess.Popen([exe, os.path.abspath(__file__)] + list(args), cwd=ICI, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x00000008 | 0x00000200 | 0x08000000)  # détaché, sans console


def rang_qcm():
    """Îlots de questions ouverts : la pastille se place sous eux."""
    import ilot
    n = 0
    for f in glob.glob(os.path.join(PLACES, '*.pid')):
        try:
            pid = int(os.path.basename(f)[:-4])
        except ValueError:
            continue
        if ilot.vivant(pid):
            n += 1
    return n


def couper():
    try:
        import ilot
        ilot.couper_net()
    except Exception:  # noqa: BLE001
        os._exit(0)


# ---------------------------------------------------------------------------
# 1. Hook Stop : lancer le guetteur et rendre la main
# ---------------------------------------------------------------------------

def lanceur():
    try:
        brut = sys.stdin.buffer.read() if sys.stdin is not None else b''
        if commun.coupe():
            return  # extension coupée (fichier « coupe » du dossier de données)
        mode = mode_pastille()
        if mode == 'non':
            return
        if mode == 'oui':
            manque = commun.manque()
            if manque:
                noter(f'pastille pas affichée ({manque})')
                return
        entree = json.loads(brut.decode('utf-8', 'replace') or '{}')
        sid = str(entree.get('session_id') or '')
        tp = str(entree.get('transcript_path') or '')
        if not re.fullmatch(r'[0-9a-fA-F-]{36}', sid):
            noter('hook Stop sans identifiant de session valable')
            return
        if not tp or not os.path.isfile(tp):
            noter(f'{sid[:8]} : transcription introuvable ({tp})')
            return
        lancer_detache(['--guetter', sid, tp, repr(time.time())])
    except Exception:  # noqa: BLE001
        noter('lanceur : ' + traceback.format_exc())


# ---------------------------------------------------------------------------
# 2. Guetteur : la session attend-elle l'utilisateur ?
# ---------------------------------------------------------------------------

def guetter(cli, tp, t0):
    time.sleep(0.8)
    chemin, limite = None, time.time() + 4
    while True:
        chemin = trouver_fiche(cli)
        if chemin or time.time() > limite:
            break
        time.sleep(0.5)
    if not chemin:
        noter(f'{cli[:8]} : fiche de session introuvable')
        return
    fiche = lire_fiche(chemin) or {}
    observation = mode_pastille() == 'observation'
    local = str(fiche.get('sessionId') or '')
    titre = propre(fiche.get('title') or commun.t('Une session', 'A session'), 120)
    nom = f'« {titre[:50]} »'
    if fiche.get('scheduledTaskId'):
        if observation:
            noter(f'{nom} : tâche planifiée, ignorée')
        return
    if fiche.get('isArchived'):
        noter(f'{nom} : session archivée')
        return
    if not NOM_SUR.fullmatch(local):
        noter(f'{nom} : identifiant de session inattendu ({local!r})')
        return

    u0, ask = analyser_tour(fin_transcription(tp))
    if not u0:
        noter(f'{nom} : aucun message de Claude dans la transcription')
        return
    if deja_traite(local, u0):
        noter(f'{nom} : tour déjà traité ({u0[:8]}), hook repassé à la reprise ou au compactage')
        return
    marquer_traite(local, u0)
    # l'appli enregistre la fin du tour en même temps que le hook : on attend qu'elle l'ait écrite
    issue, fiche = attendre(chemin, lambda x: x.get('lastAssistantUuid') == u0, 10)
    if issue != 'ok':
        noter(f'{nom} : fiche pas à jour ({issue}), rien affiché')
        return
    t_fiche = time.time() - t0
    bord = fiche.get('lastTurnEdgeAt') or 0

    def nouveau_tour(x):
        return ((x.get('latestUserFrameAt') or 0) > t0 * 1000
                or bool(bord and (x.get('lastTurnEdgeAt') or 0) > bord))

    resume, t_resume, issue_resume = {}, None, None
    if observation or not ask:
        # le résumé de l'appli arrive quelques secondes après la fin du tour (jamais pour les sessions annexes)
        issue_resume, lue = attendre(chemin, lambda x: x.get('postTurnSummaryFor') == u0, 120,
                                     abandon=nouveau_tour)
        if lue:
            fiche = lue
        if issue_resume == 'ok':
            resume, t_resume = fiche.get('postTurnSummary') or {}, time.time() - t0
    besoin = propre(resume.get('needs_action') or '')
    if besoin and commun.langue() == 'fr' and en_anglais(besoin):
        noter(f'{nom} : résumé de l’appli en anglais remplacé par « {TEXTE_FRANCAIS} » : {besoin[:90]!r}')
        besoin = TEXTE_FRANCAIS
    if ask:
        texte, source = propre(ask), 'ask'
    elif besoin:
        texte, source = besoin, 'résumé'
    else:
        texte, source = '', ''

    if observation:
        vue_claude = claude_au_premier_plan() and session_au_premier_plan() == local
        wu = fiche.get('turnWrapUp') or {}
        dernier = fiche.get('latestUserFrameAt') or 0
        details = [
            f'fiche à {t_fiche:.1f} s', f'u0 {u0[:8]}', f'ask {ask[:70]!r}',
            f'résumé à {t_resume:.1f} s' if t_resume else f'résumé absent ({issue_resume})',
            f'catégorie {resume.get("status_category")}', f'needs_action {besoin[:70]!r}',
            f'needsUser {wu.get("needsUser")}',
            f'dernier message {(dernier - t0 * 1000) / 1000:+.0f} s' if dernier else 'dernier message absent',
            f'bord {(fiche.get("lastTurnEdgeAt") or 0) - bord:+} ms' if bord else 'bord absent',
            f'tours {fiche.get("completedTurns")}', f'vue dans Claude {vue_claude}',
        ]
        noter(f'{nom} : observation | ' + ' | '.join(details))
        noter(f'{nom} : ' + (f'aurait affiché ({source}) : {texte[:90]!r}' if texte else 'rien à afficher'))
        return

    if not texte:
        if issue_resume == 'abandon':
            noter(f'{nom} : nouveau tour avant le résumé')
        elif issue_resume == 'ok':
            noter(f'{nom} : rien à attendre ({resume.get("status_category")})')
        else:
            noter(f'{nom} : ni question ni résumé ({issue_resume})')
        return
    if claude_au_premier_plan() and session_au_premier_plan() == local:
        noter(f'{nom} : attente vue dans Claude, pas de pastille')
        return
    actuelle = lire_fiche(chemin) or fiche
    if nouveau_tour(actuelle) or actuelle.get('isArchived'):
        noter(f'{nom} : plus d’attente (nouveau tour ou session archivée)')
        return
    chemin_e = ecrire_entree({'local': local, 'titre': titre, 'texte': texte, 'depuis': t0, 'bord': bord,
                              'uuid': u0, 'fiche': chemin, 'cli': cli, 'source': source})
    noter(f'{nom} : attente affichée ({source}) : {texte[:90]!r}')
    # la fenêtre peut être en train de se fermer : on revérifie quelques secondes
    for pause in (0, 1.5, 2.5, 4.0):
        time.sleep(pause)
        if not os.path.exists(chemin_e):
            break
        if not fenetre_ouverte():
            lancer_detache(['--fenetre'])


# ---------------------------------------------------------------------------
# 3. Fenêtre : la pastille, sur le modèle de l'îlot
# ---------------------------------------------------------------------------

UNE_FOIS = threading.Lock()


def apres_fermeture(pret):
    """Des attentes sont arrivées pendant la fermeture : une nouvelle fenêtre les reprend."""
    if not UNE_FOIS.acquire(blocking=False):
        return
    lacher_verrou()
    try:
        if pret and lire_entrees() and not fenetre_ouverte():
            noter('attentes arrivées pendant la fermeture : fenêtre relancée')
            lancer_detache(['--fenetre'])
    except Exception:  # noqa: BLE001
        noter('relance de la fenêtre : ' + traceback.format_exc())


def attendre_ecran_libre():
    """Garde la pastille pour plus tard tant que l'écran est pris ; False si plus rien n'attend entre-temps."""
    raison = occupe()
    if not raison:
        return True
    noter(f'pastille retenue : {raison}')
    while True:
        time.sleep(2)
        if not purger(lire_entrees()):
            noter('pastille retenue, puis plus rien à montrer')
            return False
        if not occupe():
            noter('écran libre : pastille affichée')
            return True


def montrer():
    if not prendre_verrou():
        return  # une autre fenêtre montre déjà les attentes (ou les garde pour la fin du plein écran)
    pret = False
    try:
        os.makedirs(ENTREES, exist_ok=True)
        entrees = purger(lire_entrees())  # déjà répondues ou périmées pendant le lancement : rien à montrer
        if entrees and attendre_ecran_libre():
            entrees = purger(lire_entrees())
            if entrees:
                pret = interface(entrees)
    finally:
        apres_fermeture(pret)


def interface(initiales):
    """Fenêtre pywebview transparente, comme l'îlot. Renvoie True si la page s'est affichée."""
    if ICI not in sys.path:
        sys.path.insert(0, ICI)
    import ilot
    if ilot.LIB not in sys.path:
        sys.path.insert(0, ilot.LIB)
    import webview
    from webview.platforms import winforms as WF
    u32, gdi, dwm = ilot.u32, ilot.gdi, ilot.dwm

    rang = rang_qcm()
    etat = {'fini': False, 'pret': False, 'hwnd': None, 'form': None, 'seq': 0, 'rang': rang, 'ouvert_a': 0,
            'cachee': False, 'son_differe': False,
            'precedente': u32.GetForegroundWindow(), 'signature': signature(initiales),
            'connues': {(e.get('local'), e.get('depuis')) for e in initiales}}
    donnees = {'entrees': [vue(e) for e in initiales], 'rang': rang, 'test': TEST, 'langue': commun.langue()}
    with open(PAGE, encoding='utf-8') as f:
        page = f.read().replace('__DONNEES__', json.dumps(donnees, ensure_ascii=False).replace('</', '<\\/'))

    dpr = (u32.GetDpiForSystem() or 96) / 96
    travail = wintypes.RECT()
    if not u32.SystemParametersInfoW(0x30, 0, ctypes.byref(travail), 0):  # SPI_GETWORKAREA
        travail = wintypes.RECT(0, 0, u32.GetSystemMetrics(0), u32.GetSystemMetrics(1))
    largeur_css = ilot.LARGEUR_FENETRE
    hauteur_css = max(320, min(ilot.HAUTEUR_MAX, int((travail.bottom - travail.top) / dpr) - 40))
    lp, hp = round(largeur_css * dpr), round(hauteur_css * dpr)
    xp = travail.left + (travail.right - travail.left - lp) // 2
    yp = travail.top

    verrou = threading.Lock()  # fichiers d'attente
    verrou_zone = threading.Lock()
    verrou_fin = threading.Lock()
    cache, vus = {}, {}
    fenetre = None

    def js(code):
        try:
            return fenetre.evaluate_js(code)
        except Exception:  # noqa: BLE001
            return None

    def en_fond(fonction, *args):
        threading.Thread(target=fonction, args=args, daemon=True).start()

    def plus_tard(delai, fonction):
        minuterie = threading.Timer(delai, fonction)
        minuterie.daemon = True
        minuterie.start()

    def sur_ui(fonction):
        form = etat['form']
        if form is not None:
            form.Invoke(WF.Func[WF.Type](lambda: fonction()))

    def rendre():
        """Rend le clavier à la fenêtre où travaillait l'utilisateur, si la pastille l'a encore."""
        h = etat['hwnd']
        if not h or u32.GetForegroundWindow() != h:
            return False
        cible = etat['precedente']
        if cible and u32.IsWindow(cible) and u32.IsWindowVisible(cible):
            return bool(u32.SetForegroundWindow(cible))
        return False

    def fermer():
        with verrou_fin:
            if etat['fini']:
                return
            etat['fini'] = True
        if time.time() - etat['ouvert_a'] > 3:
            rendre()  # sauf juste après une ouverture : Claude est en train de passer devant
        lacher_verrou()  # une nouvelle attente peut déjà rouvrir une fenêtre

        def filet():  # fenêtre bloquée en se fermant
            apres_fermeture(etat['pret'])
            couper()
        plus_tard(3.0, filet)
        try:
            fenetre.destroy()
        except Exception:  # noqa: BLE001
            pass

    def retirer(local, depuis, raison):
        with verrou:
            if retirer_entree(local, depuis):
                noter(f'attente retirée ({raison}) : {local}')

    class Api:
        def zone(self, seq, x, y, w, h, r, dpr_page=1, devant=False):
            """Découpe la fenêtre à la forme de l'île (pixels CSS) : ailleurs, les clics passent au travers."""
            hwnd = etat['hwnd']
            if not hwnd:
                return False
            with verrou_zone:
                if seq <= etat['seq']:
                    return False
                etat['seq'] = seq
                d = float(dpr_page or 1)
                x1, y1 = math.floor(x * d), math.floor(y * d)
                x2, y2 = math.ceil((x + w) * d), math.ceil((y + h) * d)
                if r and r > 0:
                    diametre = max(2, round(2 * r * d))
                    rgn = gdi.CreateRoundRectRgn(x1, y1, x2 + 1, y2 + 1, diametre, diametre)
                else:
                    rgn = gdi.CreateRectRgn(x1, y1, x2, y2)
                if not u32.SetWindowRgn(hwnd, rgn, True):
                    gdi.DeleteObject(rgn)
                if devant:
                    u32.SetWindowPos(hwnd, ilot.HWND_TOPMOST, 0, 0, 0, 0,
                                     ilot.SWP_NOMOVE | ilot.SWP_NOSIZE | ilot.SWP_NOACTIVATE)
            return True

        def pret(self):
            if etat['pret']:
                return True
            etat['pret'] = True
            noter(f'pastille affichée : {len(initiales)} attente(s), rang {etat["rang"]}')
            if not ESSAI:
                ilot.signal_sonore()
            return True

        def focus(self):
            if TEST:
                return True  # l'essai automatique ne prend jamais le clavier

            def faire():
                form = etat['form']
                try:
                    form.Activate()
                    form.browser.webview.Focus()
                except Exception:  # noqa: BLE001
                    pass
            try:
                sur_ui(faire)
            except Exception:  # noqa: BLE001
                pass
            return True

        def rendre_focus(self):
            return rendre()

        def ouvrir(self, local, depuis=None):
            local = str(local or '')
            retirer(local, depuis, 'ouverte')
            if ESSAI or not local.startswith('local_') or not NOM_SUR.fullmatch(local):
                noter(f'ouverture demandée, rien ouvert (essai) : {local}')
                return True
            try:
                etat['ouvert_a'] = time.time()
                u32.AllowSetForegroundWindow(0xFFFFFFFF)  # ASFW_ANY : Claude a le droit de passer devant
                os.startfile(f'claude://claude.ai/epitaxy/{local}')
                return True
            except Exception:  # noqa: BLE001
                noter('ouverture de la session : ' + traceback.format_exc())
                return False

        def ecarter(self, local, depuis=None):
            retirer(str(local or ''), depuis, 'ignorée')
            return True

        def ecarter_tout(self, liste):
            for paire in liste or []:
                if isinstance(paire, (list, tuple)) and len(paire) == 2:
                    retirer(str(paire[0] or ''), paire[1], 'ignorée')
            return True

        def fin(self):
            fermer()
            return True

    def avant_affichage(window):
        form = window.native
        h = form.Handle.ToInt32()
        etat['form'], etat['hwnd'] = form, h
        from System.Drawing import Color
        form.BackColor = Color.Black
        form.browser.webview.DefaultBackgroundColor = Color.Transparent
        ex = u32.GetWindowLongW(h, ilot.GWL_EXSTYLE)
        u32.SetWindowLongW(h, ilot.GWL_EXSTYLE,
                           (ex | ilot.WS_EX_NOACTIVATE | ilot.WS_EX_TOOLWINDOW) & ~ilot.WS_EX_APPWINDOW)
        u32.SetWindowRgn(h, gdi.CreateRectRgn(lp // 2, 0, lp // 2 + 1, 1), False)
        u32.SetWindowPos(h, ilot.HWND_TOPMOST, xp, yp, lp, hp, ilot.SWP_NOACTIVATE | ilot.SWP_SHOWWINDOW)
        rgn = gdi.CreateRectRgn(0, 0, -1, -1)
        dwm.DwmEnableBlurBehindWindow(h, ctypes.byref(ilot.FLOU(0x3, True, rgn, False)))
        gdi.DeleteObject(rgn)
        for attribut, valeur in ((33, 1), (34, 0xFFFFFFFE), (38, 1)):
            v = ctypes.c_uint(valeur)
            dwm.DwmSetWindowAttribute(h, attribut, ctypes.byref(v), 4)
        form.Deactivate += lambda *_: en_fond(js, 'window.ilot && ilot.perteFocus()')

    def suivre_premier_plan():
        while not etat['fini']:
            fg = u32.GetForegroundWindow()
            if fg and fg != etat['hwnd'] and not ilot.titre_fenetre(fg).startswith(commun.TITRES_FENETRE):
                etat['precedente'] = fg
            time.sleep(0.25)

    def suivre_rang():
        while not etat['fini']:
            time.sleep(0.3)
            n = rang_qcm()
            if n != etat['rang'] and not etat['fini']:
                etat['rang'] = n
                js(f'window.ilot && ilot.changerRang({n})')

    def surveiller_page():
        limite = time.time() + 20
        while not etat['pret'] and not etat['fini'] and time.time() < limite:
            time.sleep(0.2)
        if not etat['pret'] and not etat['fini']:
            noter('page de la pastille jamais prête')
            fermer()

    def cacher(oui):
        """Plein écran ou écran verrouillé : la pastille s'efface, puis revient sans prendre le clavier."""
        h = etat['hwnd']
        if not h or oui == etat['cachee']:
            return
        etat['cachee'] = oui
        drapeaux = ilot.SWP_NOMOVE | ilot.SWP_NOSIZE | ilot.SWP_NOACTIVATE
        if oui:
            u32.SetWindowPos(h, ilot.HWND_TOPMOST, 0, 0, 0, 0, drapeaux | 0x0080)  # SWP_HIDEWINDOW
            noter('pastille cachée le temps du plein écran')
            return
        u32.SetWindowPos(h, ilot.HWND_TOPMOST, 0, 0, 0, 0, drapeaux | ilot.SWP_SHOWWINDOW)
        noter('pastille de retour')
        js('window.ilot && ilot.pulser()')
        if etat['son_differe']:
            etat['son_differe'] = False
            ilot.signal_sonore()

    def surveiller():
        while not etat['fini']:
            time.sleep(1.0)
            if etat['fini'] or not etat['pret']:
                continue
            try:
                cacher(bool(occupe()))
                focus = session_au_premier_plan() if claude_au_premier_plan() else None
                with verrou:
                    gardees = purger(lire_entrees(), focus, cache, vus)
                sig = signature(gardees)
                if sig == etat['signature']:
                    continue
                etat['signature'] = sig
                cles = {(e.get('local'), e.get('depuis')) for e in gardees}
                ajout = bool(cles - etat['connues'])
                etat['connues'] |= cles
                if not gardees:
                    if etat['cachee']:
                        fermer()  # personne ne verrait l'au revoir
                    else:
                        js('window.ilot && ilot.vider()')
                    continue
                js('window.ilot && ilot.maj(' + json.dumps([vue(e) for e in gardees]) + ')')
                if ajout and not ESSAI:
                    if etat['cachee']:
                        etat['son_differe'] = True  # le son attendra le retour de la pastille
                    else:
                        ilot.signal_sonore()
            except Exception:  # noqa: BLE001
                noter('surveillance : ' + traceback.format_exc())

    def montree(window):
        time.sleep(0.2)
        h = etat['hwnd']
        if h:
            # désormais un clic active la pastille et lui donne le clavier ; rien d'autre ne le fait
            u32.SetWindowLongW(h, ilot.GWL_EXSTYLE,
                               u32.GetWindowLongW(h, ilot.GWL_EXSTYLE) & ~ilot.WS_EX_NOACTIVATE)
        en_fond(suivre_premier_plan)
        en_fond(suivre_rang)
        en_fond(surveiller_page)
        en_fond(surveiller)

    ilot.corriger_pywebview(WF)
    fenetre = webview.create_window(
        ilot.TITRE_FENETRE + TITRE, html=page, js_api=Api(), width=largeur_css, height=hauteur_css,
        x=round(xp / dpr), y=round(yp / dpr), frameless=True, easy_drag=False, on_top=False,
        min_size=(0, 0), background_color='#000000', shadow=False)
    fenetre.events.before_show += avant_affichage
    fenetre.events.shown += montree
    try:
        webview.start(gui='edgechromium', private_mode=False, storage_path=PROFIL)
    finally:
        etat['fini'] = True
    return etat['pret']


# ---------------------------------------------------------------------------
# Démo et point d'entrée
# ---------------------------------------------------------------------------

DEMO_FR = [
    ('Compte rendu de réunion',
     'Je l’envoie à l’équipe en lien de partage ou en PDF ?', 4 * 60),
    ('Rangement des archives',
     'Il me manque le nom du dossier où ranger les exports en double.', 23 * 60),
]
DEMO_EN = [
    ('Meeting notes',
     'Should I send them to the team as a share link or as a PDF?', 4 * 60),
    ('Archive cleanup',
     'I need the name of the folder for the duplicate exports.', 23 * 60),
]


def lancer_demo():
    os.makedirs(ENTREES, exist_ok=True)
    for f in glob.glob(os.path.join(ENTREES, '*.json')):
        try:
            os.remove(f)
        except OSError:
            pass
    maintenant = time.time()
    for i, (titre, texte, age) in enumerate(commun.t(DEMO_FR, DEMO_EN), 1):
        ecrire_entree({'local': f'demo-{i}', 'titre': titre, 'texte': texte, 'depuis': maintenant - age,
                       'bord': 0, 'uuid': '', 'fiche': '', 'cli': '', 'source': 'démo'})
    montrer()


def relayer_question(cli, texte):
    """L'îlot a rendu à Claude une question restée sans réponse : la pastille prend le relais."""
    if not re.fullmatch(r'[0-9a-fA-F-]{36}', cli or ''):
        noter('relais de l’îlot sans identifiant de session valable')
        return
    chemin = trouver_fiche(cli)
    fiche = lire_fiche(chemin) if chemin else None
    if not fiche:
        noter(f'{cli[:8]} : fiche de session introuvable (relais de l’îlot)')
        return
    local = str(fiche.get('sessionId') or '')
    titre = propre(fiche.get('title') or commun.t('Une session', 'A session'), 120)
    nom = f'« {titre[:50]} »'
    if fiche.get('scheduledTaskId') or fiche.get('isArchived') or not NOM_SUR.fullmatch(local):
        noter(f'{nom} : question de l’îlot non relayée (tâche planifiée, session archivée ou identifiant inattendu)')
        return
    texte = propre(texte) or commun.t('Question en attente dans Claude', 'Question waiting in Claude')
    vue_claude = claude_au_premier_plan() and session_au_premier_plan() == local
    if mode_pastille() == 'observation':
        noter(f'{nom} : aurait affiché (îlot) : {texte[:90]!r} | vue dans Claude {vue_claude}')
        return
    if vue_claude:
        noter(f'{nom} : question vue dans Claude, pas de pastille')
        return
    chemin_e = ecrire_entree({'local': local, 'titre': titre, 'texte': texte, 'depuis': time.time(),
                              'bord': fiche.get('lastTurnEdgeAt') or 0,
                              'uuid': fiche.get('lastAssistantUuid') or '', 'fiche': chemin, 'cli': cli,
                              'source': 'îlot'})
    noter(f'{nom} : attente affichée (îlot) : {texte[:90]!r}')
    for pause in (0, 1.5, 2.5, 4.0):
        time.sleep(pause)
        if not os.path.exists(chemin_e):
            break
        if not fenetre_ouverte():
            lancer_detache(['--fenetre'])


def main():
    args = sys.argv[1:]
    demo = '--demo' in args
    if args[:1] in (['--question'], ['--guetter'], ['--fenetre']) and (commun.coupe() or mode_pastille() == 'non'):
        return  # extension coupée ou pastille désactivée entre-temps
    if args[:1] == ['--question']:
        try:
            relayer_question(args[1] if len(args) > 1 else '', args[2] if len(args) > 2 else '')
        except Exception:  # noqa: BLE001
            noter('relais de l’îlot : ' + traceback.format_exc())
        return
    if args[:1] == ['--guetter']:
        try:
            guetter(args[1], args[2], float(args[3]))
        except Exception:  # noqa: BLE001
            noter('guetteur : ' + traceback.format_exc())
        return
    if args[:1] == ['--fenetre'] or demo:
        manque = commun.manque()
        if manque:
            noter(f'pastille pas affichée ({manque})')
            if demo:
                print(commun.t(f'Démo impossible : {manque}. Voir le README de l’extension (installer.py).',
                               f'Demo not shown: {manque}. See the README (installer.py).'), file=sys.stderr)
            return
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
        try:
            lancer_demo() if demo else montrer()
        except Exception:  # noqa: BLE001
            noter('fenêtre : ' + traceback.format_exc())
        couper()  # sans attendre le nettoyage de .NET et WebView2
        return
    lanceur()


if __name__ == '__main__':
    main()
