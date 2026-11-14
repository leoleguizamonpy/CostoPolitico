"""Cámara de Diputados: nómina oficial de diputados.

Estructura verificada (noviembre 2026):

1. Nómina alfabética — https://diputados.gov.py/diputados/nomina-alfabetica
   Tabla con N° | NOMBRE DEL DIPUTADO | PARTIDO. El nombre viene en mayúsculas y en orden
   "APELLIDOS NOMBRES" SIN separador ("ABED DE ZACARIAS MARIA ROCIO"), casi siempre con
   enlace a silpy.congreso.gov.py/parlamentario/<ID>.

2. Ficha del SILpy — https://silpy.congreso.gov.py/web/parlamentario/<ID>
   El <title> trae el nombre en orden natural "NOMBRES APELLIDOS"
   ("MARÍA ROCÍO ABED DE ZACARÍAS"), a veces con agregados ("(BILLY)", usuario de redes).

Comparando ambos órdenes se obtiene el corte exacto entre apellidos y nombres, necesario
para cruzar nombres cortos ("Rocío Abed") en las listas de viáticos. Si no hay ficha, se
estima con la convención de dos apellidos y queda marcado.

Los viáticos de Diputados se importan con viaticos.importar_pdf_diputados (PDF mensual).
"""
import re
import time

from bs4 import BeautifulSoup

from .. import normalizar, personas, red

URL_NOMINA = "https://diputados.gov.py/diputados/nomina-alfabetica"
URL_SILPY = "https://silpy.congreso.gov.py/web/parlamentario/{}"
_SILPY_ID = re.compile(r"parlamentario/(\d+)")
# Partículas que forman parte de un apellido compuesto: "DE ZACARIAS", "VDA DE PEÑA", "DA SILVA".
_PARTICULAS = {"DE", "DEL", "LA", "LAS", "LOS", "VDA", "DA", "DOS", "Y"}


def parsear_nomina(html: str) -> list[dict]:
    sopa = BeautifulSoup(html, "html.parser")
    diputados = []
    for fila in sopa.select("table tr"):
        celdas = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in fila.find_all("td")]
        if len(celdas) < 3 or not celdas[0].isdigit() or not celdas[1]:
            continue
        a = fila.find("a", href=_SILPY_ID)
        diputados.append({
            "numero": int(celdas[0]),
            "silpy_id": _SILPY_ID.search(a["href"]).group(1) if a else None,
            "nombre_crudo": celdas[1],
            "partido": celdas[2] or None,
        })
    return diputados


def titulo_silpy(html: str) -> str | None:
    m = re.search(r"<title>([^<]*)</title>", html, re.IGNORECASE)
    return m.group(1).strip() if m else None


def separar_nombre(crudo: str, nombre_silpy: str | None = None) -> tuple[str, str, str]:
    """'ABED DE ZACARIAS MARIA ROCIO' + 'MARÍA ROCÍO ABED DE ZACARÍAS'
    -> ('ABED DE ZACARIAS', 'MARIA ROCIO', 'silpy')."""
    tokens = re.findall(r"[^\W\d_]+", crudo)  # misma división en palabras que normalizar.nombre
    norm = [normalizar.nombre(t) for t in tokens]
    if nombre_silpy:
        silpy = normalizar.nombre(nombre_silpy).split()
        for k in range(1, len(norm)):
            apellidos, nombres = norm[:k], norm[k:]
            empieza = silpy[:len(nombres)] == nombres
            resto = silpy[len(nombres):]
            contiene = any(resto[i:i + k] == apellidos for i in range(len(resto) - k + 1))
            if empieza and contiene:
                return " ".join(tokens[:k]), " ".join(tokens[k:]), "silpy"
    # Estimación: dos apellidos (cada uno con sus partículas: "DA SILVA", "DE ALLIANA"),
    # dejando al menos una palabra para el nombre.
    k = 0
    for _ in range(2):
        j = k
        while j < len(norm) and norm[j] in _PARTICULAS:
            j += 1
        if j + 1 >= len(norm):  # no quedaría nombre de pila
            break
        k = j + 1
    k = max(k, 1)
    return " ".join(tokens[:k]), " ".join(tokens[k:]), "estimado"


def importar_nomina(con, html: str, titulos: dict[str, str] | None = None) -> dict:
    """`titulos`: silpy_id -> nombre de la ficha del SILpy (ver descargar_nomina)."""
    titulos = titulos or {}
    stats = {"diputados": 0, "corte_silpy": 0, "corte_estimado": 0}
    for d in parsear_nomina(html):
        apellidos, nombres, metodo = separar_nombre(d["nombre_crudo"], titulos.get(d["silpy_id"] or ""))
        personas.guardar(
            con,
            nombre_completo=f"{nombres} {apellidos}",
            nombres=nombres.title(),
            apellidos=apellidos.title(),
            silpy_id=d["silpy_id"],
            partido=d["partido"],
            cargo="Diputado/a",
            poder="legislativo",
            institucion="Cámara de Diputados",
        )
        stats["diputados"] += 1
        stats[f"corte_{metodo}"] += 1
    con.commit()
    return stats


