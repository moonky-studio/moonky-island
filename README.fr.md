# Moonky Island

Une extension Claude Code pour Windows. Quand Claude vous pose une question avec l'outil
AskUserQuestion, elle s'affiche en haut de l'écran, au-dessus de toutes les applications, et vous
répondez d'un clic sans revenir dans Claude. Une pastille signale aussi les sessions qui ont fini leur
tour et attendent votre réponse.

[English version](README.md)

## Ce que fait l'extension

- **L'îlot.** Les questions posées avec AskUserQuestion apparaissent en haut de l'écran, sans prendre
  le clavier. Vous choisissez une option, tapez votre propre réponse, ou cliquez sur « Répondre dans
  Claude » pour répondre dans la discussion comme avant. Sans réponse au bout de 9 minutes, la question
  repart dans la discussion et la pastille prend le relais.
- **La pastille.** Quand une session de l'appli Claude finit son tour sur une question, une pastille
  montre le titre de la session et ce qu'elle attend. Un clic ouvre la discussion. Elle se tait si vous
  avez déjà cette session sous les yeux.
- **Un rappel au démarrage.** Chaque session reçoit une consigne : poser vos décisions avec
  AskUserQuestion, en 2 à 4 options, sa recommandation en premier. Les questions ouvertes (un nom, un
  montant, un texte) restent dans la discussion.
- **La dictée, facultative.** Un micro dans l'îlot, transcrit sur votre PC par Whisper.

Si quelque chose manque ou plante, l'extension s'efface et Claude pose ses questions dans la
discussion, comme sans elle.

## Ce qu'il faut sur le PC

