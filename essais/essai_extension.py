# Essai de l'extension sans fenêtre, sans son, sans micro et sans réseau : manifestes, questions de fin de tour,
# rappel de démarrage, hooks de l'îlot et de la pastille quand rien n'est installé, guetteur de la pastille en mode
# observation, réglages, journaux, installateur (coupe-circuit, vérification, remplacement des bibliothèques).
# Les hooks reçoivent le JSON que Claude Code leur enverrait, par le même lanceur (py.exe -3.12-64). Tout s'écrit
# dans un dossier temporaire effacé à la fin, jamais dans le dossier de données réel ni dans la config de Claude.
# Aucun hook de fenêtre ne tourne avec des bibliothèques présentes : l'îlot et la pastille s'arrêtent avant
# d'afficher quoi que ce soit. Environ 15 s, code de sortie 1 si un cas échoue.
# Lancement : py -3.12-64 essais\essai_extension.py
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import types

sys.stdout.reconfigure(encoding='utf-8')
sys.dont_write_bytecode = True
os.environ['ILOT_ESSAI'] = '1'
os.environ['ILOT_LANGUE'] = 'fr'  # textes attendus en français, quelle que soit la langue de Windows
for variable in ('ILOT_DELAI_MAX', 'ILOT_TEST_AUTO', 'CLAUDE_CONFIG_DIR'):
    os.environ.pop(variable, None)

ESSAIS = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ESSAIS)
ILOT = os.path.join(RACINE, 'ilot')
MARCHE = os.path.join(RACINE, '.claude-plugin', 'marketplace.json')

TMP = tempfile.mkdtemp(prefix='ilot-essai-extension-')
SANS_LIB = os.path.join(TMP, 'sans-lib')          # rien d'installé : l'îlot et la pastille renoncent
FAUX_LIB = os.path.join(TMP, 'faux-lib')          # bibliothèques vides : seul le rappel y tourne
EN_PROCESS = os.path.join(TMP, 'en-process')      # dossier de données des modules importés ici
APPDATA_VIDE = os.path.join(TMP, 'appdata')       # aucune fiche de session de l'appli
STOP = os.path.join(TMP, 'stop')
OBSERVATION = os.path.join(TMP, 'observation')
INSTALLATEUR = os.path.join(TMP, 'installateur')
CONFIG_CLAUDE = os.path.join(TMP, 'config-claude')
for dossier in (SANS_LIB, EN_PROCESS, APPDATA_VIDE, STOP, OBSERVATION, INSTALLATEUR, CONFIG_CLAUDE):
    os.makedirs(dossier)
for paquet in ('webview', 'pythonnet'):
    os.makedirs(os.path.join(FAUX_LIB, 'lib', paquet))
    open(os.path.join(FAUX_LIB, 'lib', paquet, '__init__.py'), 'w').close()

os.environ['MOONKY_ILOT_DONNEES'] = EN_PROCESS  # avant l'import : commun.py le lit une fois
sys.path[:0] = [ILOT, RACINE]
import commun  # noqa: E402
import fin_de_tour  # noqa: E402
import attente  # noqa: E402
import rappel  # noqa: E402
import ilot  # noqa: E402
import installer  # noqa: E402

assert commun.DONNEES == os.path.abspath(EN_PROCESS), commun.DONNEES
WEBVIEW2 = bool(commun.webview2_version())  # sans WebView2, le faux dossier de bibliothèques ne suffit pas

CAS = []


def cas(f):
    CAS.append(f)
    return f


def lancer(script, entree=b'', donnees=SANS_LIB, env_plus=None, args=(), delai=60):
    """Lance un script comme le ferait Claude Code (py.exe -3.12-64), le JSON du hook sur l'entrée standard."""
    env = dict(os.environ, MOONKY_ILOT_DONNEES=donnees, ILOT_ESSAI='1', PYTHONDONTWRITEBYTECODE='1',
               PYTHONIOENCODING='utf-8', APPDATA=APPDATA_VIDE)
    env.update(env_plus or {})
    brut = entree if isinstance(entree, bytes) else json.dumps(entree).encode('utf-8')
    debut = time.perf_counter()
    r = subprocess.run(['py.exe', '-3.12-64', script, *args], input=brut, env=env, capture_output=True,
                       timeout=delai)
    return r, time.perf_counter() - debut


def script(nom):
    return os.path.join(ILOT, nom)


def journal(donnees, nom):
    """Lignes des journaux du script nom dans ce dossier de données."""
    lignes = []
    dossier = os.path.join(donnees, 'journaux')
    if os.path.isdir(dossier):
        for f in sorted(os.listdir(dossier)):
            if f.startswith(nom + '-') and f.endswith('.log'):
                with open(os.path.join(dossier, f), encoding='utf-8') as h:
                    lignes += h.read().splitlines()
    return lignes


def ecrire(chemin, contenu):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, 'w', encoding='utf-8') as f:
        f.write(contenu if isinstance(contenu, str) else json.dumps(contenu, ensure_ascii=False))


def effacer(chemin):
    try:
        os.remove(chemin)
    except FileNotFoundError:
        pass


def sortie_json(r):
    assert r.returncode == 0, f'code {r.returncode} : {r.stderr.decode("utf-8", "replace")[-400:]}'
    texte = r.stdout.decode('ascii')  # les hooks n'écrivent que de l'ASCII (accents échappés)
    return json.loads(texte)


def rien(r, quoi):
    assert r.returncode == 0, f'{quoi} : code {r.returncode} : {r.stderr.decode("utf-8", "replace")[-400:]}'
    assert r.stdout == b'', f'{quoi} : sortie inattendue {r.stdout[:200]!r}'


