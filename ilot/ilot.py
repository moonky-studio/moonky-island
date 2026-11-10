# -*- coding: utf-8 -*-
"""
Îlot de décisions pour Claude (Windows).

Hook PreToolUse sur l'outil AskUserQuestion : quand une session de Claude veut
poser une question à l'utilisateur, l'îlot l'affiche en haut de l'écran,
au-dessus de toutes les applications, sans prendre le clavier, et renvoie ses
réponses à la session. Mécanisme officiel depuis Claude Code 2.1.85 :
permissionDecision « allow » avec les réponses dans updatedInput.answers.

Même hook sur mcp__ccd_turn__wrap_up, le résumé de fin de tour de l'appli
Claude : une question posée là avec des boutons de réponse passe aussi par
l'îlot (voir fin_de_tour.py).

Sans réponse dans l'îlot (bouton « Répondre dans Claude », délai dépassé,
erreur, bibliothèque ou WebView2 absents, extension coupée), il ne renvoie
rien : Claude affiche alors sa propre fenêtre. Le délai est de 9 minutes (voir
DELAI_MAX) ; à son terme, la pastille « attend ta réponse »
(attente.py --question) prend le relais.

Interface : la page HTML qui porte le nom de ce fichier (ilot.py -> ilot.html),
dans une fenêtre pywebview (installée par installer.py dans le dossier de
données, voir commun.py). La fenêtre est fixe, transparente et ne capte les
clics que sur l'île : la page lui envoie la forme de l'île à chaque changement
(fonction zone) et Windows découpe la fenêtre à cette forme.

Code maison, sans réseau. Démo, sans rien envoyer : py -3.12-64 ilot.py --demo
(--deplie ou --open pour l'ouvrir directement sur les questions). Pour les essais :
ILOT_ESSAI=1 coupe le son, le micro et Whisper ; ILOT_TEST_AUTO=1 répond seul.
"""
import sys

if sys.platform != 'win32':  # l'îlot ne sait s'afficher que sous Windows : ailleurs, il laisse faire Claude
    if __name__ == '__main__':
        sys.exit(0)
    raise ImportError("l'îlot ne fonctionne que sous Windows")

import ctypes
import glob
import json
import math
import os
import queue
import subprocess
import threading
import time
import traceback
from ctypes import wintypes

import commun
import fin_de_tour

ICI = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.splitext(os.path.abspath(__file__))[0] + '.html'
# tout ce que l'îlot écrit vit hors du dossier de l'extension, remplacé à chaque mise à jour (voir commun.py)
JOURNAL = commun.chemin_journal('ilot')
PLACES = commun.PLACES
LIB = commun.LIB
# profil WebView2 gardé d'une fois sur l'autre : démarrage plus rapide, rien à effacer à la fermeture
PROFIL_WEBVIEW = os.path.join(commun.PROFILS, 'ilot')
DICTEES = commun.DICTEES
SONS = os.path.join(ICI, 'sons')
TRAVAILLEUR = os.path.join(ICI, 'dictee_whisper.py')
PYTHON_WHISPER = commun.whisper_python()
MODELE_WHISPER = commun.whisper_modele()
# micro proposé seulement si la dictée est activée dans reglages.json et que Whisper est installé
DICTEE_ACTIVE = commun.dictee_active()
CUDA_KO = os.path.join(commun.ETAT, 'whisper-processeur-seulement')
DUREE_CUDA_KO = 12 * 3600  # un plantage de la carte graphique au chargement l'écarte pour 12 h, pas pour toujours
JOURNAL_WHISPER = commun.chemin_journal('whisper')
TITRE_FENETRE, TITRES_FENETRE = commun.TITRE_FENETRE, commun.TITRES_FENETRE
ESSAI = bool(os.environ.get('ILOT_ESSAI'))

# taille de la fenêtre en pixels CSS : l'île (600 px au plus) et la marge de son ressort
LARGEUR_FENETRE = 680
HAUTEUR_MAX = 900

# L'appli Claude coupe une session restée muette (coworkMessageTimeoutMs, réglé à distance : 10 min par
# défaut, coupures observées entre 962 et 1 020 s le 05/11). Une question qui attend dans ce hook compte
# comme du silence ; posée par Claude dans sa propre fenêtre, elle protège la session. L'îlot rend donc la
# question à Claude au bout de 9 min, 13 au plus si l'utilisateur est en train d'y répondre.
DELAI_MAX = float(os.environ.get('ILOT_DELAI_MAX') or 9 * 60)
DEBUT = time.time()
LIMITE = DEBUT + DELAI_MAX
LIMITE_DURE = LIMITE + 4 * 60
DELAI_DEPASSE = threading.Event()
ATTENTE = os.path.join(ICI, 'attente.py')
PYTHONW = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')


def noter(message):
    try:
        with open(JOURNAL, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + ('[essai] ' if ESSAI else '') + message + '\n')
    except Exception:
        pass


DEPART = time.perf_counter()


def jalon(etape):
    """Repère de temps dans le journal, pendant les essais seulement."""
    if ESSAI:
        noter(f'{etape} à {time.perf_counter() - DEPART:.2f} s')


# ---------------------------------------------------------------------------
# Windows : fonctions natives (instances à part, pour ne pas toucher celles de pywebview)
# ---------------------------------------------------------------------------

u32 = ctypes.WinDLL('user32', use_last_error=True)
gdi = ctypes.WinDLL('gdi32')
dwm = ctypes.WinDLL('dwmapi')
HWND = ctypes.c_void_p
u32.GetForegroundWindow.restype = HWND
u32.GetForegroundWindow.argtypes = []
u32.SetForegroundWindow.argtypes = [HWND]
u32.IsWindow.argtypes = [HWND]
u32.IsWindowVisible.argtypes = [HWND]
u32.GetWindowTextW.argtypes = [HWND, ctypes.c_wchar_p, ctypes.c_int]
u32.GetWindowLongW.restype = ctypes.c_long
u32.GetWindowLongW.argtypes = [HWND, ctypes.c_int]
u32.SetWindowLongW.restype = ctypes.c_long
u32.SetWindowLongW.argtypes = [HWND, ctypes.c_int, ctypes.c_long]
u32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u32.SetWindowRgn.argtypes = [HWND, ctypes.c_void_p, wintypes.BOOL]
u32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
u32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
u32.GetDpiForSystem.restype = wintypes.UINT
u32.GetSystemMetrics.argtypes = [ctypes.c_int]
gdi.CreateRectRgn.restype = ctypes.c_void_p
gdi.CreateRectRgn.argtypes = [ctypes.c_int] * 4
gdi.CreateRoundRectRgn.restype = ctypes.c_void_p
gdi.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
gdi.DeleteObject.argtypes = [ctypes.c_void_p]
dwm.DwmSetWindowAttribute.argtypes = [HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]


