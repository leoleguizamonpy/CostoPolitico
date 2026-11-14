"""Cámara de Senadores: nómina oficial de senadores y viajes con viáticos.

Estructura verificada en senado.gov.py (noviembre 2026):

1. Nómina alfabética — /index.php/menu-senadores/sub-menu-nomina-alfabetica.html
   Cada senador es un enlace a silpy.congreso.gov.py/legislador/<ID> con el texto
   "N. Apellidos, Nombres", seguido del partido en un <span class="fw-bold">.
   La numeración vuelve a 1 para los senadores vitalicios.

2. Listado de misiones — /index.php/enlaces-adicionales/menu-transparencia-activa/
   sub-menu-detalles-de-viajes-nacionales-e-internacionales.html
   Tabla #example: una fila por mes y tipo (MISION AL EXTERIOR / AL INTERIOR),
   con enlace "?idMision=<n>". Hay registros desde 2008.

3. Detalle de cada misión — misma URL con ?idMision=<n>
   Tabla #informes: # | Beneficiario | Destino | Descripción | Fecha (dd/mm/aaaa - dd/mm/aaaa)
   | Monto asignado | Monto devuelto | Archivos (informe PDF en adminweb.senado.gov.py).

Los beneficiarios incluyen funcionarios (choferes, prensa, asesores). Solo se asignan
los que cruzan con un senador; el resto queda en sin_asignar.
"""
import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import normalizar, personas
from .viaticos import CARGOS_LEGISLATIVO, _guardar_viaje

BASE = "https://www.senado.gov.py"
URL_NOMINA = BASE + "/index.php/menu-senadores/sub-menu-nomina-alfabetica.html"
URL_MISIONES = (BASE + "/index.php/enlaces-adicionales/menu-transparencia-activa/"
                "sub-menu-detalles-de-viajes-nacionales-e-internacionales.html")
FUENTE = "Cámara de Senadores — Detalles de viajes nacionales e internacionales (Ley 5189/14)"
_ENLACE_SILPY = re.compile(r"silpy\.congreso\.gov\.py/legislador/(\d+)")
_TEXTO_SENADOR = re.compile(r"^\s*(\d+)\.\s*(.+?),\s*(.+?)\s*$")


# ---------- parsers (reciben HTML, no hacen red: se pueden probar sin conexión) ----------

def parsear_nomina(html: str) -> list[dict]:
    sopa = BeautifulSoup(html, "html.parser")
    senadores, vitalicio, ultimo = [], False, 0
    for a in sopa.find_all("a", href=_ENLACE_SILPY):
        m = _TEXTO_SENADOR.match(a.get_text(" ", strip=True))
        if not m:
            continue
        numero = int(m.group(1))
        if numero == 1 and ultimo > 1:  # la numeración reinicia: empieza la lista de vitalicios
            vitalicio = True
        ultimo = numero
        partido = a.find_next("span", class_="fw-bold")
        senadores.append({
            "silpy_id": _ENLACE_SILPY.search(a["href"]).group(1),
            "apellidos": m.group(2).strip(),
            "nombres": m.group(3).strip(),
            "partido": partido.get_text(strip=True) if partido else None,
            "vitalicio": vitalicio,
        })
    return senadores


def parsear_misiones(html: str) -> list[dict]:
    sopa = BeautifulSoup(html, "html.parser")
    misiones = []
    for fila in sopa.select("#example tbody tr"):
        a = fila.find("a", href=re.compile(r"idMision=\d+"))
        celdas = fila.find_all("td")
        if not a or len(celdas) < 5:
            continue
        organo = celdas[1].get_text(" ", strip=True).upper()
        misiones.append({
            "id": int(re.search(r"idMision=(\d+)", a["href"]).group(1)),
            # "CAMARA DE SENADORES" o "CONGRESO NACIONAL" (Parlasur y órganos bicamerales)
            "congreso": "CONGRESO NACIONAL" in organo,
            "tipo": celdas[2].get_text(strip=True),
            "mes": celdas[3].get_text(strip=True),
            "anho": int(celdas[4].get_text(strip=True) or 0),
        })
    return misiones