# ---------------------------------------------------------------------------
# Manifestes
# ---------------------------------------------------------------------------

@cas
def manifestes():
    with open(os.path.join(RACINE, '.claude-plugin', 'plugin.json'), encoding='utf-8') as f:
        plugin = json.load(f)
    assert plugin.get('name') == 'moonky-island' and plugin.get('license') == 'MIT', plugin
    assert 'version' not in plugin, 'version figée : chaque commit doit compter comme une mise à jour'
    with open(os.path.join(RACINE, 'hooks', 'hooks.json'), encoding='utf-8') as f:
        hooks = json.load(f)['hooks']
    assert set(hooks) == {'SessionStart', 'PreToolUse', 'Stop'}, sorted(hooks)
    cibles = {}
    for evenement, groupes in hooks.items():
        for groupe in groupes:
            motif = groupe.get('matcher')
            if motif is not None:
                re.compile(motif)
            for h in groupe['hooks']:
                assert h.get('type') == 'command' and h.get('command') == 'py.exe', h
                assert h['args'][0] == '-3.12-64', h
                chemin = h['args'][1].replace('${CLAUDE_PLUGIN_ROOT}', RACINE)
                assert os.path.isfile(chemin), f'script introuvable : {h["args"][1]}'
                assert isinstance(h.get('timeout'), int), h
                cibles[(evenement, motif)] = (os.path.basename(chemin), h['timeout'])
    assert cibles[('SessionStart', None)][0] == 'rappel.py', cibles
    assert cibles[('Stop', None)][0] == 'attente.py', cibles
    question = [m for (e, m) in cibles if e == 'PreToolUse' and m and re.search(m, 'AskUserQuestion')]
    assert len(question) == 1 and cibles[('PreToolUse', question[0])][0] == 'ilot.py', cibles
    assert not re.search(question[0], 'AskUserQuestionX') and not re.search(question[0], 'xAskUserQuestion')
    fin = [m for (e, m) in cibles if e == 'PreToolUse' and m and re.search(m, 'mcp__ccd_turn__wrap_up')]
    assert len(fin) == 1 and cibles[('PreToolUse', fin[0])][0] == 'ilot.py', cibles
    assert not re.search(fin[0], 'mcp__ccd_turn__wrap_up_bis')
    # le délai des deux hooks de l'îlot doit couvrir sa limite dure et son filet de sécurité
    assert ilot.DELAI_MAX == 540, ilot.DELAI_MAX
    for motif in (question[0], fin[0]):
        assert cibles[('PreToolUse', motif)][1] > ilot.LIMITE_DURE - ilot.DEBUT + 15, cibles
    with open(MARCHE, encoding='utf-8') as f:
        catalogue = json.load(f)
    assert catalogue.get('name') == 'moonky-island', catalogue
    assert [p.get('name') for p in catalogue['plugins']] == ['moonky-island'], catalogue
    assert catalogue['plugins'][0].get('source') == './', catalogue
    assert installer.EXTENSION == 'moonky-island@moonky-island', installer.EXTENSION


# ---------------------------------------------------------------------------
# Questions de fin de tour (wrap_up), relayées dans l'îlot
# ---------------------------------------------------------------------------

def wrap(session, ask, actions, outil='mcp__ccd_turn__wrap_up', recap='Récapitulatif.'):
    return {'tool_name': outil, 'session_id': session, 'hook_event_name': 'PreToolUse',
            'tool_input': {'recap': recap, 'ask': ask, 'actions': actions}}


REPONSES = [{'label': 'Oui'}, {'label': 'Non'}]


def passer_ilot(entree, quoi, donnees=SANS_LIB):
    """Lance le hook de l'îlot, qui doit s'effacer sans rien écrire ; renvoie les nouvelles lignes de son journal."""
    avant = len(journal(donnees, 'ilot'))
    r, duree = lancer(script('ilot.py'), entree, donnees)
    rien(r, quoi)
    assert duree < 10, f'{quoi} : {duree:.1f} s'
    return journal(donnees, 'ilot')[avant:]


@cas
def fin_de_tour_questions():
    s = 'session-fin-de-tour'
    q = fin_de_tour.questions
    assert q(wrap(s, 'On publie ?', REPONSES, outil='Bash')) is None, 'autre outil relayé'
    assert q(wrap(s, 'On commite ?', [{'action': 'commit'}])) is None, 'bouton d’action relayé'
    assert q(wrap(s, 'On commite ?', [{'label': 'Plus tard'}, {'action': 'commit'}])) is None, 'action mêlée relayée'
    assert q(wrap(s, 'PR ?', json.dumps([{'action': 'create_pr'}]))) is None, 'actions en texte relayées'
    assert q(wrap(s, 'Quel nom ?', [])) is None, 'question sans bouton relayée'
    assert q(wrap(s, 'Quel nom ?', 'pas du json')) is None, 'actions illisibles relayées'
    assert q({'tool_name': fin_de_tour.OUTIL, 'tool_input': 'texte'}) is None, 'entrée sans dictionnaire relayée'
    liste = q(wrap(s, '  On   publie ?\n', [{'label': ' Oui '}, {'label': 'Oui'}, {'label': 'Pas  maintenant'}],
                   recap='Le  dépôt est prêt.\nRien de poussé.'))
    assert liste and len(liste) == 1, liste
    question = liste[0]
    assert question['question'] == 'On publie ?', question
    assert question['contexte'] == 'Le dépôt est prêt. Rien de poussé.', question
    assert question['multiSelect'] is False and question['header'] == '', question
    assert [o['label'] for o in question['options']] == ['Oui', 'Pas maintenant'], question
    assert question['options'][0].get('recommande') is True, question
    assert 'recommande' not in question['options'][1], question
    seul = q(wrap(s, 'Je lance ?', json.dumps([{'label': 'Oui'}])))
    assert seul and 'recommande' not in seul[0]['options'][0], 'bouton unique marqué recommandé'
    assert len(q(wrap(s, 'Lequel ?', [{'label': str(i)} for i in range(12)]))[0]['options']) == 9
    assert not os.path.exists(fin_de_tour.chemin_etat(s)), 'état écrit sans réponse'
    with open(os.path.join(ILOT, 'ilot.html'), encoding='utf-8') as f:
        page = f.read()
    assert "'q-contexte'" in page and 'o.recommande' in page, 'la page ne montre ni le résumé ni la recommandation'


