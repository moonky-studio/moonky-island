# Images du README : l'îlot et la pastille rendus dans Chrome sans fenêtre, avec des données fictives.
# Aucune vraie fenêtre, aucun son, aucun micro : window.pywebview.api est simulé dans la page.
# Il faut Playwright et Pillow (py -3.12-64 -m pip install playwright pillow) et Google Chrome, ou un Chromium installé par Playwright.
# Lancement : py -3.12-64 essais\images_readme.py   (écrit docs\images\*.webp, environ 1 min par langue ; « en » ou « fr » en argument pour une seule)
import io
import json
import os
import sys
import time

from PIL import Image
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SORTIE = os.path.join(RACINE, 'docs', 'images')
CHROME = os.path.join(os.environ.get('PROGRAMFILES', r'C:\Program Files'), r'Google\Chrome\Application\chrome.exe')
LARGEUR, ECHELLE = 880, 2
LENT = 0.1  # vitesse des animations pendant la capture de l'animation (10 fois plus lentes)
IMAGES_S = 30

# ---------------------------------------------------------------------------
# Données fictives
# ---------------------------------------------------------------------------

TEXTES = {
    'en': {
        'principale': {
            'titre': 'Release notes 2.4',
            'questions': [{
                'header': 'Format',
                'question': 'The release notes are ready. How should I share them with the team?',
                'options': [
                    {'label': 'Share link (recommended)', 'description': 'Always up to date, everyone can comment.'},
                    {'label': 'PDF attachment', 'description': 'Fixed, readable offline.'},
                    {'label': 'Post in the team channel', 'description': 'A short summary with a link to the notes.'},
                ],
            }],
        },
        'fin_de_tour': {
            'titre': 'Login redirect fix',
            'questions': [{
                'header': '', 'question': 'Shall I commit and push the fix?',
                'contexte': 'Fixed the redirect loop after sign-in and added two tests. All 48 tests pass. '
                            'Nothing is committed yet.',
                'options': [{'label': 'Yes, push', 'recommande': True}, {'label': 'Not now'}],
            }],
        },
        'dictee': {
            'titre': 'Archive cleanup',
            'questions': [{
                'header': 'Archive', 'multiSelect': True,
                'question': 'Which folders should I move to the archive?',
                'options': [
                    {'label': 'September drafts', 'description': 'None opened in a month.'},
                    {'label': 'Duplicate exports', 'description': '4 files, 3.2 GB.'},
                    {'label': 'Screenshots', 'description': '58 images on the desktop.'},
                ],
            }],
        },
        'pastille': [
            ('Login redirect fix', 'Shall I commit and push the fix?', 2 * 60),
            ('Archive cleanup', 'I need the name of the folder for the duplicate exports.', 23 * 60),
        ],
    },
    'fr': {
        'principale': {
            'titre': 'Notes de version 2.4',
            'questions': [{
                'header': 'Format',
                'question': 'Les notes de version sont prêtes. Comment je les partage avec l\'équipe ?',
                'options': [
                    {'label': 'Lien de partage (recommandé)', 'description': 'Toujours à jour, chacun peut commenter.'},
                    {'label': 'PDF en pièce jointe', 'description': 'Figé, lisible hors ligne.'},
                    {'label': 'Message dans le canal de l\'équipe',
                     'description': 'Un résumé court avec le lien vers les notes.'},
                ],
            }],
        },
        'fin_de_tour': {
            'titre': 'Correction de la redirection',
            'questions': [{
                'header': '', 'question': 'Je fais le commit et je le pousse ?',
                'contexte': 'La boucle de redirection après la connexion est corrigée, avec deux tests en plus. '
                            'Les 48 tests passent. Rien n\'est encore commité.',
                'options': [{'label': 'Oui, pousse', 'recommande': True}, {'label': 'Pas maintenant'}],
            }],
        },
        'dictee': {
            'titre': 'Rangement des archives',
            'questions': [{
                'header': 'Archives', 'multiSelect': True,
                'question': 'Quels dossiers je range dans les archives ?',
                'options': [
                    {'label': 'Brouillons de septembre', 'description': 'Aucun ouvert depuis un mois.'},
                    {'label': 'Exports en double', 'description': '4 fichiers, 3,2 Go.'},
                    {'label': 'Captures d\'écran', 'description': '58 images sur le bureau.'},
                ],
            }],
        },
        'pastille': [
            ('Correction de la redirection', 'Je fais le commit et je le pousse ?', 2 * 60),
            ('Rangement des archives', 'Il me manque le nom du dossier où ranger les exports en double.', 23 * 60),
        ],
    },
}

# ---------------------------------------------------------------------------
# Page : fond d'écran, fenêtre d'application floue en dessous, pont Python simulé
# ---------------------------------------------------------------------------

