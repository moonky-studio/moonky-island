# Essai de la dictée sans micro, sans son et sans modèle : les classes Dictee et Moteur d'ilot.py tournent
# avec un faux Whisper (faux_whisper.py, même protocole que dictee_whisper.py). Vérifie le choix du moteur,
# les délais bornés, le repli sur le processeur, le marqueur de 12 h et les abandons (Échap, « Répondre dans
# Claude », fermeture de l'îlot). Le micro (MCI) est bloqué ; tout s'écrit dans un dossier temporaire effacé
# à la fin, jamais dans le dossier de données réel. Environ 25 s, code de sortie 1 si un cas échoue.
# Lancement : py -3.12-64 essais\essai_dictee.py
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import wave

sys.stdout.reconfigure(encoding='utf-8')
os.environ['ILOT_ESSAI'] = '1'
os.environ['ILOT_LANGUE'] = 'fr'  # textes attendus en français, quelle que soit la langue de Windows
os.environ.pop('ILOT_WHISPER_CPU', None)

ESSAIS = os.path.dirname(os.path.abspath(__file__))
ICI = os.path.join(os.path.dirname(ESSAIS), 'ilot')
TMP = tempfile.mkdtemp(prefix='ilot-essai-dictee-')
os.environ['MOONKY_ILOT_DONNEES'] = os.path.join(TMP, 'donnees')  # avant l'import : commun.py le lit une fois
sys.path.insert(0, ICI)
import ilot  # noqa: E402

ilot.PYTHON_WHISPER = sys.executable
ilot.TRAVAILLEUR = os.path.join(ESSAIS, 'faux_whisper.py')
ilot.DICTEES = os.path.join(TMP, 'dictees')
ilot.CUDA_KO = os.path.join(TMP, 'cuda_ko')
ilot.JOURNAL_WHISPER = os.path.join(TMP, 'whisper.log')
ilot.JOURNAL = os.path.join(TMP, 'ilot.log')
LANCEMENTS = os.path.join(TMP, 'lancements.log')
os.environ['FAUX_JOURNAL'] = LANCEMENTS

ilot.Dictee.ATTENTE_CARTE = 1.5
ilot.Dictee.ATTENTE_PRET = 4
ilot.Dictee.DELAI_CARTE = (1.0, 0.1)
ilot.Dictee.DELAI_PROCESSEUR = (2.0, 0.1)

APPELS_MCI = []


def mci_interdit(*args, **kwargs):
    APPELS_MCI.append(args)
    raise RuntimeError('MCI interdit pendant les essais')


ilot.mci = mci_interdit

ORDRES = []
SECONDES = [2.0]


def ecrire_wav(chemin, secondes):
    with wave.open(chemin, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b'\x00\x00' * int(16000 * secondes))


def faux_micro(self, ordre, chemin='', delai=20):
    ORDRES.append(ordre)
    if ordre == 'fin':
        ecrire_wav(chemin, SECONDES[0])
    return ('ok', '0' if ordre == 'niveau' else '')


ilot.Dictee._micro = faux_micro

PROCS = []
_init_moteur = ilot.Moteur.__init__


def init_suivi(self, processeur, prevenir):
    _init_moteur(self, processeur, prevenir)
    PROCS.append(self._proc)


ilot.Moteur.__init__ = init_suivi


def nouvelle_dictee(carte='rapide', cpu='rapide', libre=8000):
    os.environ['FAUX_MODE_CARTE'] = carte
    os.environ['FAUX_MODE_CPU'] = cpu
    ilot.memoire_graphique_libre = lambda: libre
    return ilot.Dictee()