@cas
def fin_de_tour_reponse():
    s = 'session-reponse'
    etat = fin_de_tour.chemin_etat(s)
    entree = wrap(s, 'On  publie ?', REPONSES)
    assert fin_de_tour.sortie(entree, {}) is None and fin_de_tour.sortie(entree, None) is None
    assert fin_de_tour.sortie(entree, {'On publie ?': '  '}) is None, 'réponse vide envoyée'
    assert not os.path.exists(etat), 'relais noté sans réponse'
    d = fin_de_tour.sortie(entree, {'On publie ?': 'Oui'})
    h = d['hookSpecificOutput']
    assert h['hookEventName'] == 'PreToolUse' and h['permissionDecision'] == 'deny', d
    raison = h['permissionDecisionReason']
    assert raison.startswith(commun.MARQUE_GARDE), raison
    assert '« On publie ? »' in raison and '« Oui »' in raison and 'sans `ask`' in raison, raison
    with open(etat, encoding='utf-8') as f:
        assert 'publie' not in f.read(), 'texte de la question gardé sur le disque'
    # la même question revient (Claude n'a pas suivi la consigne) : laissée à l'appli, sans tourner en rond
    assert fin_de_tour.questions(entree) is None, 'même question relayée deux fois'
    assert any('déjà relayée' in x for x in journal(EN_PROCESS, 'ilot')), 'question répétée pas notée'
    assert fin_de_tour.questions(wrap(s, 'On  PUBLIE ?', REPONSES)) is None, 'casse ou espaces comptés'
    assert fin_de_tour.questions(wrap(s, 'Et ensuite ?', REPONSES)), 'question suivante pas relayée'
    ecrire(etat, {'question': fin_de_tour.empreinte('On publie ?'), 'quand': time.time() - 16 * 60})
    assert fin_de_tour.questions(entree), 'relais de plus de 15 min encore compté'
    fin_de_tour.noter_relais(s, 'On publie ?')
    assert fin_de_tour.questions(wrap(s, '', REPONSES)) is None
    assert not os.path.exists(etat), 'état pas oublié après un wrap_up sans question'
    # réponse rangée sous une autre clé : la première non vide sert
    d = fin_de_tour.sortie(wrap(s, 'Lequel ?', REPONSES), {'autre': 'Le second'})
    assert '« Le second »' in d['hookSpecificOutput']['permissionDecisionReason'], d
    assert os.path.dirname(fin_de_tour.chemin_etat('../../x:y')) == fin_de_tour.ETAT, 'nom de session non assaini'
    os.environ['ILOT_LANGUE'] = 'en'
    commun.langue.cache_clear()
    try:
        raison = fin_de_tour.raison('Ship it?', 'Yes')
        assert raison.startswith(commun.MARQUE_GARDE + ':') and '"Ship it?"' in raison and '"Yes"' in raison, raison
    finally:
        os.environ['ILOT_LANGUE'] = 'fr'
        commun.langue.cache_clear()


@cas
def fin_de_tour_par_hook():
    assert commun.DEFAUTS[fin_de_tour.REGLAGE] is True and fin_de_tour.active(), 'relais coupé par défaut'
    entree = wrap('session-hook', 'On publie ?', REPONSES)
    nouvelles = passer_ilot(entree, 'bibliothèques absentes')
    assert any('îlot pas affiché (bibliothèques pas installées) : question laissée à Claude' in x
               for x in nouvelles), nouvelles
    for quoi, autre in (('bouton d’action', wrap('session-hook', 'On commite ?', [{'action': 'commit'}])),
                        ('sans question', wrap('session-hook', '', REPONSES)),
                        ('sans bouton', wrap('session-hook', 'Quel nom ?', []))):
        assert not passer_ilot(autre, quoi), quoi
    reglages = os.path.join(SANS_LIB, 'reglages.json')
    ecrire(reglages, {fin_de_tour.REGLAGE: False})
    try:
        assert not passer_ilot(entree, 'relais coupé par le réglage')
    finally:
        effacer(reglages)
    coupe = os.path.join(SANS_LIB, 'coupe')
    ecrire(coupe, 'essai')
    try:
        assert not passer_ilot(entree, 'extension coupée')
    finally:
        effacer(coupe)
    assert not os.path.exists(os.path.join(SANS_LIB, 'etat')), 'état écrit sans réponse'


# ---------------------------------------------------------------------------
# Rappel de démarrage
# ---------------------------------------------------------------------------

