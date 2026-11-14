"""Ficha de cada legislador en el SILpy: partido, bancada (movimiento) y si es titular o suplente.

https://silpy.congreso.gov.py/web/parlamentario/<ID>  — estructura verificada (noviembre 2026):
  <title>NOMBRES APELLIDOS</title>
  <span title="Tipo">TITULAR [2023-2028]</span>
  <span title="Partido">Asociación Nacional Republicana ANR</span>
  <span class="font-bold"> MIEMBRO </span> de la Bancada
      <span class="font-bold font-italic">BANCADA DE LA ASOCIACIÓN NACIONAL REPUBLICANA ANR - A "HONOR COLORADO"</span>

En la ANR y el PLRA la bancada corresponde al movimiento interno ("A HONOR COLORADO",
"C COLORADO AÑETETÉ", "Verdadero Liberalismo", "Eligio Ayala"…). Se publica el texto oficial de
la bancada; el "movimiento" que muestra la web es solo la parte que sigue al nombre del partido,
sin reinterpretarla. Al Poder Ejecutivo no se le asigna partido: ninguna fuente oficial usada
lo informa.
"""
import re
import time

from bs4 import BeautifulSoup

from .. import normalizar, red

URL_FICHA = "https://silpy.congreso.gov.py/web/parlamentario/{}"


def parsear_ficha(html: str) -> dict:
    sopa = BeautifulSoup(html, "html.parser")

    def por_titulo(t):
        el = sopa.find("span", attrs={"title": t})
        return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else None

    bancada = rol = None
    for span in sopa.find_all("span", class_="font-italic"):
        previo = span.previous_sibling
        if previo and "de la Bancada" in str(previo):
            bancada = re.sub(r"\s+", " ", span.get_text(" ", strip=True))
            rol_el = span.find_previous_sibling("span")
            rol = rol_el.get_text(strip=True).title() if rol_el else None
            break
    titulo = sopa.title.get_text(strip=True) if sopa.title else None
    return {
        "nombre": titulo,
        "partido": por_titulo("Partido"),
        "representante": por_titulo("Tipo"),  # "TITULAR [2023-2028]" / "SUPLENTE [2023-2028]"
        "bancada": bancada,
        "rol_bancada": rol,
    }


def movimiento(bancada: str | None, partido: str | None) -> str | None:
    """Parte de la bancada que sigue al nombre del partido, tal como está escrita:
    'BANCADA DE LA … ANR - A "HONOR COLORADO"' -> 'A "Honor Colorado"';
    'Partido Liberal Radical Autentico (PLRA) "B"' -> 'B'; 'BANCADA INDEPENDIENTE' -> None."""
    if not bancada:
        return None
    partes = re.split(r"\s[-–]\s?", bancada)
    if len(partes) > 1:
        resto = partes[-1]
    elif ")" in bancada:
        resto = bancada.rsplit(")", 1)[1]
    else:
        return None
    resto = resto.strip()
    if len(resto) >= 2 and resto[0] in "\"“" and resto[-1] in "\"”":  # todo entre comillas: "B"
        resto = resto[1:-1].strip()
    if not resto:
        return None
    # Si lo que queda es solo la sigla o el nombre del partido, no es un movimiento
    # (comparando palabras completas: la "B" de una bancada no es la B de "REPUBLICANA").
    p = normalizar.nombre(partido or "")
    r = normalizar.nombre(resto)
    if r == p or r in p.split()[-1:] or p.endswith(" " + r):
        return None
    return _capitalizar(resto)


SIGLAS = {"PL", "ANR", "PLRA", "PPQ", "PEN", "CN", "PPS", "PDP", "HC"}


def _capitalizar(texto: str) -> str:
    """'A "HONOR COLORADO"' -> 'A "Honor Colorado"'; 'YO CREO' -> 'Yo Creo'; deja letras sueltas y siglas."""
    def palabra(m):
        w = m.group(0)
        return w.upper() if len(w) == 1 or w.upper() in SIGLAS else w.capitalize()
    return re.sub(r"[^\W\d_]+", palabra, texto)


def guardar_ficha(con, silpy_id: str, ficha: dict) -> None:
    con.execute(
        "UPDATE personas SET partido = COALESCE(?, partido), bancada = ?, rol_bancada = ?,"
        " representante = ? WHERE silpy_id = ?",
        (ficha.get("partido"), ficha.get("bancada"), ficha.get("rol_bancada"),
         ficha.get("representante"), silpy_id))


def actualizar_fichas(con, pausa: float = 0.4, sesion=None, solo_faltantes: bool = False) -> dict:
    """Recorre las personas con ID del SILpy y actualiza partido, bancada y tipo."""
    import requests

    s = sesion or red.sesion()
    sql = "SELECT silpy_id FROM personas WHERE silpy_id IS NOT NULL"
    if solo_faltantes:
        sql += " AND bancada IS NULL"
    ok = err = 0
    for (sid,) in con.execute(sql).fetchall():
        try:
            r = s.get(URL_FICHA.format(sid), timeout=60)
            r.raise_for_status()
            guardar_ficha(con, sid, parsear_ficha(r.text))
            ok += 1
        except requests.RequestException:
            err += 1
        time.sleep(pausa)
    con.commit()
    return {"fichas": ok, "errores": err}
