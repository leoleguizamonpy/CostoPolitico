"""Utilidades para limpiar nombres, montos y fechas de fuentes paraguayas."""
import hashlib
import re
import unicodedata
from datetime import datetime


def nombre(texto: str) -> str:
    """'Carlos Alberto  Núñez Salinas' -> 'CARLOS ALBERTO NUNEZ SALINAS'."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^A-Za-z ]", " ", texto).upper()
    return re.sub(r"\s+", " ", texto).strip()


def monto(texto) -> int | None:
    """'₲ 5.073.097' / 'Gs. 5.073.097' / '5073097,00' -> 5073097."""
    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        return int(round(texto))
    t = str(texto).strip()
    t = re.sub(r"[^\d.,-]", "", t)
    if not t or not re.search(r"\d", t):
        return None
    # Formato paraguayo: punto = miles, coma = decimales.
    if "," in t:
        t = t.split(",")[0]
    t = t.replace(".", "")
    try:
        return int(t)
    except ValueError:
        return None


_FECHA = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def rango_fechas(texto: str) -> tuple[str | None, str | None]:
    """'29/01/2025 AL 02/02/2025' -> ('2025-01-29', '2025-02-02')."""
    encontradas = _FECHA.findall(texto or "")
    iso = [datetime(int(a), int(m), int(d)).strftime("%Y-%m-%d") for d, m, a in encontradas]
    if not iso:
        return None, None
    return iso[0], iso[-1]


def huella(*partes) -> str:
    return hashlib.sha1("|".join(str(p) for p in partes).encode()).hexdigest()


def ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")
