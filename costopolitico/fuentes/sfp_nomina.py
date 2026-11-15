"""Remuneraciones desde la nómina de funcionarios (Ley 5189/14).

Fuente: portal de datos abiertos del Viceministerio de Capital Humano (ex SFP)
https://datos.sfp.gov.py/data/funcionarios  — CSV mensual.
Diccionario de columnas: https://datos.sfp.gov.py/def/funcionarios

El CSV trae una fila por persona y por objeto de gasto (sueldo, gastos de
representación, bonificaciones...). Se importan solo las filas de las personas
que cumplen REGLAS_NOMINA (legisladores, presidente, vice, ministros).
"""
import csv
import io
import re
import sys
import zipfile
from pathlib import Path

from .. import normalizar, personas, red

FUENTE = "Nómina de funcionarios — datos abiertos SFP/VCHGO (Ley 5189/14)"
URL_PORTAL = "https://datos.sfp.gov.py/data/funcionarios"

_ENTIDADES = re.compile(r"C.MARA|PRESIDENCIA|MINISTERIO", re.IGNORECASE)
_CAMARAS = re.compile(r"^CAMARA DE (SENADORES|DIPUTADOS)")
# Función de los funcionarios de despacho, tal como aparece en la nómina (abril 2026):
#   "DESPACHO DEL SENADOR DIONISIO AMARILLA", "ASESORA DEL DESPACHO DEL SENADOR SILVIO OVELAR",
#   "PRESTA SERVICIOS EN EL DESPACHO LEGISLATIVO DE LA DIPUTADA BETTINA ROSMARY AGUILERA PANIAGUA",
#   "ENCARGADO DE DESPACHO LEGISLATIVO DE LA DIPUTADA LEIDY GALEANO RESOLUCION N 3695 2025".
# El nombre termina donde empieza un agregado ("SERVICIOS PERSONALES", "RESOLUCION…").
_DESPACHO = re.compile(
    r"DES?PACHO(?: LEGISLATIVO)? (?:DEL?|DE LA) (SENADORA?|DIPUTAD[OA])(?: NACIONAL)? "
    r"([A-Z ]+?)(?= SERVICIOS| RESOLUCION| RES | N | NRO|$)")

# Clasificador presupuestario (objeto de gasto) — nombres legibles de los más frecuentes.
OBJETOS = {
    "111": "Sueldo",
    "112": "Dieta",
    "113": "Gastos de representación",
    "114": "Aguinaldo",
    "123": "Remuneración extraordinaria",
    "125": "Remuneración adicional",
    "133": "Bonificaciones y gratificaciones",
    "137": "Gratificaciones por servicios especiales",
    "191": "Subsidio para la salud",
    "199": "Otros gastos del personal",
    "232": "Viáticos y movilidad",
}

# Los nombres de columna cambiaron entre años; se acepta cualquiera de estos alias.
ALIAS = {
    "anho": ["anho", "anio", "año", "ano"],
    "mes": ["mes"],
    "entidad": ["descripcion_entidad", "entidad_descripcion", "descripcion_oee", "entidad"],
    "documento": ["documento", "cedula", "ci"],
    "nombres": ["nombres", "nombre"],
    "apellidos": ["apellidos", "apellido"],
    "cargo": ["cargo"],
    "funcion": ["funcion"],
    "objeto_gasto": ["objeto_gasto", "objeto_de_gasto"],
    "concepto": ["concepto", "descripcion_objeto_gasto"],
    "devengado": ["devengado"],
    "presupuestado": ["presupuestado"],
}


def _abrir(ruta: Path):
    """Abre .csv o .zip (con un .csv adentro) como texto, SIN cargarlo entero en memoria:
    los archivos mensuales pesan ~45 MB comprimidos y varios cientos descomprimidos.
    Detecta la codificación con una muestra (los de 2026 vienen en Latin-1)."""
    if ruta.suffix.lower() == ".zip":
        z = zipfile.ZipFile(ruta)
        nombre = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        abrir_binario = lambda: z.open(nombre)
    else:
        abrir_binario = lambda: open(ruta, "rb")
    with abrir_binario() as b:
        muestra = b.read(2_000_000)
    try:
        muestra[:-4].decode("utf-8")
        codificacion = "utf-8-sig"
    except UnicodeDecodeError:
        codificacion = "latin-1"
    return io.TextIOWrapper(abrir_binario(), encoding=codificacion, newline="")