class FLOU(ctypes.Structure):  # DWM_BLURBEHIND
    _fields_ = [('dwFlags', wintypes.DWORD), ('fEnable', wintypes.BOOL),
                ('hRgnBlur', ctypes.c_void_p), ('fTransitionOnMaximized', wintypes.BOOL)]


dwm.DwmEnableBlurBehindWindow.argtypes = [HWND, ctypes.POINTER(FLOU)]

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0001, 0x0002, 0x0010, 0x0040


def titre_fenetre(hwnd):
    tampon = ctypes.create_unicode_buffer(200)
    try:
        u32.GetWindowTextW(hwnd, tampon, 200)
    except Exception:
        return ''
    return tampon.value


# ---------------------------------------------------------------------------
# Session, places à l'écran, son
# ---------------------------------------------------------------------------

def fiche_session(cli_id):
    """Titre et identifiant (local_…) de la session dans l'app Claude."""
    if not cli_id:
        return commun.t('Une session', 'A session'), ''
    base = os.path.join(os.environ.get('APPDATA', ''), 'Claude', 'claude-code-sessions')
    fichiers = glob.glob(os.path.join(base, '*', '*', 'local_*.json'))
    fichiers.sort(key=os.path.getmtime, reverse=True)
    for chemin in fichiers[:400]:
        try:
            with open(chemin, encoding='utf-8') as f:
                fiche = json.load(f)
            if fiche.get('cliSessionId') == cli_id:
                return ((fiche.get('title') or commun.t('Une session', 'A session')).strip(),
                        fiche.get('sessionId') or '')
        except Exception:
            continue
    return commun.t('Une session', 'A session'), ''


def vivant(pid):
    try:
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    except Exception:
        return False


def prendre_place():
    """Rang de cet îlot parmi ceux déjà affichés, pour les empiler."""
    os.makedirs(PLACES, exist_ok=True)
    autres = 0
    for f in glob.glob(os.path.join(PLACES, '*.pid')):
        try:
            pid = int(os.path.basename(f)[:-4])
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        if vivant(pid):
            autres += 1
        else:
            try:
                os.remove(f)
            except OSError:
                pass
    with open(os.path.join(PLACES, f'{os.getpid()}.pid'), 'w') as f:
        f.write(repr(time.time()))
    return autres


def depart(chemin):
    try:
        with open(chemin) as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        try:
            return os.path.getmtime(chemin)
        except OSError:
            return 0.0


def rang_actuel():
    """Nombre d'îlots encore ouverts arrivés avant celui-ci : l'île remonte quand un autre se ferme."""
    mien = depart(os.path.join(PLACES, f'{os.getpid()}.pid'))
    n = 0
    for f in glob.glob(os.path.join(PLACES, '*.pid')):
        try:
            pid = int(os.path.basename(f)[:-4])
        except ValueError:
            continue
        if pid != os.getpid() and depart(f) < mien and vivant(pid):
            n += 1
    return n


def rendre_place():
    try:
        os.remove(os.path.join(PLACES, f'{os.getpid()}.pid'))
    except OSError:
        pass


# PlaySound : le son passe par le curseur « Sons système » du mélangeur, comme l'ancien son de Windows
SND_SYSTEM = 0x00200000


# noms anglais des sons, pour le README en anglais
ALIAS_SONS = {'none': 'aucun', 'off': 'aucun', 'glass': 'verre', 'drop': 'goutte'}


def son_choisi():
    """Son réglé dans reglages.json : marimba, verre (glass), goutte (drop), « windows » (son de Windows) ou
    « aucun » (none)."""
    nom = str(commun.reglages().get('son') or '').strip().lower()
    nom = os.path.splitext(os.path.basename(nom))[0] or 'windows'
    return ALIAS_SONS.get(nom, nom)


def signal_sonore():
    """Son d'arrivée d'une question : le son choisi dans reglages.json, sinon le son « Astérisque » de Windows."""
    nom = son_choisi()
    if nom == 'aucun':
        return
    try:
        import winsound
    except ImportError:
        return
    chemin = os.path.join(SONS, nom + '.wav')
    if nom != 'windows' and os.path.isfile(chemin):
        base = winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
        for drapeaux in (base | SND_SYSTEM, base):
            try:
                winsound.PlaySound(chemin, drapeaux)
                return
            except Exception as e:
                noter(f'son {os.path.basename(chemin)} refusé (drapeaux {drapeaux:#x}) : {e}')
    try:
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Dictée : micro enregistré par Windows (MCI), transcrit en local par Whisper
# ---------------------------------------------------------------------------

def mci(commande, tolerant=False):
    tampon = ctypes.create_unicode_buffer(512)
    erreur = ctypes.windll.winmm.mciSendStringW(commande, tampon, 511, None)
    if erreur and not tolerant:
        message = ctypes.create_unicode_buffer(512)
        ctypes.windll.winmm.mciGetErrorStringW(erreur, message, 511)
        raise RuntimeError(message.value or f'erreur MCI {erreur}')
    return tampon.value


def memoire_graphique_libre():
    """Mo libres sur la carte graphique d'après nvidia-smi ; None si on ne sait pas."""
    try:
        sortie = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=3, creationflags=0x08000000)  # CREATE_NO_WINDOW
        return int(sortie.stdout.split()[0])
    except Exception:  # noqa: BLE001
        return None


