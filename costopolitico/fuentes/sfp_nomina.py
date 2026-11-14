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
import sys
import zipfile
from pathlib import Path

from .. import normalizar, personas

FUENTE = "Nómina de funcionarios — datos abiertos SFP/VCHGO (Ley 5189/14)"
URL_PORTAL = "https://datos.sfp.gov.py/data/funcionarios"

# Los nombres de columna cambiaron entre años; se acepta cualquiera de estos alias.
ALIAS = {
    "anho": ["anho", "anio", "año", "ano"],
    "mes": ["mes"],
    "entidad": ["descripcion_entidad", "entidad_descripcion", "descripcion_oee", "entidad"],
    "documento": ["documento", "cedula", "ci"],
    "nombres": ["nombres", "nombre"],
    "apellidos": ["apellidos", "apellido"],
    "cargo": ["cargo", "funcion"],
    "objeto_gasto": ["objeto_gasto", "objeto_de_gasto"],
    "concepto": ["concepto", "descripcion_objeto_gasto"],
    "devengado": ["devengado"],
    "presupuestado": ["presupuestado"],
}


def _abrir(ruta: Path):
    """Acepta .csv o .zip con un .csv adentro. Prueba UTF-8 y Latin-1."""
    if ruta.suffix.lower() == ".zip":
        with zipfile.ZipFile(ruta) as z:
            nombre = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            crudo = z.read(nombre)
    else:
        crudo = ruta.read_bytes()
    for cod in ("utf-8-sig", "latin-1"):
        try:
            return io.StringIO(crudo.decode(cod))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"No se pudo decodificar {ruta}")


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
    texto = _abrir(ruta)
    muestra = texto.read(4096)
    texto.seek(0)
    delimitador = csv.Sniffer().sniff(muestra, delimiters=",;|").delimiter
    lector = csv.DictReader(texto, delimiter=delimitador)
    col = _mapear_columnas(lector.fieldnames or [])
    descargado = normalizar.ahora()
    stats = {"filas": 0, "politicos": 0, "gastos_nuevos": 0}

    def v(fila, clave):
        return (fila.get(col.get(clave, ""), "") or "").strip()

    for fila in lector:
        stats["filas"] += 1
        regla = personas.clasificar(v(fila, "entidad"), v(fila, "cargo"))
        if not regla:
            continue
        monto = normalizar.monto(v(fila, "devengado")) or normalizar.monto(v(fila, "presupuestado"))
        if not monto:
            continue
        stats["politicos"] += 1
        nombre = f"{v(fila, 'nombres')} {v(fila, 'apellidos')}".strip()
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
        concepto = " ".join(x for x in (v(fila, "objeto_gasto"), v(fila, "concepto")) if x) or "Remuneración"
        cur = con.execute(
            "INSERT OR IGNORE INTO gastos (persona_id, categoria, concepto, monto, periodo, detalle,"
            " fuente_nombre, fuente_url, descargado_en, huella) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, "remuneracion", concepto, monto, periodo, v(fila, "cargo"), FUENTE, fuente_url,
             descargado, normalizar.huella("sfp", pid, periodo, concepto, monto)),
        )
        stats["gastos_nuevos"] += cur.rowcount
    con.commit()
    return stats


if __name__ == "__main__":
    from ..db import conectar
    print(importar(conectar(), sys.argv[1]))