@cas
def rappel_demarrage():
    entree = {'session_id': 'essai', 'hook_event_name': 'SessionStart', 'source': 'startup'}
    r, _ = lancer(script('rappel.py'), entree, SANS_LIB)
    d = sortie_json(r)['hookSpecificOutput']
    assert d['hookEventName'] == 'SessionStart', d
    texte = d['additionalContext']
    assert 'py -3.12-64' in texte and os.path.join(RACINE, 'installer.py') in texte, texte
    assert 'bibliothèques pas installées' in texte, texte
    r, _ = lancer(script('rappel.py'), entree, SANS_LIB, env_plus={'ILOT_LANGUE': 'en'})
    assert 'libraries not installed' in sortie_json(r)['hookSpecificOutput']['additionalContext']
    coupe = os.path.join(SANS_LIB, 'coupe')
    ecrire(coupe, 'essai')
    try:
        r, _ = lancer(script('rappel.py'), entree, SANS_LIB)
        rien(r, 'extension coupée')
    finally:
        effacer(coupe)
    if WEBVIEW2:
        r, _ = lancer(script('rappel.py'), entree, FAUX_LIB)
        assert sortie_json(r)['hookSpecificOutput']['additionalContext'] == rappel.REGLE_FR
        r, _ = lancer(script('rappel.py'), entree, FAUX_LIB, env_plus={'ILOT_LANGUE': 'en'})
        assert sortie_json(r)['hookSpecificOutput']['additionalContext'] == rappel.REGLE_EN


# ---------------------------------------------------------------------------
# Îlot : rien d'installé, la question reste à Claude
# ---------------------------------------------------------------------------

QUESTION = {'tool_name': 'AskUserQuestion', 'session_id': 'essai', 'hook_event_name': 'PreToolUse',
            'tool_input': {'questions': [{'question': 'Q ?', 'header': 'Essai', 'multiSelect': False,
                                          'options': [{'label': 'A', 'description': 'a'},
                                                      {'label': 'B', 'description': 'b'}]}]}}


@cas
def ilot_sans_bibliotheques():
    assert not os.path.exists(os.path.join(SANS_LIB, 'lib')), 'des bibliothèques dans le dossier sans-lib'
    passage = passer_ilot
    coupe = os.path.join(SANS_LIB, 'coupe')
    ecrire(coupe, 'essai')
    try:
        nouvelles = passage(QUESTION, 'extension coupée')
        assert not nouvelles, nouvelles
    finally:
        effacer(coupe)
    nouvelles = passage(QUESTION, 'bibliothèques absentes')
    assert any('îlot pas affiché (bibliothèques pas installées) : question laissée à Claude' in x
               for x in nouvelles), nouvelles
    nouvelles = passage(b'{pas du json', 'entrée illisible')
    assert any('erreur' in x for x in nouvelles), nouvelles
    deja = json.loads(json.dumps(QUESTION))
    deja['tool_input']['answers'] = {'Q ?': 'A'}
    nouvelles = passage(deja, 'réponses déjà données')
    assert not nouvelles, nouvelles


# ---------------------------------------------------------------------------
# Hors de Windows : tous les hooks s'effacent
# ---------------------------------------------------------------------------

@cas
def hors_windows():
    code = ("import sys, runpy; p = sys.argv[1]; sys.platform = 'linux'; sys.argv = [p]; "
            "runpy.run_path(p, run_name='__main__')")
    for nom in ('ilot.py', 'attente.py', 'rappel.py'):
        r, _ = lancer('-c', QUESTION, SANS_LIB, args=(code, script(nom)))
        rien(r, nom)
    r, _ = lancer('-c', b'', SANS_LIB, args=(code, os.path.join(RACINE, 'installer.py')))
    assert r.returncode == 1 and 'only runs on Windows' in r.stdout.decode('utf-8', 'replace'), r


# ---------------------------------------------------------------------------
# Pastille : hook Stop
# ---------------------------------------------------------------------------

def stop(sid, tp):
    return {'session_id': sid, 'transcript_path': tp, 'hook_event_name': 'Stop', 'stop_hook_active': False}


SID = '0123abcd-0000-4000-8000-000000000000'


@cas
def pastille_hook_stop():
    reglages = os.path.join(STOP, 'reglages.json')

    def passage(entree, quoi):
        avant = len(journal(STOP, 'attente'))
        r, duree = lancer(script('attente.py'), entree, STOP)
        rien(r, quoi)
        assert duree < 5, f'{quoi} : {duree:.1f} s'
        return journal(STOP, 'attente')[avant:]

    coupe = os.path.join(STOP, 'coupe')
    ecrire(coupe, 'essai')
    try:
        assert not passage(stop(SID, __file__), 'extension coupée')
    finally:
        effacer(coupe)
    ecrire(reglages, {'pastille': False})
    assert not passage(stop(SID, __file__), 'pastille désactivée')
    effacer(reglages)
    nouvelles = passage(stop(SID, __file__), 'bibliothèques absentes')
    assert any('pastille pas affichée (bibliothèques pas installées)' in x for x in nouvelles), nouvelles
    ecrire(reglages, {'pastille': 'observation'})
    nouvelles = passage(stop('pas-un-identifiant', __file__), 'identifiant invalide')
    assert any('hook Stop sans identifiant de session valable' in x for x in nouvelles), nouvelles
    nouvelles = passage(stop(SID, os.path.join(TMP, 'absente.jsonl')), 'transcription absente')
    assert any('transcription introuvable' in x for x in nouvelles), nouvelles


@cas
def guetteur_survit_au_hook():
    # Le hook Stop rend la main tout de suite et laisse tourner un guetteur détaché. Lancé par py.exe, il ne doit
    # pas être tué avec lui : sans fiche de session (APPDATA vide), le guetteur le note au bout de 5 s environ.
    ecrire(os.path.join(OBSERVATION, 'reglages.json'), {'pastille': 'observation'})
    tp = os.path.join(OBSERVATION, 'transcription.jsonl')
    ecrire(tp, '')
    r, duree = lancer(script('attente.py'), stop(SID, tp), OBSERVATION)
    rien(r, 'hook Stop')
    assert duree < 5, f'hook Stop : {duree:.1f} s'
    limite = time.time() + 15
    while time.time() < limite:
        if any('0123abcd : fiche de session introuvable' in x for x in journal(OBSERVATION, 'attente')):
            break
        time.sleep(0.5)
    else:
        raise AssertionError('le guetteur n’a rien noté : tué avec py.exe ? '
                             + repr(journal(OBSERVATION, 'attente')))
    time.sleep(0.5)  # laisse le guetteur fermer son journal