def duree_wav(chemin):
    """Durée de l'enregistrement en secondes."""
    try:
        import wave
        with wave.open(chemin, 'rb') as w:
            return w.getnframes() / float(w.getframerate() or 16000)
    except Exception:  # noqa: BLE001
        try:
            return max(0.0, (os.path.getsize(chemin) - 44) / 32000)  # 16 kHz mono 16 bits
        except OSError:
            return 0.0


def carte_a_eviter():
    """Vrai si la carte graphique a fait planter Whisper au chargement il y a moins de 12 h."""
    try:
        return time.time() - os.path.getmtime(CUDA_KO) < DUREE_CUDA_KO
    except OSError:
        return False


def sur(appareil):
    return 'sur la carte graphique' if appareil == 'carte graphique' else 'sur le processeur'


class Abandon(Exception):
    """Dictée arrêtée par l'utilisateur (Échap, Répondre dans Claude) ou par la fermeture de l'îlot."""


class Moteur:
    """Un processus Whisper (dictee_whisper.py), sur la carte graphique ou sur le processeur."""

    def __init__(self, processeur, prevenir):
        self.appareil = 'processeur' if processeur else 'carte graphique'
        self.pret = self.mort = self.tue = False
        self.depart = time.time()
        self._prevenir = prevenir
        self._lignes = queue.Queue()
        env = dict(os.environ)
        if processeur:
            env['ILOT_WHISPER_CPU'] = '1'
        else:
            env.pop('ILOT_WHISPER_CPU', None)
        env['ILOT_WHISPER_MODELE'] = MODELE_WHISPER
        env['ILOT_DICTEES'] = DICTEES
        env['ILOT_LANGUE'] = commun.langue()
        env['ILOT_WHISPER_LANGUE'] = commun.dictee_langue()
        with open(JOURNAL_WHISPER, 'a', encoding='utf-8') as erreurs:
            self._proc = subprocess.Popen(
                [PYTHON_WHISPER, '-I', TRAVAILLEUR], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=erreurs, text=True, encoding='utf-8', env=env,
                creationflags=0x08000000)  # CREATE_NO_WINDOW
        threading.Thread(target=self._lire, daemon=True).start()

    def _lire(self):
        try:
            for ligne in self._proc.stdout:
                ligne = ligne.strip()
                if not self.pret:
                    mots = ligne.split()
                    if mots and mots[0] == 'pret':  # « pret cuda » ou « pret cpu »
                        if mots[1:2] == ['cpu']:
                            self.appareil = 'processeur'
                        self._prevenir(self, 'pret')
                elif ligne.startswith('{'):
                    self._lignes.put(ligne)
        except Exception:  # noqa: BLE001
            pass
        self._lignes.put(None)
        self._prevenir(self, 'mort')

    def vivant(self):
        return not (self.mort or self.tue)

    def transcrire(self, chemin, delai):
        try:
            self._proc.stdin.write(chemin + '\n')
            self._proc.stdin.flush()
        except (OSError, ValueError):
            raise RuntimeError(commun.t('Whisper s’est arrêté (voir le journal whisper)',
                                        'Whisper stopped (see the whisper log)')) from None
        try:
            ligne = self._lignes.get(timeout=delai)
        except queue.Empty:
            raise TimeoutError(f'pas de réponse après {delai:.0f} s') from None
        if ligne is None:
            self._lignes.put(None)
            raise RuntimeError(commun.t('Whisper s’est arrêté (voir le journal whisper)',
                                        'Whisper stopped (see the whisper log)'))
        return json.loads(ligne)

    def tuer(self):
        self.tue = True
        try:
            self._proc.kill()
        except Exception:  # noqa: BLE001
            pass