def _mapear_columnas(encabezado: list[str]) -> dict[str, str]:
    bajo = {c.strip().lower(): c for c in encabezado}
    mapa = {}
    for clave, opciones in ALIAS.items():
        for op in opciones:
            if op in bajo:
                mapa[clave] = bajo[op]
                break
    faltan = {"entidad", "nombres", "cargo"} - mapa.keys()
    if faltan:
        raise ValueError(f"El CSV no tiene las columnas esperadas: {sorted(faltan)}. Encabezado: {encabezado}")
    return mapa


def importar(con, ruta, fuente_url: str = URL_PORTAL) -> dict:
    ruta = Path(ruta)
    with _abrir(ruta) as texto:
        primera = texto.readline()
    delimitador = csv.Sniffer().sniff(primera, delimiters=",;|").delimiter
    texto = _abrir(ruta)
    lector = csv.DictReader(texto, delimiter=delimitador)
    col = _mapear_columnas(lector.fieldnames or [])
    descargado = normalizar.ahora()
    stats = {"filas": 0, "politicos": 0, "gastos_nuevos": 0, "personal_despacho": 0, "personal_sin_asignar": 0,
             "comisionados": 0}
    repetidas: dict = {}
    personal: list = []  # (cargo del legislador, nombre, fila) — se asignan al final, ya cargados todos
    from . import comisionados
    asignados = comisionados.vigentes(con)  # cédula -> despacho donde está comisionado
    comision: list = []

    def v(fila, clave):
        return (fila.get(col.get(clave, ""), "") or "").strip()

    for fila in lector:
        stats["filas"] += 1
        # Comisionados: funcionarios de cualquier institución que trabajan en un despacho.
        # Se buscan por cédula antes del filtro por entidad, porque su sueldo lo paga otra.
        if asignados:
            doc = re.sub(r"\D", "", fila.get(col.get("documento", ""), "") or "")
            if doc in asignados and not personas.clasificar(v(fila, "entidad"), v(fila, "cargo"), v(fila, "funcion")) \
                    and not (_DESPACHO.search(normalizar.nombre(v(fila, "funcion")))
                             and _CAMARAS.search(normalizar.nombre(v(fila, "entidad")))):
                comision.append((asignados[doc], {k: v(fila, k) for k in col}))
                continue
        # Filtro barato antes de las expresiones regulares: ~1 millón de filas por mes.
        if not _ENTIDADES.search(fila.get(col["entidad"], "") or ""):
            continue
        regla = personas.clasificar(v(fila, "entidad"), v(fila, "cargo"), v(fila, "funcion"))
        if not regla:
            m = _DESPACHO.search(normalizar.nombre(v(fila, "funcion")))
            if m and _CAMARAS.search(normalizar.nombre(v(fila, "entidad"))):
                personal.append((m.group(1), m.group(2), {k: v(fila, k) for k in col}))
            continue
        nombre = f"{v(fila, 'nombres')} {v(fila, 'apellidos')}".strip()
        if personas.es_relleno(nombre):
            continue
        # Solo lo efectivamente devengado (pagado). Lo presupuestado no es gasto.
        monto = normalizar.monto(v(fila, "devengado"))
        if not monto:
            continue
        stats["politicos"] += 1
        pid = personas.guardar(
            con,
            documento=v(fila, "documento") or None,
            nombre_completo=nombre,
            nombres=v(fila, "nombres") or None,
            apellidos=v(fila, "apellidos") or None,
            cargo=regla["titulo"],
            poder=regla["poder"],
            institucion=v(fila, "entidad").title(),
        )
        anho, mes = v(fila, "anho"), v(fila, "mes")
        periodo = f"{int(anho):04d}-{int(mes):02d}" if anho.isdigit() and mes.isdigit() else "s/f"
        objeto = v(fila, "objeto_gasto")
        # Puede haber dos líneas idénticas legítimas en un mes (dos viáticos del mismo monto):
        # se numeran para que no se fusionen, sin perder la idempotencia al reimportar.
        clave = (pid, periodo, objeto, monto)
        repetidas[clave] = n = repetidas.get(clave, 0) + 1
        concepto = OBJETOS.get(objeto, v(fila, "concepto").title() or "Remuneración")
        categoria = "viatico" if objeto.startswith("23") else "remuneracion"
        detalle = " · ".join(x for x in (f"objeto de gasto {objeto}" if objeto else "", v(fila, "funcion") or v(fila, "cargo")) if x)
        cur = con.execute(
            "INSERT OR IGNORE INTO gastos (persona_id, categoria, concepto, monto, periodo, detalle,"
            " fuente_nombre, fuente_url, descargado_en, huella) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, categoria, concepto, monto, periodo, detalle, FUENTE, fuente_url,
             descargado, normalizar.huella("sfp", pid, periodo, objeto, monto, n)),
        )
        stats["gastos_nuevos"] += cur.rowcount
    _asignar_personal(con, personal, fuente_url, descargado, stats)
    _asignar_comisionados(con, comision, fuente_url, descargado, stats)
    con.commit()
    texto.close()
    return stats