- Windows 11 (Windows 10 n'a pas été essayé).
- Python 3.12 64 bits, installé depuis [python.org](https://www.python.org/downloads/windows/) avec la
  case « py launcher » cochée (elle l'est par défaut), pas la version du Microsoft Store. Il peut
  cohabiter avec une autre version. Dans PowerShell, `py -3.12-64 --version` doit répondre
  `Python 3.12.x`.
- WebView2, présent d'office sous Windows 11. Sinon, installer l'Evergreen Bootstrapper de
  [Microsoft](https://developer.microsoft.com/microsoft-edge/webview2/).
- Claude Code. L'îlot marche partout où Claude Code lance des hooks ; la pastille demande l'appli
  Claude (onglet Code). Écrit et essayé avec Claude Code 2.1.296 et 2.1.317.

## Installer

1. Ajouter le catalogue et installer l'extension pour tout votre compte :

   ```powershell
   claude plugin marketplace add moonky-studio/moonky-island
   claude plugin install moonky-island@moonky-island --scope user
   ```

2. Terminer l'installation sur ce PC (environ 10 secondes, 7 Mo à télécharger). Soit vous ouvrez une
   nouvelle session et demandez à Claude de « terminer l'installation de Moonky Island » (le rappel de
   démarrage lui donne la commande), soit, dans PowerShell :

   ```powershell
   $ilot = Join-Path ((Get-Content "$env:USERPROFILE\.claude\plugins\installed_plugins.json" -Raw -Encoding UTF8 | ConvertFrom-Json).plugins.'moonky-island@moonky-island' | Sort-Object lastUpdated | Select-Object -Last 1).installPath 'installer.py'
   py -3.12-64 $ilot
   ```

   L'installateur vérifie Python et WebView2, installe pywebview et pythonnet dans
   `%LOCALAPPDATA%\moonky-ilot`, crée les réglages et finit par un bilan. Le relancer ne casse rien :
   ce qui est déjà en place est gardé.
3. Ouvrir une nouvelle session, car celles qui étaient déjà ouvertes n'ont pas les hooks de l'extension.
4. Pour voir l'îlot sans attendre une vraie question, lancer la démo que l'installateur affiche à la fin
   (`ilot\ilot.py --demo`, ou `--deplie` pour l'ouvrir sur les questions). Rien n'est envoyé à Claude.

`py -3.12-64 $ilot --verifier` dit à tout moment ce qui est en place et ce qui manque, sans rien
changer.

## Réglages

Dans `%LOCALAPPDATA%\moonky-ilot\reglages.json`, relu à chaque question, donc sans redémarrage.

| Réglage | Valeurs | Par défaut |
|---|---|---|
| `son` | `"marimba"`, `"verre"`, `"goutte"`, `"windows"` (le son de Windows) ou `"aucun"` | `"marimba"` |
| `langue` | `"auto"` (suit Windows : français si Windows est en français, anglais sinon), `"fr"` ou `"en"` | `"auto"` |
| `dictee` | `true` pour avoir le micro dans l'îlot (voir plus bas) | `false` |
| `dictee_langue` | `"auto"`, ou un code de langue comme `"fr"`, `"en"`, `"de"`. Avec `"auto"`, le français si l'interface est en français, sinon Whisper reconnaît la langue | `"auto"` |
| `pastille` | `true`, `false` (jamais de pastille) ou `"observation"` (rien ne s'affiche, le journal note ce qui l'aurait été) | `true` |
| `pastille_plein_ecran` | `true` : la pastille passe même pendant un plein écran ou une présentation | `false` |
| `garde_fou` | `true` : voir « Ce que font les hooks » plus bas. Appli Claude seulement | `false` |
| `whisper_python`, `whisper_modele` | chemins d'un Whisper déjà installé ailleurs ; vides, l'îlot prend celui de `--whisper` | vides |

Le dossier de données garde l'ancien nom de l'extension, `moonky-ilot`.

## Dictée

`py -3.12-64 $ilot --whisper` installe faster-whisper et le modèle
[mobiuslabsgmbh/faster-whisper-large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo)
dans le dossier de données, puis active la dictée : environ 1,8 Go à télécharger, 2 Go sur le disque,
5 à 20 minutes. Avec une carte NVIDIA, CUDA 12 et cuDNN 9, la transcription passe par la carte
graphique ; sinon par le processeur, plus lent. Le son ne quitte jamais le PC.

Le micro reste caché tant que la dictée n'est pas activée ou que Whisper et son modèle manquent.

## Ce que font les hooks

| Hook | Script | Rôle |
|---|---|---|
| SessionStart | `ilot/rappel.py` | Ajoute le rappel au contexte de la session. Si l'îlot ne peut pas encore s'afficher, donne plutôt à Claude la commande qui termine l'installation. |
| PreToolUse sur AskUserQuestion | `ilot/ilot.py` | Affiche les questions et rend vos réponses comme réponses de l'outil. « Répondre dans Claude » ou le délai de 9 minutes laissent la question passer dans la discussion. |
| PreToolUse sur `mcp__ccd_turn__wrap_up` | `ilot/garde_qcm.py` | Ne fait rien tant que `garde_fou` ne vaut pas `true`. Ensuite, quand Claude met une décision dans le résumé de fin de tour de l'appli avec seulement des boutons de réponse, il le refuse une fois et le renvoie vers AskUserQuestion. Si Claude insiste, il laisse passer. |
| Stop | `ilot/attente.py` | Lance un guetteur détaché et rend la main aussitôt, sans rien écrire. Le guetteur montre la pastille si la session a fini son tour en vous attendant. |

## Couper, mettre à jour, désinstaller

- Couper sans désinstaller : `py -3.12-64 $ilot --couper`. Les questions restent dans la discussion,
  sans îlot, pastille ni garde-fou. `--reprendre` remet tout en marche. La coupure tient dans le
  fichier `%LOCALAPPDATA%\moonky-ilot\coupe` : le supprimer revient au même.
  `claude plugin disable moonky-island@moonky-island` (puis `enable`) marche aussi, pour les sessions
  ouvertes après la commande.
- Mise à jour : Claude Code ne met pas à jour les catalogues tiers de lui-même. Lancer
  `claude plugin marketplace update moonky-island`, puis
  `claude plugin update moonky-island@moonky-island`, relancer l'installateur (il ne retélécharge les
  bibliothèques que si leurs versions ont changé) et ouvrir une nouvelle session.
- Désinstallation : `claude plugin uninstall moonky-island@moonky-island`, puis supprimer
  `%LOCALAPPDATA%\moonky-ilot`.

## Ce que l'extension garde sur le PC

Rien n'est envoyé sur Internet. Seul l'installateur télécharge : les bibliothèques depuis PyPI et, avec
`--whisper`, le modèle depuis Hugging Face.

Tout est dans `%LOCALAPPDATA%\moonky-ilot`, jamais dans le dossier de l'extension, qui est remplacé à
chaque mise à jour : les bibliothèques, les réglages, la coupure, Whisper s'il est installé, et des
journaux effacés au bout de 7 jours. Les journaux notent les titres des sessions et les étapes de
l'îlot ; en mode `"observation"`, aussi le début de ce que la pastille aurait affiché. Vos réponses n'y
sont pas, et les enregistrements de dictée sont effacés dès qu'ils sont transcrits.

## Limites connues

- L'îlot passe au-dessus de tout, y compris pendant un partage d'écran : en réunion, la question se
  voit. La pastille attend la fin d'un plein écran, d'une présentation ou d'un écran verrouillé, mais
  pas celle d'un partage d'écran ordinaire.
- La pastille lit les fiches de session de l'appli Claude (`%APPDATA%\Claude\claude-code-sessions`), un
  format interne que l'appli ne documente pas. S'il change, la pastille se tait ; l'îlot continue.
- Le clic sur la pastille passe par un lien interne de l'appli (`claude://claude.ai/epitaxy/...`). S'il
  change, le clic n'amène plus à la bonne session.
- La pastille ne signale ni les demandes d'autorisation ni la validation d'un plan : Claude Code ne
  lance pas le hook de fin de tour à ce moment-là.
- L'appli Claude coupe une session restée environ 16 minutes sans signe de vie, et une question qui
  attend dans l'îlot compte comme du silence. D'où les 9 minutes : si l'appli raccourcit ce délai, il
  faudra baisser `DELAI_MAX` dans `ilot/ilot.py`.
- Le nouveau gestionnaire d'installation de Python (Python install manager) n'a pas été essayé. S'il
  remplace `py`, vérifier que `py -3.12-64 --version` répond toujours.
- Pas de Mac ni de Linux. Les scripts n'y font rien, mais `py.exe` y manque : Claude Code signalerait
  une erreur de hook (sans blocage) à chaque début de session et à chaque fin de tour.

## Pour qui modifie l'extension

Le code, les commentaires et les journaux sont en français. Les essais, depuis le dossier de
l'extension :

```powershell
py -3.12-64 essais\essai_extension.py
py -3.12-64 essais\essai_dictee.py
```

Ils posent eux-mêmes `ILOT_ESSAI=1` (ni son, ni micro, ni Whisper), travaillent dans un dossier
temporaire, n'ouvrent aucune fenêtre et sortent avec le code 1 si un cas échoue. Moins d'une
demi-minute chacun.

Les trois sons sont fabriqués par synthèse par `ilot/sons/fabriquer_sons.py` (il faut numpy et scipy),
qui écrit les mêmes fichiers à chaque lancement.

## Licence

MIT, voir [LICENSE](LICENSE). Fourni tel quel, sans support : les issues et pull requests peuvent rester
sans réponse.

Claude est une marque d'Anthropic. Ce projet n'est pas affilié à Anthropic.
