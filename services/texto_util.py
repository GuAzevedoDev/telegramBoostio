import re
import unicodedata

URL_RE = re.compile(r"https?://\S+", re.I)

_EMOJI_RE = re.compile(
    r"["
    r"\U0001F000-\U0001FAFF"  # emojis, símbolos, bandeiras
    r"\U000E0000-\U000E007F"  # tags de bandeiras
    r"\u2190-\u21FF"          # setas
    r"\u2300-\u23FF"          # símbolos técnicos
    r"\u25A0-\u25FF"          # formas geométricas
    r"\u2600-\u27BF"          # símbolos diversos e dingbats
    r"\u2900-\u297F"
    r"\u2B00-\u2BFF"          # setas/estrelas
    r"\u3030\u303D\u3297\u3299"
    r"\u00A9\u00AE\u2122"
    r"\u200D\u20E3\uFE0E\uFE0F"  # ZWJ, keycap, seletores de variação
    r"]+"
)


def remover_emojis(texto: str) -> str:
    return _EMOJI_RE.sub("", texto)


def sem_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
