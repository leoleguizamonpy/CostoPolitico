"""Funcionarios comisionados al despacho de un legislador.

Un "comisionado" es un funcionario de otra institución (un ministerio, una municipalidad, la
ESSAP, la otra cámara…) que trabaja en el despacho de un senador o diputado. Su sueldo lo sigue
pagando la institución de origen, así que no aparece en la nómina de la cámara: es un costo del
legislador que queda escondido en el presupuesto de otro organismo.

La Cámara de Diputados publica cada mes, por la Ley 5189, dos listados en PDF
(https://diputados.gov.py/transparencia/ley-5189):

  * "FUNCIONARIOS COMISIONADOS A LA HONORABLE CÁMARA DE DIPUTADOS" — vienen de otras
    instituciones. Columnas: Nº | CÉDULA | NOMBRES APELLIDOS | ENTIDAD DE ORIGEN |
    FUNCIÓN QUE CUMPLE | RESOLUCIÓN | FECHA ACTO ADMINISTRATIVO | FECHA DE FINALIZACIÓN.
  * "FUNCIONARIOS COMISIONADOS DE LA HONORABLE CÁMARA DE DIPUTADOS A OTRAS INSTITUCIONES" —
    funcionarios de Diputados prestados afuera, entre ellos a despachos de senadores.

La función dice para quién trabaja: "PRESTA SERVICIOS DESPACHO LEGISLATIVO DEL DIPUTADO
ROBERTO GONZÁLEZ", "PRESTA SERVICIOS EN EL DESPACHO DE LA SENADORA GUADALUPE AVEIRO".
Solo se guardan los que trabajan en un despacho: los asignados a una dirección, comisión o
bancada no son de un legislador en particular.

Aquí se guarda solo la asignación (cédula, legislador, vigencia). El monto sale de la nómina de
la SFP de la institución que le paga, cruzando por cédula (ver sfp_nomina.importar).
"""
import re
import time
from pathlib import Path

from .. import normalizar, personas, red

FUENTE = "Cámara de Diputados — Funcionarios comisionados (Ley 5189)"

# Mismo criterio que el personal de planta en sfp_nomina._DESPACHO, más la variante
# "PRESTA SERVICIOS DESPACHO …" sin "EN EL". El nombre termina donde empieza la resolución.
_DESPACHO = re.compile(
    r"DES?PACHO(?: LEGISLATIVO)? (?:DEL?|DE LA) (SENADORA?|DIPUTAD[OA])(?: NACIONAL)? "
    r"([A-Z ]+?)(?= SERVICIOS| RESOLUCION| RES | N | NO | NRO| N$| NO$|$)")
_CEDULA = re.compile(r"\b(\d{1,3}(?:\.\d{3})+|\d{5,9})\b")
_FECHA = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")
# Comienzo de un registro en el texto corrido: número de orden + cédula con puntos.
_INICIO = re.compile(r"(?m)^\s*\d{1,4}\s+\d{1,3}(?:\.\d{3})+\s")


def es_listado(titulo: str) -> bool:
    return "COMISIONADOS" in normalizar.nombre(titulo)


def despacho(funcion: str):
    """'PRESTA SERVICIOS EN EL DESPACHO DE LA SENADORA GUADALUPE AVEIRO' -> ('Senador/a', 'GUADALUPE AVEIRO')."""
    m = _DESPACHO.search(normalizar.nombre(funcion))
    if not m:
        return None
    cargo = "Senador/a" if m.group(1).startswith("SENADOR") else "Diputado/a"
    return cargo, m.group(2).strip()


def _registro(cedula, entidad, funcion, fechas):
    desde, hasta = normalizar.rango_fechas(" ".join(fechas))
    return {"documento": re.sub(r"\D", "", cedula), "entidad": entidad, "funcion": funcion,
            "desde": desde, "hasta": hasta}