# ---------------------------------------------------------------------------
# Pastille : lecture de la transcription et guetteur en mode observation
# ---------------------------------------------------------------------------

def assistant(u, blocs, cote=False):
    return {'type': 'assistant', 'uuid': u, 'isSidechain': cote, 'message': {'role': 'assistant', 'content': blocs}}


def utilisateur(contenu, **plus):
    e = {'type': 'user', 'uuid': 'u-' + str(abs(hash(str(contenu))) % 10 ** 8), 'isSidechain': False,
         'message': {'role': 'user', 'content': contenu}}
    e.update(plus)
    return e


def appel_wrap(ident, ask):
    return {'type': 'tool_use', 'id': ident, 'name': 'mcp__ccd_turn__wrap_up',
            'input': {'recap': 'r', 'ask': ask, 'actions': [{'label': 'Oui'}]}}


def resultat(ident, texte, erreur=False, en_liste=False):
    contenu = [{'type': 'text', 'text': texte}] if en_liste else texte
    b = {'type': 'tool_result', 'tool_use_id': ident, 'content': contenu}
    if erreur:
        b['is_error'] = True
    return b


def texte(t):
    return [{'type': 'text', 'text': t}]


TOUR = [
    utilisateur('Bonjour'),
    assistant('a1', [appel_wrap('t0', 'ANCIEN')]),
    utilisateur([resultat('t0', 'ok')]),
    utilisateur('Nouvelle demande'),                      # début du tour
    assistant('a2', [appel_wrap('t1', 'A1')]),
    utilisateur([resultat('t1', 'ok')]),
    assistant('a3', [appel_wrap('t2', 'B')]),             # dernier wrap_up accepté
    utilisateur([resultat('t2', 'ok')]),
    utilisateur('méta', isMeta=True),                    # ne commence pas un tour
    utilisateur('résumé de la discussion', isCompactSummary=True),
    assistant('a3b', [appel_wrap('t3', 'REFUS')]),
    utilisateur([resultat('t3', fin_de_tour.raison('REFUS', 'Oui'), en_liste=True)]),
    assistant('a3c', [appel_wrap('t4', 'ERREUR')]),
    utilisateur([resultat('t4', 'échec', erreur=True)]),
    assistant('s1', [appel_wrap('t5', 'SOUS-AGENT')], cote=True),
    dict(utilisateur([resultat('t5', 'ok')]), isSidechain=True),
    assistant('a4', texte('Fini.')),
]

TOUT_REFUSE = [
    utilisateur('Bonjour'),
    assistant('a1', [appel_wrap('t0', 'ANCIEN')]),
    utilisateur([resultat('t0', 'ok')]),
    utilisateur('Nouvelle demande'),
    assistant('a2', [appel_wrap('t1', 'REFUS')]),
    utilisateur([resultat('t1', commun.MARQUE_GARDE + ' refusé')]),
    assistant('a5', texte('Fini.')),
]


@cas
def lecture_du_tour():
    assert attente.analyser_tour(TOUR) == ('a4', 'B'), attente.analyser_tour(TOUR)
    assert attente.analyser_tour(TOUT_REFUSE) == ('a5', ''), attente.analyser_tour(TOUT_REFUSE)
    assert attente.analyser_tour([]) == (None, '')
    tp = os.path.join(TMP, 'tour.jsonl')
    ecrire(tp, '\n'.join(json.dumps(e, ensure_ascii=False) for e in TOUR) + '\n{ligne coupée\n')
    assert attente.analyser_tour(attente.fin_transcription(tp)) == ('a4', 'B')
    assert attente.en_anglais('You need to choose the color for the button')
    assert not attente.en_anglais('Choisir la couleur du bouton, puis répondre')
    assert not attente.en_anglais('Valider le deck pour le client')


def fiche_essai(dossier, cli, local, titre, u0, besoin):
    # cliSessionId en premier : le guetteur ne lit que le début des fiches pour trouver la sienne
    fiche = {'cliSessionId': cli, 'sessionId': local, 'title': titre, 'lastAssistantUuid': u0,
             'postTurnSummaryFor': u0, 'postTurnSummary': {'needs_action': besoin, 'status_category': 'needs_input'},
             'latestUserFrameAt': 0, 'lastTurnEdgeAt': 0, 'completedTurns': 3}
    ecrire(os.path.join(dossier, 'a', 'b', local + '.json'), fiche)