def descargar_nomina(con, pausa: float = 0.5, sesion=None) -> dict:
    import requests

    s = sesion or red.sesion()
    r = s.get(URL_NOMINA, timeout=60)
    r.raise_for_status()
    html = r.text
    from .silpy import guardar_ficha, parsear_ficha

    titulos, fichas = {}, {}
    for d in parsear_nomina(html):
        if not d["silpy_id"]:
            continue
        try:
            f = s.get(URL_SILPY.format(d["silpy_id"]), timeout=60)
            f.raise_for_status()
            fichas[d["silpy_id"]] = ficha = parsear_ficha(f.text)
            titulos[d["silpy_id"]] = ficha["nombre"]
        except requests.RequestException:
            pass  # sin ficha: el corte se estima y queda marcado
        time.sleep(pausa)
    res = importar_nomina(con, html, titulos)
    for sid, ficha in fichas.items():  # partido, bancada y tipo (titular/suplente)
        guardar_ficha(con, sid, ficha)
    con.commit()
    return res


# ---------- viáticos: PDF mensual "VIAJES OFICIALES DE MISIONES PARLAMENTARIAS" ----------
# Se listan en https://diputados.gov.py/transparencia/ley-5189 (tabla Fecha | Título | Archivo,
# paginada con ?page=N y con buscador ?search=). Hay dos tipos de documento con nombre parecido:
# "VIAJES OFICIALES ..." trae la tabla con montos; "INFORME DE VIAJES ..." son los informes
# narrativos de cada misión (sin tabla de montos) y se omiten.

URL_LEY_5189 = "https://diputados.gov.py/transparencia/ley-5189"


def parsear_documentos(html: str) -> list[dict]:
    sopa = BeautifulSoup(html, "html.parser")
    docs = []
    for fila in sopa.select("tr"):
        celdas = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in fila.find_all("td")]
        a = fila.find("a", href=True)
        if len(celdas) >= 2 and a and a["href"].lower().endswith(".pdf"):
            docs.append({"fecha": celdas[0], "titulo": celdas[1], "url": a["href"]})
    return docs


def es_planilla_de_viaticos(titulo: str) -> bool:
    t = normalizar.nombre(titulo)
    return "MISIONES PARLAMENTARIAS" in t and not t.startswith("INFORME")


def anho_documento(doc: dict) -> int | None:
    m = re.search(r"20\d\d", doc["titulo"]) or re.search(r"/(\d\d)$", doc["fecha"])
    if not m:
        return None
    v = m.group(0) if m.re.pattern.startswith("20") else "20" + m.group(1)
    return int(v)


def descargar_viaticos(con, desde_anho: int = 2023, pausa: float = 0.7, sesion=None,
                       carpeta=None) -> dict:
    """Recorre el listado de la Ley 5189, baja cada planilla mensual de viáticos y la importa."""
    import tempfile
    from pathlib import Path

    import requests
    from requests.utils import requote_uri

    from .viaticos import importar_pdf_diputados

    s = sesion or red.sesion()
    carpeta = Path(carpeta or tempfile.mkdtemp(prefix="diputados_"))
    carpeta.mkdir(parents=True, exist_ok=True)
    total = {"documentos": 0, "nueva": 0, "repetida": 0, "posible_duplicado": 0, "sin_asignar": 0, "invalida": 0}
    pagina, vistos = 1, set()
    while True:
        r = s.get(URL_LEY_5189, params={"search": "MISIONES PARLAMENTARIAS", "page": pagina}, timeout=60)
        r.raise_for_status()
        docs = parsear_documentos(r.text)
        nuevos = [d for d in docs if d["url"] not in vistos]
        if not nuevos:
            break
        for d in nuevos:
            vistos.add(d["url"])
            anho = anho_documento(d)
            if not es_planilla_de_viaticos(d["titulo"]) or (anho and anho < desde_anho):
                continue
            url = requote_uri(d["url"])
            pdf = s.get(url, timeout=120)
            pdf.raise_for_status()
            ruta = carpeta / f"{normalizar.huella(url)[:12]}.pdf"
            ruta.write_bytes(pdf.content)
            res = importar_pdf_diputados(con, ruta, url)
            total["documentos"] += 1
            for k, v in res.items():
                total[k] += v
            time.sleep(pausa)
        if all((anho_documento(d) or 9999) < desde_anho for d in nuevos):
            break
        pagina += 1
        time.sleep(pausa)
    return total