def filas_pdf(ruta: Path) -> list[dict]:
    """Lee el PDF. Primero como tabla con bordes (una celda por columna); si no hay tablas,
    corta el texto en registros que empiezan con "número de orden + cédula", porque la función
    suele ocupar dos o tres renglones."""
    import pdfplumber

    filas = []
    with pdfplumber.open(ruta) as pdf:
        mapa = None  # índice de columnas, se arrastra a las páginas sin encabezado
        for pagina in pdf.pages:
            for tabla in pagina.extract_tables():
                for fila in tabla:
                    celdas = [re.sub(r"\s+", " ", c or "").strip() for c in fila]
                    sin_tildes = [normalizar.nombre(c) for c in celdas]
                    if any("CEDULA" in c for c in sin_tildes):
                        mapa = {
                            "cedula": next(i for i, c in enumerate(sin_tildes) if "CEDULA" in c),
                            "entidad": next((i for i, c in enumerate(sin_tildes) if "ENTIDAD" in c), None),
                            "funcion": next((i for i, c in enumerate(sin_tildes) if "FUNCION" in c), None),
                        }
                        continue
                    if not mapa or mapa["cedula"] >= len(celdas) or not _CEDULA.fullmatch(celdas[mapa["cedula"]]):
                        continue
                    pick = lambda k: celdas[mapa[k]] if mapa.get(k) is not None and mapa[k] < len(celdas) else ""
                    filas.append(_registro(celdas[mapa["cedula"]], pick("entidad"),
                                           pick("funcion") or " ".join(celdas),
                                           [c for c in celdas if _FECHA.fullmatch(c)]))
        if not filas:
            cols = None
            for pagina in pdf.pages:
                cols, nuevas = _por_posicion(pagina, cols)
                filas += nuevas
        if not filas:
            texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
            inicios = [m.start() for m in _INICIO.finditer(texto)] + [len(texto)]
            for a, b in zip(inicios, inicios[1:]):
                reg = re.sub(r"\s+", " ", texto[a:b]).strip()
                ced = _CEDULA.search(reg.split(" ", 1)[1] if " " in reg else reg)
                if ced:
                    filas.append(_registro(ced.group(1), None, reg, _FECHA.findall(reg)))
    return filas


def _por_posicion(pagina, cols):
    """PDF sin bordes: las celdas largas se parten en renglones centrados verticalmente
    alrededor del renglón que tiene el número de orden y la cédula. Se ubica la columna
    FUNCIÓN por la posición del encabezado y a cada fila le tocan las palabras que caen
    entre la mitad de la distancia a la fila anterior y a la siguiente."""
    palabras = pagina.extract_words()
    for w in palabras:
        n = normalizar.nombre(w["text"])
        if "FUNCION" in n:
            cols = dict(cols or {}, funcion=w["x0"])
        elif n.startswith("RESOLUCI"):
            cols = dict(cols or {}, resolucion=w["x0"])
    if not cols or "funcion" not in cols:
        return cols, []
    fin_funcion = cols.get("resolucion", float("inf"))
    renglones: dict = {}
    for w in palabras:
        renglones.setdefault(round(w["top"]), []).append(w)
    anclas = []
    for top, ws in sorted(renglones.items()):
        ws.sort(key=lambda w: w["x0"])
        if len(ws) >= 2 and ws[0]["text"].isdigit() and _CEDULA.fullmatch(ws[1]["text"]) \
                and ws[1]["x0"] < cols["funcion"]:
            anclas.append((top, ws[1]["text"]))
    filas = []
    for i, (top, cedula) in enumerate(anclas):
        arriba = (anclas[i - 1][0] + top) / 2 if i else top - 40
        abajo = (top + anclas[i + 1][0]) / 2 if i + 1 < len(anclas) else top + 40
        banda = sorted((w for w in palabras if arriba <= (w["top"] + w["bottom"]) / 2 < abajo),
                       key=lambda w: (round(w["top"]), w["x0"]))
        funcion = " ".join(w["text"] for w in banda if cols["funcion"] - 2 <= w["x0"] < fin_funcion - 2)
        fechas = [w["text"] for w in banda if _FECHA.fullmatch(w["text"])]
        filas.append(_registro(cedula, None, funcion, fechas))
    return cols, filas


def importar_pdf(con, ruta, fuente_url: str) -> dict:
    stats = {"filas": 0, "despacho": 0, "nuevas": 0, "sin_asignar": 0, "otras_funciones": 0}
    descargado = normalizar.ahora()
    for f in filas_pdf(Path(ruta)):
        stats["filas"] += 1
        d = despacho(f["funcion"])
        if not d or not f["documento"]:
            stats["otras_funciones"] += 1
            continue
        stats["despacho"] += 1
        cargo, nombre_leg = d
        cargos = ("Senador/a", "Senador/a vitalicio/a") if cargo == "Senador/a" else ("Diputado/a",)
        pid, metodo = personas.buscar_con_metodo(con, nombre_leg, cargos)
        if pid is None:
            # La cédula del funcionario no se publica: queda solo el nombre del legislador.
            stats["sin_asignar"] += con.execute(
                "INSERT OR IGNORE INTO sin_asignar (origen, nombre, monto, detalle, fuente_url, huella)"
                " VALUES (?,?,?,?,?,?)",
                ("comisionado", nombre_leg.title(), None,
                 f"{cargo} · comisionado desde/hacia {f['entidad'] or 'otra institución'} · {f['desde']} a {f['hasta']}"[:200],
                 fuente_url, normalizar.huella("comisionado_sa", f["documento"], nombre_leg, f["desde"]))).rowcount
            continue
        stats["nuevas"] += con.execute(
            "INSERT OR IGNORE INTO comisionados (documento, persona_id, cargo_legislador, nombre_legislador,"
            " metodo, entidad, funcion, desde, hasta, fuente_url, descargado_en, huella)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (f["documento"], pid, cargo, nombre_leg.title(), metodo, f["entidad"], f["funcion"][:300],
             f["desde"], f["hasta"], fuente_url, descargado,
             normalizar.huella("comisionado", f["documento"], pid, f["desde"], f["hasta"]))).rowcount
    con.commit()
    return stats