DECOR = r"""
(() => {
  const css = `
    html, body { background: transparent !important; }
    #decor { position: fixed; inset: 0; z-index: -1; border-radius: 18px; overflow: hidden;
      background:
        radial-gradient(60% 80% at 8% 0%, #f6c6a8 0%, rgba(246,198,168,0) 70%),
        radial-gradient(55% 75% at 100% 10%, #c9c3ef 0%, rgba(201,195,239,0) 70%),
        radial-gradient(70% 90% at 50% 120%, #f2a07f 0%, rgba(242,160,127,0) 70%),
        linear-gradient(160deg, #f7e7dc 0%, #efe0ea 55%, #f3d6c7 100%); }
    #fenetre { position: absolute; left: 56px; right: 56px; top: 92px; bottom: -40px; border-radius: 14px;
      background: rgba(255,255,255,0.72); box-shadow: 0 24px 60px rgba(80,40,30,0.18), 0 0 0 1px rgba(255,255,255,0.6);
      backdrop-filter: blur(20px); }
    #fenetre .barre { height: 40px; border-bottom: 1px solid rgba(0,0,0,0.06); }
    #fenetre .ligne { position: absolute; height: 10px; border-radius: 5px; background: rgba(60,50,60,0.10); }
  `;
  const lignes = [[40, 80, 46], [40, 112, 38], [40, 144, 52], [40, 196, 30], [40, 228, 44], [40, 260, 36],
                  [40, 312, 48], [40, 344, 28], [40, 396, 40], [40, 428, 50], [40, 480, 34], [40, 512, 46]];
  document.addEventListener('DOMContentLoaded', () => {
    const s = document.createElement('style'); s.textContent = css; document.head.append(s);
    const d = document.createElement('div'); d.id = 'decor';
    const f = document.createElement('div'); f.id = 'fenetre';
    f.innerHTML = '<div class="barre"></div>' + lignes.map(([x, y, w]) =>
      `<div class="ligne" style="left:${x}px;top:${y}px;width:${w}%"></div>`).join('');
    d.append(f);
    document.body.prepend(d);
  });
  const rien = () => null;
  window.__niveau = 0;
  window.pywebview = { api: {
    pret: rien, focus: rien, rendre_focus: rien, fin: rien, envoyer: rien, dans_claude: rien,
    ouvrir: rien, ecarter: rien, ecarter_tout: rien, dictee_annuler: rien, dictee_abandonner: rien,
    dictee_debut: () => 'ok', dictee_fin: () => new Promise(() => {}), niveau: () => window.__niveau,
  } };
  if (!window.__differe) window.pywebview.api.zone = rien;
})();
"""


def page_html(nom, donnees):
    with open(os.path.join(RACINE, 'ilot', nom), encoding='utf-8') as f:
        return f.read().replace('__DONNEES__', json.dumps(donnees, ensure_ascii=False).replace('</', '<\\/'))


def ouvrir(navigateur, nom, donnees, differe=False):
    page = navigateur.new_page(viewport={'width': LARGEUR, 'height': 900}, device_scale_factor=ECHELLE)
    if differe:
        page.add_init_script('window.__differe = true;')
    page.add_init_script(DECOR)
    chemin = os.path.join(SORTIE, '_page.html')
    with open(chemin, 'w', encoding='utf-8') as f:
        f.write(page_html(nom, donnees))
    page.goto('file:///' + chemin.replace('\\', '/'))
    return page


def bas_ile(page):
    return page.evaluate("(() => { const r = document.getElementById('ile').getBoundingClientRect(); return r.bottom; })()")


def capture(page, hauteur):
    png = page.screenshot(clip={'x': 0, 'y': 0, 'width': LARGEUR, 'height': hauteur}, omit_background=True)
    return Image.open(io.BytesIO(png)).convert('RGBA')


def coins(image, rayon=18 * ECHELLE):
    """Coins arrondis transparents : le fond fixe s'arrondit à la fenêtre, pas à la découpe."""
    from PIL import ImageDraw
    masque = Image.new('L', image.size, 0)
    ImageDraw.Draw(masque).rounded_rectangle((0, 0, image.size[0] - 1, image.size[1] - 1), rayon, fill=255)
    image.putalpha(Image.composite(image.getchannel('A'), masque, masque))
    return image


def enregistrer(image, nom):
    chemin = os.path.join(SORTIE, nom)
    image.save(chemin, 'WEBP', quality=88, method=6)
    print(f'{nom} : {image.size[0]}x{image.size[1]}, {os.path.getsize(chemin) // 1024} Ko')


def attendre_repos(page, ms=1400):
    page.wait_for_timeout(ms)


# ---------------------------------------------------------------------------
# Images fixes
# ---------------------------------------------------------------------------

def image_question(navigateur, langue, cle, nom, preparer=None, dictee=False):
    t = TEXTES[langue][cle]
    donnees = {'titre': t['titre'], 'questions': t['questions'], 'lien': True, 'demo': False, 'deplie': True,
               'rang': 0, 'dictee': dictee, 'langue': langue}
    page = ouvrir(navigateur, 'ilot.html', donnees)
    attendre_repos(page)
    if preparer:
        preparer(page)
    hauteur = min(900, int(bas_ile(page)) + 64)
    enregistrer(coins(capture(page, hauteur)), nom)
    page.close()