@cas
def guetteur_en_observation():
    fiches = os.path.join(TMP, 'fiches')
    reglages = os.path.join(EN_PROCESS, 'reglages.json')
    sauve = (attente.FICHES, attente.claude_au_premier_plan, attente.session_au_premier_plan)
    attente.FICHES = fiches
    attente.claude_au_premier_plan = lambda: False
    attente.session_au_premier_plan = lambda: None
    ecrire(reglages, {'pastille': 'observation'})
    try:
        cli = 'abcdef00-0000-4000-8000-000000000001'
        fiche_essai(fiches, cli, 'local_essai', "Session d'essai", 'a4', 'Choisir la couleur du bouton')
        tp = os.path.join(TMP, 'guetteur.jsonl')
        ecrire(tp, '\n'.join(json.dumps(e, ensure_ascii=False) for e in TOUR) + '\n')
        avant = len(journal(EN_PROCESS, 'attente'))
        attente.guetter(cli, tp, time.time())
        nouvelles = journal(EN_PROCESS, 'attente')[avant:]
        assert any("« Session d'essai » : observation | " in x for x in nouvelles), nouvelles
        assert any("« Session d'essai » : aurait affiché (ask) : 'B'" in x for x in nouvelles), nouvelles
        with open(os.path.join(attente.TRAITES, 'local_essai'), encoding='ascii') as f:
            assert f.read().strip() == 'a4'
        avant = len(journal(EN_PROCESS, 'attente'))
        attente.guetter(cli, tp, time.time())
        nouvelles = journal(EN_PROCESS, 'attente')[avant:]
        assert any('tour déjà traité' in x for x in nouvelles), nouvelles

        cli2 = 'abcdef00-0000-4000-8000-000000000002'
        fiche_essai(fiches, cli2, 'local_essai2', 'Autre session', 'z9',
                    'You need to choose the color for the button')
        tp2 = os.path.join(TMP, 'guetteur2.jsonl')
        ecrire(tp2, json.dumps(utilisateur('Bonjour')) + '\n' + json.dumps(assistant('z9', texte('Fini.'))) + '\n')
        avant = len(journal(EN_PROCESS, 'attente'))
        attente.guetter(cli2, tp2, time.time())
        nouvelles = journal(EN_PROCESS, 'attente')[avant:]
        assert any('en anglais remplacé' in x for x in nouvelles), nouvelles
        assert any("« Autre session » : aurait affiché (résumé) : 'Attend ta réponse dans Claude'" in x
                   for x in nouvelles), nouvelles

        # interface en anglais : le résumé anglais de l'appli est montré tel quel
        os.environ['ILOT_LANGUE'] = 'en'
        commun.langue.cache_clear()
        cli3 = 'abcdef00-0000-4000-8000-000000000003'
        fiche_essai(fiches, cli3, 'local_essai3', 'English session', 'y8',
                    'You need to choose the color for the button')
        tp3 = os.path.join(TMP, 'guetteur3.jsonl')
        ecrire(tp3, json.dumps(utilisateur('Hello')) + '\n' + json.dumps(assistant('y8', texte('Done.'))) + '\n')
        avant = len(journal(EN_PROCESS, 'attente'))
        attente.guetter(cli3, tp3, time.time())
        nouvelles = journal(EN_PROCESS, 'attente')[avant:]
        assert not any('en anglais remplacé' in x for x in nouvelles), nouvelles
        assert any("« English session » : aurait affiché (résumé) : 'You need to choose" in x
                   for x in nouvelles), nouvelles
        assert not os.listdir(attente.ENTREES) if os.path.isdir(attente.ENTREES) else True, 'pastille écrite'
    finally:
        os.environ['ILOT_LANGUE'] = 'fr'
        commun.langue.cache_clear()
        attente.FICHES, attente.claude_au_premier_plan, attente.session_au_premier_plan = sauve
        effacer(reglages)


# ---------------------------------------------------------------------------
# Réglages et journaux
# ---------------------------------------------------------------------------

@cas
def reglages():
    chemin = commun.REGLAGES
    try:
        with open(chemin, 'w', encoding='utf-8-sig') as f:  # Bloc-notes ajoute parfois une marque d'encodage
            json.dump({'son': 'verre'}, f)
        assert commun.reglages()['son'] == 'verre' and commun.reglages()['pastille'] is True
        ecrire(chemin, '{pas du json')
        assert commun.reglages() == commun.DEFAUTS
        ecrire(chemin, [1, 2])
        assert commun.reglages() == commun.DEFAUTS
        for v in (True, 'oui', ' Yes ', '1', 'on', 'TRUE'):
            assert commun.oui(v), v
        for v in (False, 'non', '', None, 0, 'observation'):
            assert not commun.oui(v), v
        for valeur, attendu in ((True, 'oui'), (False, 'non'), ('observation', 'observation'),
                                ('Observation ', 'observation'), ('non', 'non')):
            ecrire(chemin, {'pastille': valeur})
            assert attente.mode_pastille() == attendu, (valeur, attente.mode_pastille())
        effacer(chemin)
        assert attente.mode_pastille() == 'oui'
        assert not commun.dictee_active(), 'dictée active par défaut'
        python_whisper = os.path.join(TMP, 'whisper', 'python.exe')
        modele = os.path.join(TMP, 'whisper', 'modele')
        ecrire(python_whisper, '')
        os.makedirs(modele, exist_ok=True)
        ecrire(chemin, {'dictee': True, 'whisper_python': python_whisper, 'whisper_modele': modele})
        assert not commun.dictee_active(), 'micro proposé sans modèle'
        ecrire(os.path.join(modele, 'model.bin'), '')
        assert commun.dictee_active(), 'dictée pas active avec Whisper et son modèle'
        ecrire(chemin, {'dictee': False, 'whisper_python': python_whisper, 'whisper_modele': modele})
        assert not commun.dictee_active(), 'dictée active alors que désactivée'
    finally:
        effacer(chemin)