def parsear_detalle(html: str) -> list[dict]:
    sopa = BeautifulSoup(html, "html.parser")
    viajes = []
    for fila in sopa.select("#informes tbody tr"):
        c = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in fila.find_all("td")]
        if len(c) < 7:
            continue
        informe = fila.find("a", href=True)
        viajes.append({
            "beneficiario": c[1],
            "destino": c[2],
            "motivo": c[3],
            "fechas": c[4],
            "asignado": normalizar.monto(c[5]),
            "devuelto": normalizar.monto(c[6]) or 0,
            "informe": urljoin(BASE, informe["href"]) if informe else None,
        })
    return viajes


# ---------- carga en la base ----------

def importar_nomina(con, html: str) -> dict:
    lista = parsear_nomina(html)
    for s in lista:
        personas.guardar(
            con,
            nombre_completo=f"{s['nombres']} {s['apellidos']}",
            nombres=s["nombres"],
            apellidos=s["apellidos"],
            silpy_id=s["silpy_id"],
            partido=s["partido"],
            cargo="Senador/a vitalicio/a" if s["vitalicio"] else "Senador/a",
            poder="legislativo",
            institucion="Cámara de Senadores",
        )
    con.commit()
    return {"senadores": sum(not s["vitalicio"] for s in lista), "vitalicios": sum(s["vitalicio"] for s in lista)}


CARGOS_SENADO = ("Senador/a", "Senador/a vitalicio/a")


def importar_detalle(con, html: str, id_mision: int, congreso: bool = False) -> dict:
    return importar_viajes(con, parsear_detalle(html), id_mision, congreso)


def importar_viajes(con, viajes: list[dict], id_mision: int, congreso: bool = False) -> dict:
    """En misiones de la Cámara de Senadores solo se cruza con senadores; en las del
    Congreso Nacional (Parlasur, etc.) también con diputados. Evita asignar a un diputado
    el viaje de un funcionario del Senado con nombre parecido."""
    cargos = CARGOS_LEGISLATIVO if congreso else CARGOS_SENADO
    stats = {"nueva": 0, "repetida": 0, "posible_duplicado": 0, "sin_asignar": 0, "invalida": 0}
    url = f"{URL_MISIONES}?idMision={id_mision}"
    for v in viajes:
        estado = _guardar_viaje(
            con, nombre=v["beneficiario"], destino=v["destino"], fechas=v["fechas"],
            motivo=v["motivo"], monto=v["asignado"], devuelto=v["devuelto"],
            origen="senado_viaticos", fuente_nombre=FUENTE, cargos=cargos,
            # El informe PDF es la prueba más directa; si no hay, la página de la misión.
            fuente_url=v["informe"] or url,
        )
        stats[estado] += 1
    con.commit()
    return stats


# ---------- descarga (corre en tu máquina o en el VPS) ----------

def descargar_todo(con, desde_anho: int = 2023, pausa: float = 0.7, sesion=None) -> dict:
    """Baja la nómina y todas las misiones desde `desde_anho`. Idempotente: reimportar no duplica."""
    import requests

    s = sesion or requests.Session()
    s.headers["User-Agent"] = "CostoPolitico/0.1 (transparencia; github.com/leoleguizamonpy/CostoPolitico)"

    def bajar(url):
        r = s.get(url, timeout=60)
        r.raise_for_status()
        time.sleep(pausa)
        return r.text

    total = {"nomina": importar_nomina(con, bajar(URL_NOMINA)),
             "misiones": 0, "nueva": 0, "repetida": 0, "posible_duplicado": 0, "sin_asignar": 0, "invalida": 0}
    for m in parsear_misiones(bajar(URL_MISIONES)):
        if m["anho"] < desde_anho:
            continue
        r = importar_detalle(con, bajar(f"{URL_MISIONES}?idMision={m['id']}"), m["id"], m["congreso"])
        total["misiones"] += 1
        for k, v in r.items():
            total[k] += v
    return total