def _asignar_personal(con, personal, fuente_url, descargado, stats):
    """Asigna a cada legislador el costo del personal de su despacho (asesores, secretarios,
    choferes…), según la función declarada en la nómina. Se guarda agregado: en la web se ve
    cuántas personas y cuánto cuestan por mes, no sus nombres."""
    repetidas: dict = {}
    for titulo, nombre_leg, f in personal:
        monto = normalizar.monto(f.get("devengado"))
        if not monto:
            continue
        cargos = ("Senador/a", "Senador/a vitalicio/a") if titulo.startswith("SENADOR") else ("Diputado/a",)
        pid, metodo = personas.buscar_con_metodo(con, nombre_leg, cargos)
        anho, mes = f.get("anho", ""), f.get("mes", "")
        periodo = f"{int(anho):04d}-{int(mes):02d}" if anho.isdigit() and mes.isdigit() else "s/f"
        ref = normalizar.huella("personal", f.get("documento") or f.get("nombres", "") + f.get("apellidos", ""))[:12]
        if pid is None:
            con.execute(
                "INSERT OR IGNORE INTO sin_asignar (origen, nombre, monto, detalle, fuente_url, huella)"
                " VALUES (?,?,?,?,?,?)",
                ("personal_despacho", nombre_leg.title(), monto, f"{periodo} · {f.get('funcion', '')}"[:200],
                 fuente_url, normalizar.huella("personal_sa", ref, periodo, f.get("objeto_gasto"), monto)))
            stats["personal_sin_asignar"] += 1
            continue
        objeto = f.get("objeto_gasto", "")
        clave = (pid, ref, periodo, objeto, monto)
        repetidas[clave] = n = repetidas.get(clave, 0) + 1
        detalle = " · ".join(x for x in (f.get("cargo") or "funcionario", f"objeto de gasto {objeto}" if objeto else "",
                                          f"cruce {metodo}: «{nombre_leg.title()}»" if metodo in personas.METODOS_A_REVISAR else "") if x)
        cur = con.execute(
            "INSERT OR IGNORE INTO gastos (persona_id, categoria, concepto, monto, periodo, detalle,"
            " fuente_nombre, fuente_url, descargado_en, referencia, huella) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, "asesores", "Personal del despacho", monto, periodo, detalle, FUENTE, fuente_url,
             descargado, ref, normalizar.huella("personal", pid, ref, periodo, objeto, monto, n)))
        stats["personal_despacho"] += cur.rowcount


def _asignar_comisionados(con, comision, fuente_url, descargado, stats):
    """Sueldo de cada comisionado, en los meses en que estuvo asignado a un despacho."""
    from .comisionados import legislador_en

    repetidas: dict = {}
    for asignaciones, f in comision:
        monto = normalizar.monto(f.get("devengado"))
        anho, mes = f.get("anho", ""), f.get("mes", "")
        if not monto or not (anho.isdigit() and mes.isdigit()):
            continue
        periodo = f"{int(anho):04d}-{int(mes):02d}"
        a = legislador_en(asignaciones, periodo)
        if not a:
            continue
        # Mismo identificador que el personal de planta: si alguien cambia de régimen
        # se cuenta una sola persona.
        ref = normalizar.huella("personal", f.get("documento"))[:12]
        objeto = f.get("objeto_gasto", "")
        clave = (a["persona_id"], ref, periodo, objeto, monto)
        repetidas[clave] = n = repetidas.get(clave, 0) + 1
        detalle = " · ".join(x for x in (
            f"Comisionado ({(f.get('entidad') or 'otra institución').title()})",
            f"objeto de gasto {objeto}" if objeto else "",
            f"cruce {a['metodo']}: «{a['nombre_legislador']}»" if a["metodo"] in personas.METODOS_A_REVISAR else "",
        ) if x)
        stats["comisionados"] += con.execute(
            "INSERT OR IGNORE INTO gastos (persona_id, categoria, concepto, monto, periodo, detalle,"
            " fuente_nombre, fuente_url, descargado_en, referencia, huella) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (a["persona_id"], "asesores", "Personal comisionado de otra institución", monto, periodo, detalle,
             FUENTE, fuente_url, descargado, ref,
             normalizar.huella("comisionado", a["persona_id"], ref, periodo, objeto, monto, n))).rowcount