def vigentes(con) -> dict[str, list[dict]]:
    """cédula -> asignaciones (legislador y vigencia), para cruzar con la nómina de la SFP."""
    res: dict[str, list[dict]] = {}
    for r in con.execute("SELECT documento, persona_id, cargo_legislador, nombre_legislador, metodo,"
                         " entidad, desde, hasta FROM comisionados WHERE persona_id IS NOT NULL"):
        res.setdefault(r["documento"], []).append(dict(r))
    return res


def legislador_en(asignaciones: list[dict], periodo: str):
    """La asignación vigente en el mes AAAA-MM (la vigencia se cuenta por mes completo)."""
    for a in asignaciones:
        if (not a["desde"] or a["desde"][:7] <= periodo) and (not a["hasta"] or a["hasta"][:7] >= periodo):
            return a
    return None


def firma(con, periodo: str) -> str:
    """Huella de los comisionados vigentes en el mes AAAA-MM. Si cambia, hay que volver a leer
    ese mes de la SFP (la nómina completa no se guarda). Una asignación nueva solo cambia los
    meses que cubre, así que no obliga a bajar todo de nuevo."""
    filas = con.execute(
        "SELECT documento, persona_id, desde, hasta FROM comisionados WHERE persona_id IS NOT NULL"
        " AND (desde IS NULL OR substr(desde,1,7) <= ?) AND (hasta IS NULL OR substr(hasta,1,7) >= ?)"
        " ORDER BY 1,2,3,4", (periodo, periodo)).fetchall()
    return normalizar.huella(*[tuple(f) for f in filas])[:16] if filas else ""


def descargar(con, desde_anho: int = 2023, pausa: float = 0.7, sesion=None, carpeta=None) -> dict:
    """Recorre el listado de la Ley 5189 de Diputados y baja los listados de comisionados."""
    import tempfile

    from requests.utils import requote_uri

    from .diputados import URL_LEY_5189, anho_documento, parsear_documentos

    s = sesion or red.sesion()
    carpeta = Path(carpeta or tempfile.mkdtemp(prefix="comisionados_"))
    carpeta.mkdir(parents=True, exist_ok=True)
    total = {"documentos": 0, "filas": 0, "despacho": 0, "nuevas": 0, "sin_asignar": 0, "otras_funciones": 0}
    pagina, vistos = 1, set()
    while True:
        r = s.get(URL_LEY_5189, params={"search": "COMISIONADOS", "page": pagina}, timeout=60)
        r.raise_for_status()
        docs = [d for d in parsear_documentos(r.text) if d["url"] not in vistos]
        if not docs:
            break
        for d in docs:
            vistos.add(d["url"])
            anho = anho_documento(d)
            if not es_listado(d["titulo"]) or (anho and anho < desde_anho):
                continue
            ya = con.execute("SELECT 1 FROM importaciones WHERE fuente='comisionados' AND clave=?",
                             (d["url"],)).fetchone()
            if ya:
                continue
            url = requote_uri(d["url"])
            pdf = s.get(url, timeout=120)
            pdf.raise_for_status()
            ruta = carpeta / f"{normalizar.huella(url)[:12]}.pdf"
            ruta.write_bytes(pdf.content)
            res = importar_pdf(con, ruta, url)
            con.execute("INSERT OR REPLACE INTO importaciones VALUES ('comisionados', ?, ?, ?)",
                        (d["url"], normalizar.ahora(), str(res)))
            con.commit()
            total["documentos"] += 1
            for k, v in res.items():
                total[k] += v
            time.sleep(pausa)
        if all((anho_documento(d) or 9999) < desde_anho for d in docs):
            break
        pagina += 1
        time.sleep(pausa)
    return total
