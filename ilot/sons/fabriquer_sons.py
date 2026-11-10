"""Sons de notification de l'îlot, fabriqués par synthèse (aucun échantillon repris ailleurs).

    python fabriquer_sons.py              écrit verre.wav, goutte.wav et marimba.wav à côté de ce fichier
    python fabriquer_sons.py --mesurer F  donne la durée, le pic et la sonie d'un ou plusieurs WAV

48 kHz, 16 bits, stéréo. Les mêmes fichiers à chaque lancement (graines fixes). Volume réglé par
SONIE_CIBLE, à comparer au son « Astérisque » de Windows (Windows Background.wav, -16,9 LUFS).
Le son joué par l'îlot est celui du réglage « son » de reglages.json (voir son_choisi et
signal_sonore dans ilot.py). Demande numpy et scipy, qui ne servent qu'ici.
"""
import os
import sys
import wave

import numpy as np
from scipy import signal

SR = 48000
ICI = os.path.dirname(os.path.abspath(__file__))
SONIE_CIBLE = -19.0  # sonie maximale sur 400 ms (LUFS) : 2 dB sous le son Windows (-16,9)


# ---------------------------------------------------------------- mesure

def _ponderation_k(sr):
    """Filtres de la pondération K (UIT-R BS.1770), mêmes formules que pyloudnorm."""
    def biquad(sorte, gain, q, fc):
        a_ = 10 ** (gain / 40)
        w0 = 2 * np.pi * fc / sr
        alpha = np.sin(w0) / (2 * q)
        c = np.cos(w0)
        if sorte == 'plateau':
            b = [a_ * ((a_ + 1) + (a_ - 1) * c + 2 * np.sqrt(a_) * alpha),
                 -2 * a_ * ((a_ - 1) + (a_ + 1) * c),
                 a_ * ((a_ + 1) + (a_ - 1) * c - 2 * np.sqrt(a_) * alpha)]
            a = [(a_ + 1) - (a_ - 1) * c + 2 * np.sqrt(a_) * alpha,
                 2 * ((a_ - 1) - (a_ + 1) * c),
                 (a_ + 1) - (a_ - 1) * c - 2 * np.sqrt(a_) * alpha]
        else:
            b = [(1 + c) / 2, -(1 + c), (1 + c) / 2]
            a = [1 + alpha, -2 * c, 1 - alpha]
        return np.array(b) / a[0], np.array(a) / a[0]
    return [biquad('plateau', 4.0, 1 / np.sqrt(2), 1500.0), biquad('passe-haut', 0.0, 0.5, 38.0)]


def sonie_max(x, sr=SR):
    """Sonie maximale sur des fenêtres de 400 ms, en LUFS ; x a la forme (échantillons, canaux)."""
    y = np.asarray(x, dtype=float)
    for b, a in _ponderation_k(sr):
        y = signal.lfilter(b, a, y, axis=0)
    n, pas = int(0.4 * sr), int(0.05 * sr)
    if len(y) < n:
        y = np.vstack([y, np.zeros((n - len(y), y.shape[1]))])
    meilleure = -np.inf
    for i in range(0, len(y) - n + 1, pas):
        puissance = np.sum(np.mean(y[i:i + n] ** 2, axis=0))
        meilleure = max(meilleure, -0.691 + 10 * np.log10(puissance + 1e-20))
    return meilleure


def pic_vrai(x):
    """Pic après suréchantillonnage par 4 (dBFS), pour ne pas rater un pic entre deux échantillons."""
    return 20 * np.log10(np.max(np.abs(signal.resample_poly(x, 4, 1, axis=0))) + 1e-12)


def lire(chemin):
    with wave.open(chemin, 'rb') as w:
        sr, canaux, largeur = w.getframerate(), w.getnchannels(), w.getsampwidth()
        brut = w.readframes(w.getnframes())
    if largeur != 2:
        raise SystemExit(f'{chemin} : seuls les WAV 16 bits sont lus ici')
    x = np.frombuffer(brut, '<i2').reshape(-1, canaux) / 32768.0
    return x, sr