class Dictee:
    """Un enregistrement à la fois, transcrit par un moteur Whisper chargé dès que l'îlot est au premier rang : carte
    graphique si elle a de la place, sinon processeur. Chaque attente est bornée et une carte graphique trop
    lente passe la main au processeur (05/11 : carte prise par un jeu, transcription bloquée sans fin)."""

    ATTENTE_CARTE = 12  # s : carte graphique toujours pas prête, le processeur se lance en parallèle
    ATTENTE_PRET = 30  # s : au-delà, la dictée renonce à attendre un moteur
    SEUIL_CARTE = 3000  # Mo libres sous lesquels Whisper ne se charge pas sur la carte graphique
    DELAI_CARTE = (6, 0.5)  # délai d'une transcription : base en s, plus tant de s par seconde d'audio
    DELAI_PROCESSEUR = (20, 1.5)

    def __init__(self):
        self._ordres = queue.Queue()
        threading.Thread(target=self._boucle_micro, daemon=True).start()
        self._cond = threading.Condition()
        self._lancement = threading.Lock()
        self._travail = threading.Lock()
        self._moteurs = []
        self._actif = None
        self._ferme = False
        self._abandons = set()
        self._en_cours = None
        self._occupe = None
        for vieux in glob.glob(os.path.join(DICTEES, '*.wav')):  # laissés par un îlot fermé brutalement
            try:
                if time.time() - os.path.getmtime(vieux) > 600:
                    os.remove(vieux)
            except OSError:
                pass

    def _boucle_micro(self):
        # toutes les commandes MCI depuis le même fil ; chaque ordre reçoit sa réponse dans sa propre file
        while True:
            ordre, chemin, retour = self._ordres.get()
            try:
                if ordre == 'niveau':
                    retour.put(('ok', mci('status dictee level')))
                    continue
                if ordre == 'debut':
                    mci('close dictee', tolerant=True)
                    mci('open new type waveaudio alias dictee')
                    mci('set dictee bitspersample 16 channels 1 samplespersec 16000 '
                        'bytespersec 32000 alignment 2', tolerant=True)
                    mci('record dictee')
                elif ordre == 'fin':
                    mci('stop dictee')
                    mci(f'save dictee "{chemin}"')
                    mci('close dictee')
                else:
                    mci('stop dictee', tolerant=True)
                    mci('close dictee', tolerant=True)
                retour.put(('ok', ''))
            except Exception as e:  # noqa: BLE001
                if ordre != 'niveau':
                    mci('close dictee', tolerant=True)
                retour.put(('erreur', str(e)))

    def _micro(self, ordre, chemin='', delai=20):
        retour = queue.Queue(maxsize=1)
        self._ordres.put((ordre, chemin, retour))
        try:
            return retour.get(timeout=delai)
        except queue.Empty:
            raise RuntimeError(commun.t('le micro ne répond pas', 'the microphone does not respond')) from None

    def niveau(self):
        """Volume du micro pendant l'écoute (pour l'onde), -1 si Windows ne le donne pas."""
        try:
            statut, valeur = self._micro('niveau', delai=0.5)
            valeur = valeur.strip()
            return int(valeur) if statut == 'ok' and valeur.isdigit() else -1
        except Exception:  # noqa: BLE001
            return -1

    def _interrompu(self, jeton):
        return self._ferme or (jeton is not None and jeton in self._abandons)

    def _cpu_en_route(self):
        return any(x.appareil == 'processeur' and x.vivant() for x in self._moteurs)

    def _lancer(self, processeur):
        """Démarre un moteur (à appeler sous self._cond)."""
        if self._ferme:
            return None
        m = Moteur(processeur, self._evenement)
        self._moteurs.append(m)
        if not processeur:
            threading.Thread(target=self._veiller_carte, args=(m,), daemon=True).start()
        return m

    def _evenement(self, m, etat):
        """Un moteur vient d'être prêt, ou de s'arrêter."""
        with self._cond:
            if etat == 'pret':
                m.pret = True
                actif = self._actif
                if self._ferme or m.tue or (actif is not None and actif is not m and actif.vivant()):
                    m.tuer()
                else:
                    self._actif = m
                    noter(f'Whisper prêt {sur(m.appareil)} en {time.time() - m.depart:.1f} s')
                    for x in self._moteurs:
                        if x is not m and x.vivant():
                            x.tuer()  # l'autre moteur, encore en chargement, ne sert plus
            else:
                m.mort = True
                if self._actif is m:
                    self._actif = None
                if not m.pret and not m.tue and not self._ferme:
                    if m.appareil == 'carte graphique':
                        # arrêt brutal pendant le chargement (pilote de la carte graphique, par exemple)
                        try:
                            with open(CUDA_KO, 'w', encoding='utf-8') as f:
                                f.write(time.strftime('%Y-%m-%d %H:%M:%S'))
                        except OSError:
                            pass
                        noter('Whisper arrêté au chargement sur la carte graphique : processeur pour 12 h')
                        if not self._cpu_en_route():
                            try:
                                self._lancer(True)
                            except Exception:  # noqa: BLE001
                                noter('Whisper, relance sur le processeur : ' + traceback.format_exc())
                    else:
                        noter('Whisper arrêté au chargement sur le processeur (voir le journal whisper)')
            self._moteurs = [x for x in self._moteurs if not x.mort]
            self._cond.notify_all()

    def _veiller_carte(self, m):
        """Carte graphique pas prête à temps : le processeur se lance aussi, le premier prêt sert."""
        with self._cond:
            limite = m.depart + self.ATTENTE_CARTE
            while not (m.pret or m.mort or m.tue or self._ferme):
                reste = limite - time.time()
                if reste <= 0:
                    break
                self._cond.wait(max(0.05, reste))
            if m.pret or m.mort or m.tue or self._ferme or self._cpu_en_route():
                return
            noter(f'carte graphique pas prête après {self.ATTENTE_CARTE} s : le processeur prend le relais')
            try:
                self._lancer(True)
            except Exception:  # noqa: BLE001
                noter('Whisper, relance sur le processeur : ' + traceback.format_exc())

    def _assurer_moteur(self):
        """Un moteur vivant, prêt ou en chargement ; lancé au besoin."""
        with self._lancement:
            with self._cond:
                if self._ferme or any(x.vivant() for x in self._moteurs):
                    return
            if not os.path.exists(PYTHON_WHISPER):
                raise RuntimeError(commun.t('Whisper local introuvable', 'local Whisper not found'))
            processeur = carte_a_eviter() or bool(os.environ.get('ILOT_WHISPER_CPU'))
            if not processeur:
                libre = memoire_graphique_libre()
                if libre is not None and libre < self.SEUIL_CARTE:
                    noter(f'carte graphique occupée ({libre} Mo libres) : Whisper sur le processeur')
                    processeur = True
            with self._cond:
                if not self._ferme and not any(x.vivant() for x in self._moteurs):
                    self._lancer(processeur)

    def _assurer_en_fond(self):
        try:
            self._assurer_moteur()
        except Exception:  # noqa: BLE001
            noter('préchauffage, échec : ' + traceback.format_exc())

    def prechauffer(self):
        """Charge le modèle dès l'ouverture de l'îlot, pour que la dictée démarre sans attendre."""
        threading.Thread(target=self._assurer_en_fond, daemon=True).start()

    def _attendre_moteur(self, limite, jeton):
        self._assurer_moteur()
        with self._cond:
            while True:
                if self._interrompu(jeton):
                    raise Abandon()
                m = self._actif
                if m is not None and m.vivant():
                    return m
                if not any(x.vivant() for x in self._moteurs):
                    raise RuntimeError(commun.t('Whisper s’est arrêté (voir le journal whisper)',
                                                'Whisper stopped (see the whisper log)'))
                reste = limite - time.time()
                if reste <= 0:
                    raise RuntimeError(commun.t('Whisper ne démarre pas : tape ta réponse ou réessaie',
                                                'Whisper does not start: type your answer or try again'))
                self._cond.wait(min(0.5, reste))

    def _transcrire(self, chemin, secondes, jeton):
        with self._travail:
            with self._cond:
                self._en_cours = jeton
            try:
                limite = time.time() + self.ATTENTE_PRET
                while True:
                    m = self._attendre_moteur(limite, jeton)
                    base, facteur = self.DELAI_PROCESSEUR if m.appareil == 'processeur' else self.DELAI_CARTE
                    with self._cond:
                        if self._interrompu(jeton):
                            raise Abandon()
                        self._occupe = m
                    try:
                        retour = m.transcrire(chemin, base + facteur * secondes)
                    except (TimeoutError, RuntimeError) as e:
                        if self._interrompu(jeton):
                            raise Abandon() from None
                        m.tuer()
                        if m.appareil == 'processeur':
                            noter(f'transcription sur le processeur en échec : {e}')
                            if isinstance(e, TimeoutError):
                                raise RuntimeError(commun.t(
                                    'La transcription prend trop de temps : tape ta réponse ou réessaie',
                                    'Transcription is taking too long: type your answer or try again')) from None
                            raise
                        noter(f'carte graphique trop lente ou arrêtée ({e}) : nouvel essai sur le processeur')
                        with self._cond:
                            if not self._ferme and not self._cpu_en_route():
                                self._lancer(True)
                        limite = time.time() + self.ATTENTE_PRET
                        continue
                    finally:
                        with self._cond:
                            self._occupe = None
                    if 'erreur' in retour:
                        raise RuntimeError(retour['erreur'])
                    return retour.get('texte', ''), m.appareil
            finally:
                with self._cond:
                    self._en_cours = None

    # --- dictée ---------------------------------------------------------------

    def debut(self):
        if not os.path.exists(PYTHON_WHISPER):
            raise RuntimeError(commun.t('Whisper local introuvable', 'local Whisper not found'))
        self.prechauffer()
        statut, detail = self._micro('debut')
        if statut != 'ok':
            raise RuntimeError(commun.t(f'micro indisponible ({detail})', f'microphone unavailable ({detail})'))

    def fin(self, jeton=None):
        if jeton is None:
            jeton = object()
        if self._interrompu(jeton):  # arrêtée avant même la fin de l'enregistrement
            try:
                self._micro('annuler', delai=5)
            except Exception:  # noqa: BLE001
                pass
            raise Abandon()
        os.makedirs(DICTEES, exist_ok=True)
        chemin = os.path.join(DICTEES, f'{int(time.time() * 1000)}.wav')
        statut, detail = self._micro('fin', chemin)
        if statut != 'ok':
            raise RuntimeError(commun.t(f'enregistrement impossible ({detail})', f'recording failed ({detail})'))
        debut = time.time()
        try:
            secondes = duree_wav(chemin)
            texte, appareil = self._transcrire(chemin, secondes, jeton)
        finally:
            try:
                os.remove(chemin)  # l'enregistrement n'est pas gardé
            except OSError:
                pass
        noter(f'dictée de {secondes:.0f} s transcrite {sur(appareil)} en {time.time() - debut:.1f} s '
              f'({len(texte)} caractères)')
        return texte

    def abandonner(self, jeton=None):
        """Échap ou « Répondre dans Claude » pendant la transcription : on la lâche, moteur occupé compris."""
        victime = None
        with self._cond:
            if jeton is None:
                jeton = self._en_cours
            if jeton is None:
                return
            self._abandons.add(jeton)
            if self._en_cours == jeton and self._occupe is not None:
                victime = self._occupe
            self._cond.notify_all()
        if victime is not None:
            victime.tuer()
            noter('transcription arrêtée en cours de route')

    def annuler(self):
        self._micro('annuler')

    def fermer(self):
        with self._cond:
            self._ferme = True
            moteurs = list(self._moteurs)
            self._cond.notify_all()
        for m in moteurs:
            m.tuer()
        try:
            self._micro('annuler', delai=2)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Interface principale : HTML dans une fenêtre pywebview transparente
