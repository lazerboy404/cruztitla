from __future__ import annotations

import re
import unicodedata


TEXT_REPAIRS = {
    "Tultitl?n": "Tultitl\u00e1n",
    "Tultitl??n": "Tultitl\u00e1n",
    "TULTITL?N": "TULTITL\u00c1N",
    "TULTITL??N": "TULTITL\u00c1N",
    "Tultitl\u00c3\u00a1n": "Tultitl\u00e1n",
    "TULTITL\u00c3\u0081N": "TULTITL\u00c1N",
    "M?x": "M\u00e9x",
    "M??x": "M\u00e9x",
    "M?X": "M\u00c9X",
    "M??X": "M\u00c9X",
    "M\u00c3\u00a9x": "M\u00e9x",
    "M\u00c3\u0089X": "M\u00c9X",
}

SPANISH_DISPLAY_WORD_FIXES = {
    "ACUNA": "ACU\u00d1A",
    "ALVARO": "\u00c1LVARO",
    "ANGEL": "\u00c1NGEL",
    "ANIBAL": "AN\u00cdBAL",
    "BOLANOS": "BOLA\u00d1OS",
    "CARRION": "CARRI\u00d3N",
    "CESAR": "C\u00c9SAR",
    "CORDOBA": "C\u00d3RDOBA",
    "DIAZ": "D\u00cdAZ",
    "DUE\u00d1AS": "DUE\u00d1AS",
    "DUENAS": "DUE\u00d1AS",
    "FELIX": "F\u00c9LIX",
    "GOMEZ": "G\u00d3MEZ",
    "GONZALEZ": "GONZ\u00c1LEZ",
    "GUTIERREZ": "GUTI\u00c9RREZ",
    "HECTOR": "H\u00c9CTOR",
    "HERNANDEZ": "HERN\u00c1NDEZ",
    "IBA\u00d1EZ": "IB\u00c1\u00d1EZ",
    "IBANEZ": "IB\u00c1\u00d1EZ",
    "JESUS": "JES\u00daS",
    "JIMENEZ": "JIM\u00c9NEZ",
    "JOSE": "JOS\u00c9",
    "LEON": "LE\u00d3N",
    "LOPEZ": "L\u00d3PEZ",
    "MARTINEZ": "MART\u00cdNEZ",
    "MEX": "M\u00c9X",
    "MEXICO": "M\u00c9XICO",
    "MUNOZ": "MU\u00d1OZ",
    "NI\u00d1O": "NI\u00d1O",
    "NINO": "NI\u00d1O",
    "NU\u00d1EZ": "N\u00da\u00d1EZ",
    "NUNEZ": "N\u00da\u00d1EZ",
    "OCA\u00d1A": "OCA\u00d1A",
    "OCANA": "OCA\u00d1A",
    "OSCAR": "\u00d3SCAR",
    "PE\u00d1A": "PE\u00d1A",
    "PENA": "PE\u00d1A",
    "PEREZ": "P\u00c9REZ",
    "PI\u00d1A": "PI\u00d1A",
    "PINA": "PI\u00d1A",
    "QUI\u00d1ONES": "QUI\u00d1ONES",
    "QUINONES": "QUI\u00d1ONES",
    "RAMIREZ": "RAM\u00cdREZ",
    "RAUL": "RA\u00daL",
    "RODRIGUEZ": "RODR\u00cdGUEZ",
    "SANCHEZ": "S\u00c1NCHEZ",
    "TULTITLAN": "TULTITL\u00c1N",
    "VALENTIN": "VALENT\u00cdN",
    "VAZQUEZ": "V\u00c1ZQUEZ",
    "VELAZQUEZ": "VEL\u00c1ZQUEZ",
    "VICTOR": "V\u00cdCTOR",
}


def repair_text_encoding(value: object) -> str:
    text = str(value or "")
    if any(marker in text for marker in ("Ã", "Â", "\ufffd")):
        try:
            candidate = text.encode("latin-1").decode("utf-8")
        except UnicodeError:
            candidate = text
        if _text_quality(candidate) >= _text_quality(text):
            text = candidate

    for wrong, right in TEXT_REPAIRS.items():
        text = text.replace(wrong, right)
    return text


def normalize_display_text(value: object) -> str:
    text = repair_text_encoding(value)
    return re.sub(r"[A-Za-z\u00c0-\u024f\u00d1\u00f1]+", _replace_display_word, text)


def normalize_player_name(value: object) -> str:
    text = normalize_display_text(value)
    return " ".join(text.strip().split())


def _replace_display_word(match: re.Match[str]) -> str:
    word = match.group(0)
    key = _word_key(word)
    return SPANISH_DISPLAY_WORD_FIXES.get(key, word)


def _word_key(word: str) -> str:
    normalized = unicodedata.normalize("NFKD", word)
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^A-Z0-9]", "", plain.upper())


def _text_quality(text: str) -> int:
    penalty = sum(text.count(marker) for marker in ("Ã", "Â", "\ufffd", "?"))
    bonus = sum(text.count(char) for char in "ÁÉÍÓÚÜÑáéíóúüñ")
    return bonus - penalty