def decrire(x, sr):
    return (f'{len(x) / sr:4.2f} s, pic {pic_vrai(x):6.1f} dBFS, sonie max {sonie_max(x, sr):6.1f} LUFS, '
            f'{sr} Hz, {x.shape[1]} canal(aux)')


# ---------------------------------------------------------------- synthèse

def temps(duree):
    return np.arange(int(round(duree * SR))) / SR


def montee(t, duree):
    """Attaque en demi-cosinus : sans clic, sans mollesse."""
    return 0.5 - 0.5 * np.cos(np.pi * np.clip(t / duree, 0, 1))


def relache(s, duree):
    """Fondu de fin en demi-cosinus sur les dernières secondes : la note s'éteint sans coupure."""
    n = int(round(duree * SR))
    s[-n:] *= 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, n))
    return s


def sinus(f, t, phase=0.0):
    return np.sin(2 * np.pi * f * t + phase)


def note_verre(f):
    """Verre effleuré : un mode principal dédoublé (léger frémissement), deux modes aigus qui s'éteignent vite."""
    t = temps(1.6)
    s = (0.82 * sinus(f, t) * np.exp(-t / 0.40)
         + 0.18 * sinus(f + 1.6, t, 0.7) * np.exp(-t / 0.36)
         + 0.10 * sinus(f * 2.756, t, 1.1) * np.exp(-t / 0.15)
         + 0.025 * sinus(f * 5.404, t, 2.3) * np.exp(-t / 0.05))
    return relache(s * montee(t, 0.004), 0.6)


def goutte(f0, hausse, tau):
    """Goutte d'eau : un ton pur dont la hauteur monte un peu, comme une bulle qui se referme."""
    t = temps(0.6)
    f = f0 * (1 + hausse * (1 - np.exp(-t / 0.035)))
    phase = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(phase) + 0.05 * np.sin(2 * phase + 0.4)
    return relache(s * montee(t, 0.003) * np.exp(-t / tau), 0.1)


def note_marimba(f):
    """Lame de bois frappée par une mailloche douce : fondamental, partiels accordés à 4 et 10 fois."""
    t = temps(1.4)
    tau = 0.42 * np.sqrt(523.25 / f)
    s = sinus(f, t) * np.exp(-t / tau)
    for rapport, amp, part in ((3.99, 0.20, 0.20), (9.85, 0.045, 0.07)):
        if f * rapport < 9000:
            s += amp * sinus(f * rapport, t, 0.3 * rapport) * np.exp(-t / (tau * part))
    rng = np.random.default_rng(int(f))
    n = int(0.004 * SR)
    contact = signal.lfilter(*signal.butter(2, 2500, fs=SR), rng.standard_normal(n) * np.hanning(n))
    s[:n] += 0.04 * contact
    return relache(s * montee(t, 0.0025), 0.5)


def poser(sortie, son, debut, gain, pan):
    """Place un son dans la sortie stéréo (panoramique à puissance constante, pan de -1 à 1)."""
    i = int(round(debut * SR))
    angle = (pan + 1) * np.pi / 4
    sortie[i:i + len(son), 0] += son * gain * np.cos(angle)
    sortie[i:i + len(son), 1] += son * gain * np.sin(angle)