def journal():
    try:
        with open(ilot.JOURNAL, encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def lancements():
    try:
        with open(LANCEMENTS, encoding='utf-8') as f:
            return [' '.join(x.split()[1:]) for x in f.read().splitlines() if x.strip()]
    except OSError:
        return []


def mesurer(fn, *args):
    t = time.time()
    try:
        r = fn(*args)
        return 'ok', r, time.time() - t
    except ilot.Abandon:
        return 'abandon', None, time.time() - t
    except Exception as e:  # noqa: BLE001
        return 'erreur', str(e), time.time() - t


def en_fond(fn, *args):
    resultat = {}

    def lancer():
        resultat['r'] = mesurer(fn, *args)

    t = threading.Thread(target=lancer, daemon=True)
    t.start()
    return t, resultat


def attendre_fin_processus(procs, limite=2.0):
    fin = time.time() + limite
    while time.time() < fin:
        if all(p.poll() is not None for p in procs):
            return True
        time.sleep(0.05)
    return False


CAS = []


def cas(fonction):
    CAS.append(fonction)
    return fonction


@cas
def carte_normale():
    d = nouvelle_dictee()
    try:
        t = time.time()
        d.debut()
        assert time.time() - t < 0.3, 'debut() a attendu le moteur'
        time.sleep(0.8)
        etat, texte, duree = mesurer(d.fin, 1)
        assert (etat, texte) == ('ok', 'texte cuda'), (etat, texte)
        assert duree < 1, f'{duree:.2f} s'
        assert not os.listdir(ilot.DICTEES), 'enregistrement non effacé'
        assert 'Whisper prêt sur la carte graphique' in journal(), journal()
        assert 'transcrite sur la carte graphique' in journal(), journal()
        etat, texte, _ = mesurer(d.fin, 2)
        assert (etat, texte) == ('ok', 'texte cuda'), (etat, texte)
        assert lancements() == ['cuda rapide'], lancements()
    finally:
        d.fermer()


@cas
def debut_sans_attendre_nvidia_smi():
    d = nouvelle_dictee()

    def lente():
        time.sleep(1.5)
        return 8000

    ilot.memoire_graphique_libre = lente
    try:
        t = time.time()
        d.debut()
        assert time.time() - t < 0.3, f'debut() a pris {time.time() - t:.2f} s'
        etat, texte, duree = mesurer(d.fin, 1)
        assert (etat, texte) == ('ok', 'texte cuda'), (etat, texte)
    finally:
        d.fermer()


@cas
def carte_pleine():
    d = nouvelle_dictee(libre=1500)
    try:
        d.debut()
        etat, texte, _ = mesurer(d.fin, 1)
        assert (etat, texte) == ('ok', 'texte cpu'), (etat, texte)
        assert 'carte graphique occupée (1500 Mo libres)' in journal(), journal()
        assert lancements() == ['cpu rapide'], lancements()
    finally:
        d.fermer()


@cas
def nvidia_smi_muet():
    d = nouvelle_dictee(libre=None)
    try:
        d.debut()
        etat, texte, _ = mesurer(d.fin, 1)
        assert (etat, texte) == ('ok', 'texte cuda'), (etat, texte)
    finally:
        d.fermer()


@cas
def carte_jamais_prete():
    d = nouvelle_dictee(carte='jamais_pret')
    try:
        d.debut()
        etat, texte, duree = mesurer(d.fin, 1)
        assert (etat, texte) == ('ok', 'texte cpu'), (etat, texte)
        assert 1.4 < duree < 3, f'{duree:.2f} s'
        assert 'carte graphique pas prête après 1.5 s' in journal(), journal()
        assert attendre_fin_processus(PROCS[-2:-1]), 'le moteur carte graphique tourne encore'
        assert not os.path.exists(ilot.CUDA_KO), 'marqueur écrit à tort'
    finally:
        d.fermer()


@cas
def carte_plante_au_chargement():
    d = nouvelle_dictee(carte='crash_chargement')
    try:
        d.debut()
        etat, texte, duree = mesurer(d.fin, 1)
        assert (etat, texte) == ('ok', 'texte cpu'), (etat, texte)
        assert duree < 2, f'{duree:.2f} s'
        assert os.path.exists(ilot.CUDA_KO), 'marqueur absent'
        assert 'processeur pour 12 h' in journal(), journal()
    finally:
        d.fermer()
    open(LANCEMENTS, 'w').close()
    d = nouvelle_dictee()  # îlot suivant : la carte est écartée sans essai
    try:
        d.debut()
        etat, texte, _ = mesurer(d.fin, 1)
        assert (etat, texte) == ('ok', 'texte cpu'), (etat, texte)
        assert lancements() == ['cpu rapide'], lancements()
    finally:
        d.fermer()


@cas
def marqueur_de_11_h_et_de_13_h():
    with open(ilot.CUDA_KO, 'w') as f:
        f.write('essai')
    for heures, attendu in ((11, 'texte cpu'), (13, 'texte cuda')):
        ancien = time.time() - heures * 3600
        os.utime(ilot.CUDA_KO, (ancien, ancien))
        d = nouvelle_dictee()
        try:
            d.debut()
            etat, texte, _ = mesurer(d.fin, 1)
            assert (etat, texte) == ('ok', attendu), (heures, etat, texte)
        finally:
            d.fermer()


@cas
def carte_lente():
    d = nouvelle_dictee(carte='lent_transcription')
    try:
        d.debut()
        time.sleep(0.8)
        etat, texte, duree = mesurer(d.fin, 1)
        assert (etat, texte) == ('ok', 'texte cpu'), (etat, texte)
        assert 1.1 < duree < 3, f'{duree:.2f} s'
        assert 'carte graphique trop lente ou arrêtée (pas de réponse' in journal(), journal()
        assert not os.path.exists(ilot.CUDA_KO), 'marqueur écrit à tort'
    finally:
        d.fermer()


@cas
def carte_plante_en_transcription():
    d = nouvelle_dictee(carte='crash_transcription')
    try:
        d.debut()
        time.sleep(0.8)
        etat, texte, duree = mesurer(d.fin, 1)
        assert (etat, texte) == ('ok', 'texte cpu'), (etat, texte)
        assert duree < 2, f'{duree:.2f} s'
        assert not os.path.exists(ilot.CUDA_KO), 'marqueur écrit à tort'
    finally:
        d.fermer()


@cas
def processeur_lent():
    d = nouvelle_dictee(cpu='lent_transcription', libre=1500)
    try:
        d.debut()
        time.sleep(0.8)
        etat, texte, duree = mesurer(d.fin, 1)
        assert etat == 'erreur' and 'prend trop de temps' in texte, (etat, texte)
        assert 2 < duree < 3, f'{duree:.2f} s'
        assert not os.listdir(ilot.DICTEES), 'enregistrement non effacé'
    finally:
        d.fermer()


@cas
def aucun_moteur_pret():
    d = nouvelle_dictee(carte='jamais_pret', cpu='jamais_pret')
    try:
        d.debut()
        etat, texte, duree = mesurer(d.fin, 1)
        assert etat == 'erreur' and 'ne démarre pas' in texte, (etat, texte)
        assert 3.8 < duree < 5, f'{duree:.2f} s'
    finally:
        d.fermer()


@cas
def tous_les_moteurs_plantent():
    d = nouvelle_dictee(carte='crash_chargement', cpu='crash_chargement')
    try:
        d.debut()
        etat, texte, duree = mesurer(d.fin, 1)
        assert etat == 'erreur' and 's’est arrêté' in texte, (etat, texte)
        assert duree < 3, f'{duree:.2f} s'
    finally:
        d.fermer()


@cas
def fermeture_pendant_transcription():
    SECONDES[0] = 20
    d = nouvelle_dictee(carte='lent_transcription')
    try:
        d.debut()
        time.sleep(0.8)
        fil, r = en_fond(d.fin, 1)
        time.sleep(0.4)
        t = time.time()
        d.fermer()
        fil.join(3)
        assert r.get('r', ('rien',))[0] == 'abandon', r
        assert time.time() - t < 0.8, f'{time.time() - t:.2f} s'
        assert not os.path.exists(ilot.CUDA_KO), 'marqueur écrit à tort'
    finally:
        SECONDES[0] = 2.0
        d.fermer()


@cas
def fermeture_pendant_chargement():
    d = nouvelle_dictee(carte='jamais_pret', cpu='jamais_pret')
    try:
        d.debut()
        fil, r = en_fond(d.fin, 1)
        time.sleep(0.5)
        t = time.time()
        d.fermer()
        fil.join(3)
        assert r.get('r', ('rien',))[0] == 'abandon', r
        assert time.time() - t < 0.8, f'{time.time() - t:.2f} s'
        assert not os.path.exists(ilot.CUDA_KO), 'marqueur écrit à tort'
    finally:
        d.fermer()


@cas
def abandon_pendant_transcription_puis_nouvelle_dictee():
    SECONDES[0] = 20
    d = nouvelle_dictee(carte='lent_transcription')
    try:
        d.debut()
        time.sleep(0.8)
        fil, r = en_fond(d.fin, 1)
        time.sleep(0.4)
        t = time.time()
        d.abandonner(1)
        fil.join(3)
        assert r.get('r', ('rien',))[0] == 'abandon', r
        assert time.time() - t < 0.8, f'{time.time() - t:.2f} s'
        assert 'transcription arrêtée en cours de route' in journal(), journal()
        SECONDES[0] = 2.0
        os.environ['FAUX_MODE_CARTE'] = 'rapide'
        d.debut()  # le moteur tué se recharge pendant que la personne parle
        time.sleep(0.6)
        etat, texte, _ = mesurer(d.fin, 2)
        assert (etat, texte) == ('ok', 'texte cuda'), (etat, texte)
        assert lancements() == ['cuda lent_transcription', 'cuda rapide'], lancements()
        assert not os.path.exists(ilot.CUDA_KO), 'marqueur écrit à tort'
    finally:
        SECONDES[0] = 2.0
        d.fermer()


@cas
def abandon_avant_la_fin_de_l_enregistrement():
    d = nouvelle_dictee()
    try:
        d.debut()
        d.abandonner(5)
        etat, _, duree = mesurer(d.fin, 5)
        assert etat == 'abandon', etat
        assert 'annuler' in ORDRES and 'fin' not in ORDRES, ORDRES
        etat, texte, _ = mesurer(d.fin, 6)  # la dictée suivante n'est pas touchée
        assert (etat, texte) == ('ok', 'texte cuda'), (etat, texte)
    finally:
        d.fermer()


@cas
def abandon_pendant_le_chargement():
    d = nouvelle_dictee(carte='jamais_pret', cpu='jamais_pret')
    try:
        d.debut()
        fil, r = en_fond(d.fin, 7)
        time.sleep(0.5)
        t = time.time()
        d.abandonner(7)
        fil.join(3)
        assert r.get('r', ('rien',))[0] == 'abandon', r
        assert time.time() - t < 0.8, f'{time.time() - t:.2f} s'
        assert any(m.vivant() for m in d._moteurs), 'le chargement en cours a été coupé'
    finally:
        d.fermer()


@cas
def repli_interne_sur_le_processeur():
    d = nouvelle_dictee(carte='pret_cpu')
    try:
        d.debut()
        etat, texte, _ = mesurer(d.fin, 1)
        assert (etat, texte) == ('ok', 'texte cpu'), (etat, texte)
        assert 'Whisper prêt sur le processeur' in journal(), journal()
    finally:
        d.fermer()


@cas
def vieux_enregistrements_effaces():
    os.makedirs(ilot.DICTEES, exist_ok=True)
    vieux = os.path.join(ilot.DICTEES, 'vieux.wav')
    recent = os.path.join(ilot.DICTEES, 'recent.wav')
    for chemin in (vieux, recent):
        ecrire_wav(chemin, 0.1)
    ancien = time.time() - 11 * 60
    os.utime(vieux, (ancien, ancien))
    d = nouvelle_dictee()
    try:
        assert not os.path.exists(vieux), 'vieil enregistrement gardé'
        assert os.path.exists(recent), 'enregistrement récent effacé'
    finally:
        d.fermer()
        os.remove(recent)


def main():
    resultats = []
    for f in CAS:
        for chemin in (ilot.JOURNAL, LANCEMENTS):
            open(chemin, 'w').close()
        if os.path.exists(ilot.CUDA_KO):
            os.remove(ilot.CUDA_KO)
        ORDRES.clear()
        t = time.time()
        try:
            f()
            resultats.append((f.__name__, 'OK', time.time() - t, ''))
        except AssertionError as e:
            resultats.append((f.__name__, 'ÉCHEC', time.time() - t, str(e)))
        except Exception:  # noqa: BLE001
            resultats.append((f.__name__, 'ERREUR', time.time() - t, traceback.format_exc()))
    restants = attendre_fin_processus(PROCS, 3)
    for nom, statut, duree, detail in resultats:
        print(f'{statut:6} {nom} ({duree:.1f} s)' + (f'\n       {detail}' if detail else ''))
    print(f'{len(PROCS)} faux moteurs lancés, tous arrêtés : {restants}')
    print(f'appels MCI : {len(APPELS_MCI)}')
    if not restants:
        for p in PROCS:
            if p.poll() is None:
                p.kill()
        time.sleep(0.5)
    shutil.rmtree(TMP, ignore_errors=True)
    reussi = restants and not APPELS_MCI and all(r[1] == 'OK' for r in resultats)
    sys.exit(0 if reussi else 1)


main()