def preparer_dictee(page):
    page.evaluate("ilot.choisir(0, 0, 'souris'); ilot.choisir(0, 1, 'souris');")
    page.wait_for_timeout(400)
    page.evaluate("ilot.basculerDictee(0)")
    # niveau du micro simulé : une voix qui monte, pour que les barres aient du relief
    for niveau in (2, 5, 9, 14, 18, 16, 20, 17):
        page.evaluate(f'window.__niveau = {niveau}')
        page.wait_for_timeout(120)


def image_pastille(navigateur, langue, nom):
    maintenant = time.time()
    entrees = [{'local': f'demo-{i}', 'titre': titre, 'texte': texte, 'depuis': maintenant - age}
               for i, (titre, texte, age) in enumerate(TEXTES[langue]['pastille'], 1)]
    page = ouvrir(navigateur, 'attente.html', {'entrees': entrees, 'rang': 0, 'test': False, 'langue': langue})
    attendre_repos(page)
    page.evaluate('ilot.deplier()')
    attendre_repos(page, 1200)
    hauteur = min(900, int(bas_ile(page)) + 64)
    enregistrer(coins(capture(page, hauteur)), nom)
    page.close()


# ---------------------------------------------------------------------------
# Animation : arrivée, ouverture, choix, envoi
# ---------------------------------------------------------------------------

def animation(navigateur, langue, nom):
    t = TEXTES[langue]['principale']
    donnees = {'titre': t['titre'], 'questions': t['questions'], 'lien': True, 'demo': False, 'deplie': False,
               'rang': 0, 'dictee': False, 'langue': langue}
    page = ouvrir(navigateur, 'ilot.html', donnees, differe=True)
    cdp = page.context.new_cdp_session(page)
    cdp.send('Animation.enable')
    cdp.send('Animation.setPlaybackRate', {'playbackRate': LENT})
    page.wait_for_timeout(300)

    # hauteur de l'image : celle du panneau ouvert, mesurée sur une copie rendue à part
    mesure = ouvrir(navigateur, 'ilot.html', {**donnees, 'deplie': True})
    attendre_repos(mesure)
    hauteur = int(bas_ile(mesure)) + 64
    mesure.close()

    images = []

    def filmer(secondes):
        """Capture à intervalles réguliers de temps réel, soit 1/IMAGES_S s du temps ralenti des animations."""
        pas = 1 / IMAGES_S / LENT
        debut = time.perf_counter()
        for k in range(round(secondes * IMAGES_S)):
            cible = debut + k * pas
            reste = cible - time.perf_counter()
            if reste > 0:
                time.sleep(reste)
            images.append(capture(page, hauteur))

    def tenir(secondes):
        images.extend([images[-1]] * round(secondes * IMAGES_S))

    # écran vide un instant, puis l'île arrive
    images.append(capture(page, hauteur))
    tenir(0.5)
    page.evaluate("window.pywebview.api.zone = () => null; window.dispatchEvent(new Event('pywebviewready'))")
    filmer(1.0)
    tenir(0.9)
    page.evaluate('() => { ilot.deplier(); }')
    filmer(1.0)
    tenir(1.2)
    page.evaluate("() => { ilot.choisir(0, 0, 'souris'); }")
    filmer(0.8)
    tenir(0.9)
    page.evaluate('() => { ilot.envoyer(); }')
    filmer(1.4)
    tenir(1.0)
    page.close()

    images = [coins(i) for i in images]
    chemin = os.path.join(SORTIE, nom)
    images[0].save(chemin, 'WEBP', save_all=True, append_images=images[1:], duration=round(1000 / IMAGES_S),
                   loop=0, quality=80, method=4, minimize_size=True)
    print(f'{nom} : {len(images)} images, {os.path.getsize(chemin) // 1024} Ko')


def main():
    os.makedirs(SORTIE, exist_ok=True)
    with sync_playwright() as p:
        options = {'executable_path': CHROME} if os.path.exists(CHROME) else {}
        navigateur = p.chromium.launch(args=['--mute-audio', '--force-color-profile=srgb'], **options)
        langues = sys.argv[1:] or ['en', 'fr']
        for langue in langues:
            animation(navigateur, langue, f'ilot-{langue}.webp')
            image_question(navigateur, langue, 'fin_de_tour', f'fin-de-tour-{langue}.webp')
            image_question(navigateur, langue, 'dictee', f'dictee-{langue}.webp', preparer_dictee, dictee=True)
            image_pastille(navigateur, langue, f'pastille-{langue}.webp')
        navigateur.close()
    os.remove(os.path.join(SORTIE, '_page.html'))


if __name__ == '__main__':
    main()