def salle(graine, duree=1.4, rt_grave=0.9, rt_aigu=0.4):
    """Réponse d'une petite salle : bruit filtré, aigus qui s'éteignent plus vite que les graves."""
    rng = np.random.default_rng(graine)
    n = int(duree * SR)
    t = np.arange(n) / SR
    fr = np.fft.rfftfreq(n, 1 / SR)
    passe_bas = 1 / np.sqrt(1 + (fr / 2500) ** 4)
    sans_graves = 1 / np.sqrt(1 + (300 / np.maximum(fr, 1)) ** 4)
    bruit = np.fft.rfft(rng.standard_normal(n))
    graves = np.fft.irfft(bruit * passe_bas * sans_graves, n)
    aigus = np.fft.irfft(bruit * np.sqrt(np.clip(1 - passe_bas ** 2, 0, 1)) * sans_graves, n)
    k = np.log(1000)  # 60 dB
    reponse = (graves * np.exp(-k * t / rt_grave) + aigus * np.exp(-k * t / rt_aigu)) * montee(t, 0.02)
    reponse = np.concatenate([np.zeros(int(0.012 * SR)), reponse])
    return reponse / np.sqrt(np.sum(reponse ** 2))


def convoluer(x, h):
    n = len(x) + len(h) - 1
    taille = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, taille) * np.fft.rfft(h, taille), taille)[:n]


def finir(sec, reverb):
    """Salle, filtre doux, queue coupée sous -55 dB puis fondue, volume calé sur SONIE_CIBLE."""
    mono = sec.mean(axis=1)
    g, d = salle(11), salle(23)
    sortie = np.zeros((len(sec) + len(g) - 1, 2))
    sortie[:len(sec)] += sec
    sortie[:, 0] += reverb * convoluer(mono, g)
    sortie[:, 1] += reverb * convoluer(mono, d)
    sortie = signal.sosfilt(signal.butter(2, [120, 10000], btype='bandpass', fs=SR, output='sos'), sortie, axis=0)
    niveau = np.max(np.abs(sortie), axis=1)
    fin = int(np.nonzero(niveau > np.max(niveau) * 10 ** (-55 / 20))[0][-1]) + int(0.02 * SR)
    sortie = sortie[:fin]
    fondu = int(0.08 * SR)
    sortie[-fondu:] *= (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, fondu)))[:, None]
    sortie *= 10 ** ((SONIE_CIBLE - sonie_max(sortie)) / 20)
    pic = pic_vrai(sortie)
    if pic > -1.0:
        sortie *= 10 ** ((-1.0 - pic) / 20)
    return sortie


def verre():
    sec = np.zeros((int(2.0 * SR), 2))
    poser(sec, note_verre(783.99), 0.000, 0.78, -0.18)   # sol
    poser(sec, note_verre(1174.66), 0.110, 1.00, 0.18)   # ré, une quinte au-dessus
    return finir(sec, 0.30)


def goutte_double():
    sec = np.zeros((int(1.2 * SR), 2))
    poser(sec, goutte(660.0, 0.40, 0.070), 0.000, 1.00, -0.10)
    poser(sec, goutte(990.0, 0.25, 0.055), 0.125, 0.50, 0.15)
    return finir(sec, 0.32)


def marimba():
    sec = np.zeros((int(2.0 * SR), 2))
    poser(sec, note_marimba(659.26), 0.000, 0.78, -0.22)   # mi
    poser(sec, note_marimba(783.99), 0.078, 0.86, 0.00)    # sol
    poser(sec, note_marimba(1046.50), 0.156, 1.00, 0.22)   # do, l'accord se pose
    return finir(sec, 0.22)


def ecrire(nom, x):
    rng = np.random.default_rng(7)
    tremblement = rng.random(x.shape) - rng.random(x.shape)  # dither triangulaire de ±1 bit
    y = np.clip(np.round(x * 32767 + tremblement), -32768, 32767).astype('<i2')
    chemin = os.path.join(ICI, nom)
    with wave.open(chemin, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(y.tobytes())
    return chemin


def main():
    if len(sys.argv) > 2 and sys.argv[1] == '--mesurer':
        for chemin in sys.argv[2:]:
            print(os.path.basename(chemin), ':', decrire(*lire(chemin)))
        return
    for nom, fabrique in (('verre.wav', verre), ('goutte.wav', goutte_double), ('marimba.wav', marimba)):
        chemin = ecrire(nom, fabrique())
        print(nom, ':', decrire(*lire(chemin)))


if __name__ == '__main__':
    main()