if __name__ == "__main__":
    from ..db import conectar
    print(importar(conectar(), sys.argv[1]))


# ---------- descarga mensual ----------
# Verificado en noviembre de 2026: https://datos.sfp.gov.py/data/funcionarios_{año}_{mes}.csv.zip
# (mes sin cero a la izquierda). Los archivos completos pesan 30-50 MB; desde junio de 2026 el
# portal publica archivos casi vacíos (1-6 KB) y octubre de 2026 viene parcial (1,4 MB).
# Un archivo bajo el umbral se considera incompleto: no se importa ni se marca, y se vuelve a
# intentar en la próxima corrida por si la SFP lo completa.

URL_MES = "https://datos.sfp.gov.py/data/funcionarios_{anho}_{mes}.csv.zip"
UMBRAL_COMPLETO = 10_000_000  # bytes


def meses(desde: tuple[int, int], hasta: tuple[int, int]):
    a, m = desde
    while (a, m) <= hasta:
        yield a, m
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)


def descargar_meses(con, desde: tuple[int, int] = (2023, 7), hasta: tuple[int, int] | None = None,
                    sesion=None, carpeta=None, umbral: int = UMBRAL_COMPLETO) -> dict:
    """Baja e importa cada mes publicado. Por defecto desde julio de 2023 (inicio del período
    legislativo y de gobierno 2023-2028)."""
    import tempfile
    from datetime import date

    import requests

    s = sesion or red.sesion()
    hoy = date.today()
    hasta = hasta or (hoy.year, hoy.month)
    carpeta = Path(carpeta or tempfile.mkdtemp(prefix="sfp_"))
    carpeta.mkdir(parents=True, exist_ok=True)
    from . import comisionados

    resumen = {"importados": [], "ya_importados": 0, "incompletos": [], "no_publicados": []}
    for a, m in meses(desde, hasta):
        clave = f"{a}-{m:02d}"
        hecho = con.execute("SELECT 1 FROM importaciones WHERE fuente='sfp' AND clave=?", (clave,)).fetchone()
        firma = comisionados.firma(con, clave)
        previa = con.execute("SELECT resultado FROM importaciones WHERE fuente='sfp-comisionados' AND clave=?",
                             (clave,)).fetchone()
        # Un mes ya leído se vuelve a leer solo si aparecieron comisionados nuevos (la nómina
        # completa no se guarda). Reimportar no duplica: cada gasto tiene huella única.
        if hecho and firma == (previa[0] if previa else ""):
            resumen["ya_importados"] += 1
            continue
        url = URL_MES.format(anho=a, mes=m)
        cab = s.head(url, timeout=60, allow_redirects=True)
        if cab.status_code == 404:
            resumen["no_publicados"].append(clave)
            continue
        cab.raise_for_status()
        tam = int(cab.headers.get("content-length") or 0)
        if tam and tam < umbral:
            resumen["incompletos"].append(f"{clave} ({tam:,} bytes)".replace(",", "."))
            continue
        destino = carpeta / f"funcionarios_{a}_{m}.csv.zip"
        with s.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(destino, "wb") as f:
                for trozo in r.iter_content(1 << 20):
                    f.write(trozo)
        res = importar(con, destino, url)
        con.execute("INSERT OR REPLACE INTO importaciones VALUES ('sfp', ?, ?, ?)",
                    (clave, normalizar.ahora(), str(res)))
        con.execute("INSERT OR REPLACE INTO importaciones VALUES ('sfp-comisionados', ?, ?, ?)",
                    (clave, normalizar.ahora(), firma))
        con.commit()
        destino.unlink(missing_ok=True)
        resumen["importados"].append(clave)
    return resumen