# ---------------------------------------------------------------------------

def corriger_pywebview(WF):
    """La fenêtre s'affiche sans jamais prendre le premier plan ni le clavier (prototype du 04/11)."""
    Form = WF.BrowserView.BrowserForm
    echelle = Form._scale

    def echelle_sans_activation(self):
        # premier appel juste après la création du handle, avant Size, Location et Show :
        # on interdit l'activation dès ce moment-là
        if not getattr(self, '_ilot_inactivable', False):
            self._ilot_inactivable = True
            h = self.Handle.ToInt32()
            u32.SetWindowLongW(h, GWL_EXSTYLE,
                               u32.GetWindowLongW(h, GWL_EXSTYLE) | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        return echelle.fget(self)

    def montree_sans_focus(self, *_):
        self.shown.set()  # sans webview.Focus() : le clavier reste où il est

    def theme_sans_mica(self):
        pass  # pywebview pose un fond Mica en thème sombre : il se verrait derrière la fenêtre transparente

    Form._scale = property(echelle_sans_activation)
    Form.on_shown = montree_sans_focus
    Form.update_title_bar_theme = theme_sans_mica


def duree(secondes):
    return f'{secondes:.0f} s' if secondes < 90 else f'{secondes / 60:.0f} min'


def prechauffer_si_premier(etat, dictee):
    """Whisper se charge pour l'îlot du premier rang seulement : sinon chaque îlot empilé chargerait son propre
    modèle. Un îlot empilé le charge en remontant au premier rang, ou au clic sur le micro, environ 3 s sur la
    carte graphique. Rien sans dictée activée."""
    if etat['pret'] and etat['rang'] == 0 and DICTEE_ACTIVE and not ESSAI:
        dictee.prechauffer()
        return True
    return False


def interface_web(questions, titre, local, rang, demo=False, deplie=False, secours=None):
    """Îlot en HTML dans une fenêtre pywebview. Renvoie (réponses, vers_claude, lien_ouvert)."""
    if LIB not in sys.path:
        sys.path.insert(0, LIB)
    import webview
    from webview.platforms import winforms as WF

    donnees = {'titre': titre, 'questions': questions, 'lien': bool(local), 'demo': demo, 'deplie': deplie,
               'rang': rang, 'dictee': DICTEE_ACTIVE, 'langue': commun.langue()}
    with open(PAGE, encoding='utf-8') as f:
        page = f.read().replace('__DONNEES__', json.dumps(donnees, ensure_ascii=False).replace('</', '<\\/'))

    # fenêtre fixe en haut au centre de l'écran principal, en pixels physiques
    dpr = (u32.GetDpiForSystem() or 96) / 96
    travail = wintypes.RECT()
    if not u32.SystemParametersInfoW(0x30, 0, ctypes.byref(travail), 0):  # SPI_GETWORKAREA
        travail = wintypes.RECT(0, 0, u32.GetSystemMetrics(0), u32.GetSystemMetrics(1))
    largeur_css = LARGEUR_FENETRE
    hauteur_css = max(320, min(HAUTEUR_MAX, int((travail.bottom - travail.top) / dpr) - 40))
    lp, hp = round(largeur_css * dpr), round(hauteur_css * dpr)
    xp = travail.left + (travail.right - travail.left - lp) // 2
    yp = travail.top

    etat = {'reponses': None, 'vers_claude': False, 'lien_ouvert': False, 'fini': False, 'pret': False,
            'hwnd': None, 'form': None, 'seq': 0, 'precedente': u32.GetForegroundWindow(), 'rang': rang}
    verrou_zone = threading.Lock()
    verrou_fin = threading.Lock()
    dictee = Dictee()
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
        minuterie.daemon = True  # ne retarde jamais la sortie du hook, donc la réponse à Claude
        minuterie.start()

    def sur_ui(fonction):
        form = etat['form']
        if form is not None:
            form.Invoke(WF.Func[WF.Type](lambda: fonction()))

    def rendre():
        """Rend le clavier à la fenêtre où travaillait l'utilisateur, si l'îlot l'a encore."""
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
        jalon('fermeture demandée')
        rendre()
        try:
            fenetre.destroy()
        except Exception:  # noqa: BLE001
            pass
        jalon('fenêtre détruite')

    def ouvrir_lien():
        if not local:
            return False
        u32.AllowSetForegroundWindow(0xFFFFFFFF)  # ASFW_ANY : Claude a le droit de passer devant
        os.startfile(f'claude://claude.ai/epitaxy/{local}')
        return True

    class Api:
        def zone(self, seq, x, y, w, h, r, dpr_page=1, devant=False):
            """Découpe la fenêtre à la forme de l'île (pixels CSS) : ailleurs, les clics passent au travers."""
            hwnd = etat['hwnd']
            if not hwnd:
                return False
            with verrou_zone:
                if seq <= etat['seq']:
                    return False  # un appel plus récent est déjà passé
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
                    u32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            return True

        def pret(self):
            if etat['pret']:
                return True
            etat['pret'] = True
            jalon('île dessinée')
            noter(f'îlot affiché : {titre} (rang {rang})')
            if not ESSAI:
                signal_sonore()
            prechauffer_si_premier(etat, dictee)
            return True

        def focus(self):
            if os.environ.get('ILOT_TEST_AUTO'):
                return True  # l'essai automatique ne prend jamais le clavier : on peut travailler pendant ce temps
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

        def envoyer(self, reponses):
            if etat['fini'] or not isinstance(reponses, dict):
                return False
            etat['reponses'] = reponses
            jalon('réponses reçues')
            rendre()  # le clavier revient tout de suite ; l'île finit son animation par-dessus
            plus_tard(3.0, fermer)
            if secours:  # fenêtre bloquée en se fermant : la réponse part quand même
                plus_tard(7.0, lambda: secours(reponses, False, False))
            return True

        def dans_claude(self):
            if etat['fini']:
                return False
            etat['vers_claude'] = True
            try:
                etat['lien_ouvert'] = ouvrir_lien()
            except Exception:  # noqa: BLE001
                noter('ouverture de la session : ' + traceback.format_exc())
            plus_tard(3.0, fermer)
            if secours:
                plus_tard(7.0, lambda: secours(None, True, etat['lien_ouvert']))
            return True

        def ouvrir(self):
            try:
                return ouvrir_lien()
            except Exception:  # noqa: BLE001
                noter('ouverture de la session : ' + traceback.format_exc())
                return False

        def fin(self):
            jalon('animation de fin terminée')
            fermer()
            return True

        def niveau(self):
            return dictee.niveau()

        def dictee_debut(self, jeton=None):
            if ESSAI:
                return commun.t('micro coupé pendant les essais', 'microphone off during tests')
            if not DICTEE_ACTIVE:
                return commun.t('dictée désactivée (voir le README de l’extension)',
                                'dictation is off (see the README)')
            try:
                dictee.debut()
                return 'ok'
            except Exception as e:  # noqa: BLE001
                noter('dictée, début : ' + traceback.format_exc())
                return str(e)

        def dictee_fin(self, jeton=None):
            try:
                return {'texte': dictee.fin(jeton)}
            except Abandon:
                return {'abandon': True}
            except Exception as e:  # noqa: BLE001
                noter('dictée, fin : ' + traceback.format_exc())
                return {'erreur': str(e)}

        def dictee_abandonner(self, jeton=None):
            try:
                dictee.abandonner(jeton)
            except Exception:  # noqa: BLE001
                noter('dictée, abandon : ' + traceback.format_exc())
            return True

        def dictee_annuler(self):
            try:
                dictee.annuler()
            except Exception:  # noqa: BLE001
                pass
            return True

    def avant_affichage(window):
        form = window.native
        h = form.Handle.ToInt32()
        etat['form'], etat['hwnd'] = form, h
        from System.Drawing import Color
        form.BackColor = Color.Black
        form.browser.webview.DefaultBackgroundColor = Color.Transparent
        ex = u32.GetWindowLongW(h, GWL_EXSTYLE)
        u32.SetWindowLongW(h, GWL_EXSTYLE, (ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        # rien de visible ni de cliquable tant que la page n'a pas dessiné l'île
        u32.SetWindowRgn(h, gdi.CreateRectRgn(lp // 2, 0, lp // 2 + 1, 1), False)
        u32.SetWindowPos(h, HWND_TOPMOST, xp, yp, lp, hp, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        # transparence par pixel : flou DWM sur une région vide, ni coins, ni bord, ni fond Mica
        rgn = gdi.CreateRectRgn(0, 0, -1, -1)
        dwm.DwmEnableBlurBehindWindow(h, ctypes.byref(FLOU(0x3, True, rgn, False)))
        gdi.DeleteObject(rgn)
        for attribut, valeur in ((33, 1), (34, 0xFFFFFFFE), (38, 1)):
            v = ctypes.c_uint(valeur)
            dwm.DwmSetWindowAttribute(h, attribut, ctypes.byref(v), 4)
        # un clic ailleurs : l'île se replie (la page le voit aussi, par sécurité les deux)
        form.Deactivate += lambda *_: en_fond(js, 'window.ilot && ilot.perteFocus()')

    def suivre_premier_plan():
        while not etat['fini']:
            fg = u32.GetForegroundWindow()
            if fg and fg != etat['hwnd'] and not titre_fenetre(fg).startswith(TITRES_FENETRE):
                etat['precedente'] = fg
            time.sleep(0.25)

    def suivre_rang():
        while not etat['fini']:
            time.sleep(0.5)
            n = rang_actuel()
            if n != etat['rang'] and not etat['fini']:
                etat['rang'] = n
                js(f'window.ilot && ilot.changerRang({n})')
                if prechauffer_si_premier(etat, dictee):
                    noter(f'îlot remonté au premier rang : Whisper se charge ({titre})')

    def surveiller_page():
        # page jamais affichée (WebView2 en panne…) : on se retire, Claude pose la question lui-même
        limite = time.time() + 20
        while not etat['pret'] and not etat['fini'] and time.time() < limite:
            time.sleep(0.2)
        if not etat['pret'] and not etat['fini']:
            noter('page de l’îlot jamais prête : question laissée à Claude')
            fermer()

    def surveiller_delai():
        # passé ce délai, l'appli Claude couperait la session (voir DELAI_MAX) : la question repart vers Claude,
        # sauf si l'utilisateur a l'îlot en main à ce moment-là (premier plan), jusqu'à la limite dure
        while not etat['fini'] and (time.time() < LIMITE or (
                u32.GetForegroundWindow() == etat['hwnd'] and time.time() < LIMITE_DURE)):
            time.sleep(1)
        if etat['fini'] or etat['reponses'] is not None or etat['vers_claude']:
            return
        DELAI_DEPASSE.set()
        noter(f'sans réponse après {duree(time.time() - DEBUT)} : question rendue à Claude ({titre})')
        fermer()

    def test_auto():
        for _ in range(100):
            if js('typeof window.ilot === "object"'):
                break
            time.sleep(0.1)
        jalon('essai automatique : page jointe')
        time.sleep(0.8)
        js('ilot.testAuto(); true')
        jalon('essai automatique lancé')

    def montree(window):
        time.sleep(0.2)
        h = etat['hwnd']
        if h:
            # désormais un clic active l'îlot et lui donne le clavier ; rien d'autre ne le fait
            u32.SetWindowLongW(h, GWL_EXSTYLE, u32.GetWindowLongW(h, GWL_EXSTYLE) & ~WS_EX_NOACTIVATE)
        en_fond(suivre_premier_plan)
        en_fond(suivre_rang)
        en_fond(surveiller_page)
        en_fond(surveiller_delai)
        if os.environ.get('ILOT_TEST_AUTO'):
            en_fond(test_auto)

    corriger_pywebview(WF)
    fenetre = webview.create_window(
        TITRE_FENETRE + titre, html=page, js_api=Api(), width=largeur_css, height=hauteur_css,
        x=round(xp / dpr), y=round(yp / dpr), frameless=True, easy_drag=False, on_top=False,
        min_size=(0, 0), background_color='#000000', shadow=False)
    fenetre.events.before_show += avant_affichage
    fenetre.events.shown += montree
    try:
        webview.start(gui='edgechromium', private_mode=False, storage_path=PROFIL_WEBVIEW)
    finally:
        jalon('boucle de la fenêtre terminée')
        etat['fini'] = True
        dictee.fermer()
        jalon('micro et Whisper fermés')
    return etat['reponses'], etat['vers_claude'], etat['lien_ouvert']


# ---------------------------------------------------------------------------
# Démo : py -3.12-64 ilot.py --demo (--deplie ou --open pour l'ouvrir sur les questions), rien n'est envoyé
# ---------------------------------------------------------------------------

DEMO_FR = [
    {
        'header': 'Compte rendu',
        'question': 'Le compte rendu de la réunion est prêt. Je l’envoie à l’équipe en lien de partage ou en PDF ?',
        'multiSelect': False,
        'options': [
            {'label': 'Lien de partage (recommandé)', 'description': 'Toujours à jour, chacun peut commenter.'},
            {'label': 'PDF en pièce jointe', 'description': 'Figé, lisible hors ligne.'},
        ],
    },
    {
        'header': 'Archives',
        'question': 'Quels dossiers je range dans les archives ?',
        'multiSelect': True,
        'options': [
            {'label': 'Brouillons de septembre', 'description': 'Aucun ouvert depuis un mois.'},
            {'label': 'Exports en double', 'description': '4 fichiers, 3,2 Go.'},
            {'label': 'Captures d’écran', 'description': '58 images sur le bureau.'},
        ],
    },
]

DEMO_EN = [
    {
        'header': 'Meeting notes',
        'question': 'The meeting notes are ready. Should I send them to the team as a share link or as a PDF?',
        'multiSelect': False,
        'options': [
            {'label': 'Share link (recommended)', 'description': 'Always up to date, everyone can comment.'},
            {'label': 'PDF attachment', 'description': 'Fixed, readable offline.'},
        ],
    },
    {
        'header': 'Archive',
        'question': 'Which folders should I move to the archive?',
        'multiSelect': True,
        'options': [
            {'label': 'September drafts', 'description': 'None opened in a month.'},
            {'label': 'Duplicate exports', 'description': '4 files, 3.2 GB.'},
            {'label': 'Screenshots', 'description': '58 images on the desktop.'},
        ],
    },
]


def main():
    demo = '--demo' in sys.argv
    deplie = '--deplie' in sys.argv or '--open' in sys.argv
    sortie_json = sys.stdout
    if sys.stderr is not None:
        sys.stdout = sys.stderr  # rien d'autre que la réponse ne doit sortir sur stdout
    try:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        if demo:
            entree = {'session_id': '', 'tool_input': {'questions': commun.t(DEMO_FR, DEMO_EN)}}
        else:
            entree = json.loads(sys.stdin.buffer.read().decode('utf-8', 'replace') or '{}')
        outil = entree.get('tool_input') or {}
        # question du résumé de fin de tour de l'appli Claude (wrap_up), relayée ici : voir fin_de_tour.py
        fin_tour = not demo and str(entree.get('tool_name') or '') == fin_de_tour.OUTIL
        if fin_tour:
            if commun.coupe() or not fin_de_tour.active():
                return
            questions = fin_de_tour.questions(entree) or []
            if not questions:
                return
        else:
            questions = outil.get('questions') or []
            if not questions or outil.get('answers'):
                return
        if commun.coupe():
            if demo:
                print(commun.t('Démo impossible : l’extension est coupée (installer.py --reprendre la rallume).',
                               'Demo not shown: the plugin is off (installer.py --on turns it back on).'))
            return  # extension coupée (fichier « coupe » du dossier de données) : Claude pose la question
        manque = commun.manque()
        if manque:
            noter(f'îlot pas affiché ({manque}) : question laissée à Claude')
            if demo:
                print(commun.t(f'Démo impossible : {manque}. Voir le README de l’extension (installer.py).',
                               f'Demo not shown: {manque}. See the README (installer.py).'))
            return
        if demo:
            titre, local = commun.t('Démo de l’îlot, rien n’est envoyé', 'Moonky Island demo, nothing is sent'), ''
        else:
            titre, local = fiche_session(entree.get('session_id', ''))
        rang = prendre_place()
        une_fois = threading.Lock()
        relais = threading.Lock()

        def livrer(reponses, vers_claude, lien_ouvert):
            """Donne la réponse à Claude, une seule fois, que ce soit la fin normale ou le filet de sécurité."""
            if not une_fois.acquire(blocking=False):
                return False
            if reponses and fin_tour:
                sortie = fin_de_tour.sortie(entree, reponses)
                if sortie:
                    sortie_json.write(json.dumps(sortie))
                    sortie_json.flush()
                    jalon('réponse écrite pour Claude')
                    noter(f'réponse de fin de tour envoyée ({titre})')
            elif reponses:
                sortie = {
                    'hookSpecificOutput': {
                        'hookEventName': 'PreToolUse',
                        'permissionDecision': 'allow',
                        'permissionDecisionReason': commun.t("Réponses données dans l'îlot",
                                                             'Answers given in Moonky Island'),
                        'updatedInput': dict(outil, answers=reponses),
                    }
                }
                sortie_json.write(json.dumps(sortie))
                sortie_json.flush()
                jalon('réponse écrite pour Claude')
                noter(f'réponses envoyées ({titre}) : {len(reponses)}')
            elif vers_claude:
                noter(f'réponse dans Claude ({titre})')
                if local and not lien_ouvert:
                    os.startfile(f'claude://claude.ai/epitaxy/{local}')
            return True

        def secours(reponses, vers_claude, lien_ouvert):
            # 7 s après la réponse, la fenêtre ne s'est toujours pas fermée : on livre et on coupe
            noter('fenêtre lente à se fermer : réponse livrée par le filet de sécurité')
            if livrer(reponses, vers_claude, lien_ouvert):
                rendre_place()
                couper_net()

        def rendre_a_claude():
            """Voir DELAI_MAX : Claude pose la question lui-même et la pastille « attend ta réponse » le
            signale, puisque l'îlot n'est plus là. Une question de fin de tour n'en a pas besoin : le tour se
            termine, et le hook de fin de tour lance la pastille."""
            if demo or fin_tour or not relais.acquire(blocking=False):
                return
            try:
                premiere = questions[0] if isinstance(questions[0], dict) else {}
                texte = ' '.join(str(premiere.get('question') or '').split())[:300]
                autres = len(questions) - 1
                if autres:
                    s = 's' if autres > 1 else ''
                    texte += commun.t(f' (et {autres} autre{s} question{s})', f' (and {autres} more question{s})')
                exe = PYTHONW if os.path.isfile(PYTHONW) else sys.executable
                subprocess.Popen([exe, ATTENTE, '--question', str(entree.get('session_id') or ''), texte],
                                 cwd=ICI, close_fds=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=0x00000008 | 0x00000200 | 0x08000000)  # détaché, sans console
            except Exception:  # noqa: BLE001
                noter('relais vers la pastille : ' + traceback.format_exc())

        def filet_delai():
            # l'îlot est encore là bien après la limite (fenêtre bloquée ?) : on rend la question et on coupe
            noter(f'îlot encore ouvert après {duree(time.time() - DEBUT)} : '
                  f'question rendue à Claude par le filet ({titre})')
            if livrer(None, False, False):
                rendre_a_claude()
                rendre_place()
                couper_net()

        filet = threading.Timer(max(1.0, LIMITE_DURE + 15 - time.time()), filet_delai)
        filet.daemon = True
        filet.start()

        lien_ouvert = False
        try:
            try:
                reponses, vers_claude, lien_ouvert = interface_web(questions, titre, local, rang, demo, deplie,
                                                                   secours)
            except Exception:
                noter('interface web indisponible : question laissée à Claude : ' + traceback.format_exc())
                reponses, vers_claude = None, False
        finally:
            rendre_place()
        livrer(reponses, vers_claude, lien_ouvert)
        filet.cancel()
        if DELAI_DEPASSE.is_set() and not reponses and not vers_claude:
            rendre_a_claude()
    except Exception:
        noter('erreur : ' + traceback.format_exc())


def couper_net():
    """Fin immédiate : une sortie normale (même os._exit) fait passer .NET et WebView2 par leur nettoyage,
    2 s pendant lesquelles Claude attend la fin du hook. La réponse est déjà écrite et vidée."""
    for flux in (sys.stdout, sys.stderr, sys.__stdout__):
        try:
            flux.flush()
        except Exception:  # noqa: BLE001
            pass
    noyau = ctypes.WinDLL('kernel32')
    noyau.GetCurrentProcess.restype = ctypes.c_void_p
    noyau.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    noyau.TerminateProcess(noyau.GetCurrentProcess(), 0)
    os._exit(0)


if __name__ == '__main__':
    main()
    couper_net()