@cas
def langue():
    chemin = commun.REGLAGES
    try:
        os.environ['ILOT_LANGUE'] = ''
        for valeur, attendu in (('en', 'en'), (' FR ', 'fr'), ('auto', None), ('klingon', None)):
            ecrire(chemin, {'langue': valeur})
            commun.langue.cache_clear()
            trouve = commun.langue()
            assert trouve == attendu if attendu else trouve in ('fr', 'en'), (valeur, trouve)
            assert commun.t('a', 'b') == ('a' if trouve == 'fr' else 'b')
        os.environ['ILOT_LANGUE'] = 'en'
        ecrire(chemin, {'langue': 'fr'})
        commun.langue.cache_clear()
        assert commun.langue() == 'en', 'ILOT_LANGUE ne passe pas avant le réglage'

        # langue parlée pour Whisper : français si l'îlot l'est, sinon reconnue par Whisper
        effacer(chemin)
        assert commun.dictee_langue() == '', 'dictée forcée alors que l’îlot est en anglais'
        os.environ['ILOT_LANGUE'] = 'fr'
        commun.langue.cache_clear()
        assert commun.dictee_langue() == 'fr'
        for valeur, attendu in ((' DE ', 'de'), ('en', 'en'), ('auto', 'fr'), ('', 'fr')):
            ecrire(chemin, {'dictee_langue': valeur})
            assert commun.dictee_langue() == attendu, (valeur, commun.dictee_langue())

        # sons : noms français, noms anglais du README et nom de fichier
        for valeur, attendu in (('Glass', 'verre'), ('drop', 'goutte'), ('none', 'aucun'), ('off', 'aucun'),
                                ('marimba.wav', 'marimba'), ('verre', 'verre'), ('', 'windows')):
            ecrire(chemin, {'son': valeur})
            assert ilot.son_choisi() == attendu, (valeur, ilot.son_choisi())
        effacer(chemin)
        assert ilot.son_choisi() == 'marimba', 'son par défaut'
    finally:
        os.environ['ILOT_LANGUE'] = 'fr'
        commun.langue.cache_clear()
        effacer(chemin)


@cas
def journaux_de_sept_jours():
    dossier = commun.JOURNAUX
    os.makedirs(dossier, exist_ok=True)
    vieux, recent, autre = (os.path.join(dossier, n) for n in ('vieux-20000101.log', 'recent.log', 'notes.txt'))
    for chemin in (vieux, recent, autre):
        ecrire(chemin, 'x\n')
    ancien = time.time() - 8 * 86400
    for chemin in (vieux, autre):
        os.utime(chemin, (ancien, ancien))
    commun.purger_journaux()
    assert not os.path.exists(vieux), 'journal de 8 jours gardé'
    assert os.path.exists(recent) and os.path.exists(autre), 'fichier effacé à tort'
    ecrire(vieux, 'x\n')
    os.utime(vieux, (ancien, ancien))
    effacer(os.path.join(dossier, f'neuf-{time.strftime("%Y%m%d")}.log'))
    commun.chemin_journal('neuf')  # premier journal du jour : il fait le ménage
    assert not os.path.exists(vieux), 'le premier journal du jour n’a pas fait le ménage'
    for chemin in (recent, autre):
        effacer(chemin)


# ---------------------------------------------------------------------------
# Installateur
# ---------------------------------------------------------------------------

ATTENDUS = ['pywebview-6.2.1', 'pythonnet-3.2.0', 'Clr_Loader-0.3.1', 'cffi-2.1.1', 'pycparser-3.12',
            'bottle-0.13.4', 'proxy_tools-0.1.0']


@cas
def installateur_versions():
    lib = os.path.join(TMP, 'versions', 'lib')
    for nom in ATTENDUS:
        os.makedirs(os.path.join(lib, nom + '.dist-info'))
    assert installer.ecarts(lib) == ['pythonnet 3.2.1 (trouvé 3.2.0)', 'typing_extensions 4.16.0'], \
        installer.ecarts(lib)
    os.rename(os.path.join(lib, 'pythonnet-3.2.0.dist-info'), os.path.join(lib, 'pythonnet-3.2.1.dist-info'))
    os.makedirs(os.path.join(lib, 'typing_extensions-4.16.0.dist-info'))
    assert installer.ecarts(lib) == [], installer.ecarts(lib)


@cas
def installateur_remplacement():
    base = os.path.join(TMP, 'remplacement')
    lib, nouveau = os.path.join(base, 'lib'), os.path.join(base, 'lib.nouveau')
    ecrire(os.path.join(lib, 'ancien.txt'), 'ancien')
    ecrire(os.path.join(nouveau, 'nouveau.txt'), 'nouveau')
    installer.time = types.SimpleNamespace(sleep=lambda s: None, strftime=time.strftime)
    try:
        ouvert = open(os.path.join(lib, 'ancien.txt'), encoding='utf-8')  # comme une pastille qui tourne
        try:
            assert installer.remplacer(nouveau, lib) is False, 'remplacement d’une lib en cours d’utilisation'
        finally:
            ouvert.close()
        assert os.path.isfile(os.path.join(lib, 'ancien.txt')) and os.path.isdir(nouveau), 'ancienne lib perdue'
        assert installer.remplacer(nouveau, lib) is True
        assert os.path.isfile(os.path.join(lib, 'nouveau.txt')) and not os.path.exists(nouveau)
        restes = [n for n in os.listdir(base) if n.startswith('lib.ancien-')]
        assert not restes, restes
    finally:
        installer.time = time


REGLAGES_A_LA_MAIN = {'hooks': {
    'PreToolUse': [
        {'matcher': 'AskUserQuestion',
         'hooks': [{'type': 'command', 'command': 'python C:/Users/nom/.claude/ilot/ilot.py'}]},
        {'matcher': 'mcp__ccd_turn__wrap_up',
         'hooks': [{'type': 'command', 'command': 'node', 'args': ['C:/Users/nom/.claude/hooks/qcm_ilot_guard.mjs']}]},
    ],
    'Stop': [{'hooks': [{'type': 'command', 'command': 'pythonw',
                         'args': ['C:/Users/nom/.claude/ilot/attente.py']}]}],
    'SessionStart': [{'hooks': [{'type': 'command', 'command': 'echo bonjour'}]}],
}}


@cas
def installateur_config_claude():
    os.environ['CLAUDE_CONFIG_DIR'] = CONFIG_CLAUDE
    try:
        assert installer.config_claude() == CONFIG_CLAUDE
        assert installer.ilot_en_double() == [] and installer.extension_installee() == ('', '')
        assert installer.autres_ilots('') == []
        ecrire(os.path.join(CONFIG_CLAUDE, 'settings.json'), REGLAGES_A_LA_MAIN)
        doubles = installer.ilot_en_double()
        assert len(doubles) == 3, doubles
        assert {d.split(' : ')[0] for d in doubles} == {'PreToolUse', 'Stop'}, doubles
        ecrire(os.path.join(CONFIG_CLAUDE, 'settings.json'), '{pas du json')
        assert installer.ilot_en_double() == []
        installes = os.path.join(CONFIG_CLAUDE, 'plugins', 'installed_plugins.json')
        ancien = {'moonky-ilot@moonky-skills': [{'scope': 'user', 'installPath': 'x', 'version': 'aaaaaaaaaaaa'}],
                  'autre@ailleurs': [{'scope': 'user', 'version': '1'}]}
        ecrire(installes, {'version': 2, 'plugins': ancien})
        assert installer.extension_installee() == ('', ''), installer.extension_installee()
        assert installer.autres_ilots('') == ['moonky-ilot@moonky-skills']
        # retrouvée par son dossier d'installation, quel que soit le nom du catalogue
        ecrire(installes, {'version': 2, 'plugins': dict(ancien, **{'moonky-island@un-catalogue': [
            {'scope': 'user', 'installPath': RACINE + os.sep, 'version': 'abc123def456'},
            {'scope': 'project', 'projectPath': 'C:/projets/demo', 'installPath': 'y', 'version': '0123456789ab'},
        ]})})
        assert installer.extension_installee() == ('moonky-island@un-catalogue',
                                                   'version abc123def456, pour tous les dossiers ; '
                                                   'version 0123456789ab, dans C:/projets/demo'), \
            installer.extension_installee()
        assert installer.autres_ilots('moonky-island@un-catalogue') == ['moonky-ilot@moonky-skills']
        # à défaut de dossier connu, le nom de l'extension suffit
        ecrire(installes, {'version': 2, 'plugins': {
            installer.EXTENSION: [{'scope': 'user', 'installPath': 'z', 'version': '1'}]}})
        assert installer.extension_installee()[0] == installer.EXTENSION
    finally:
        os.environ.pop('CLAUDE_CONFIG_DIR', None)


@cas
def installateur_coupe_circuit():
    def commande(*args, env_plus=None):
        r, _ = lancer(os.path.join(RACINE, 'installer.py'), b'', INSTALLATEUR, env_plus=env_plus, args=args,
                      delai=120)
        return r.returncode, r.stdout.decode('utf-8', 'replace')

    coupe = os.path.join(INSTALLATEUR, 'coupe')
    code, sortie = commande('--couper')
    assert code == 0 and 'Moonky Island coupé' in sortie, sortie
    with open(coupe, encoding='utf-8') as f:
        assert '--on' in f.read()
    code, sortie = commande('--reprendre')
    assert code == 0 and 'Moonky Island remis en marche' in sortie and not os.path.exists(coupe), sortie
    code, sortie = commande('--on')
    assert code == 0 and "Moonky Island n'était pas coupé." in sortie, sortie
    vide = {'CLAUDE_CONFIG_DIR': os.path.join(TMP, 'config-vide')}
    code, sortie = commande('--verifier', env_plus=vide)
    assert code == 1, sortie
    for attendu in ('Bibliothèques : à installer (pywebview 6.2.1',
                    'pas trouvée : claude plugin install moonky-island@moonky-island',
                    'questions de fin de tour oui, langue auto', "L'îlot ne peut pas s'afficher"):
        assert attendu in sortie, (attendu, sortie)
    # en anglais par le réglage « langue »
    reglages = os.path.join(INSTALLATEUR, 'reglages.json')
    ecrire(reglages, {'langue': 'en'})
    try:
        code, sortie = commande('--check', env_plus=dict(vide, ILOT_LANGUE=''))
        assert code == 1, sortie
        for attendu in ('Libraries: to install (pywebview 6.2.1',
                        'not found: claude plugin install moonky-island@moonky-island',
                        'end-of-turn questions yes, language en', 'The island cannot show up'):
            assert attendu in sortie, (attendu, sortie)
        code, sortie = commande('--off', env_plus={'ILOT_LANGUE': ''})
        assert code == 0 and 'Moonky Island is off' in sortie, sortie
        code, sortie = commande('--on', env_plus={'ILOT_LANGUE': ''})
        assert code == 0 and 'Moonky Island is back on' in sortie and not os.path.exists(coupe), sortie
    finally:
        effacer(reglages)
    assert not os.path.exists(os.path.join(INSTALLATEUR, 'lib')), 'la vérification a installé quelque chose'
    code, sortie = commande('--couper', '--reprendre')
    assert code == 2, (code, sortie)


def main():
    resultats = []
    for f in CAS:
        t = time.time()
        try:
            f()
            resultats.append((f.__name__, 'OK', time.time() - t, ''))
        except AssertionError as e:
            resultats.append((f.__name__, 'ÉCHEC', time.time() - t, str(e) or traceback.format_exc()))
        except Exception:  # noqa: BLE001
            resultats.append((f.__name__, 'ERREUR', time.time() - t, traceback.format_exc()))
    for nom, statut, duree, detail in resultats:
        print(f'{statut:6} {nom} ({duree:.1f} s)' + (f'\n       {detail}' if detail else ''))
    print(f'{sum(r[1] == "OK" for r in resultats)} cas sur {len(resultats)} réussis')
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0 if all(r[1] == 'OK' for r in resultats) else 1)


main()
