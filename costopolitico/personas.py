"""Quién cuenta como 'político' y cómo se lo identifica en cada fuente."""
import re
import sqlite3

from . import normalizar

# Reglas sobre la nómina de la SFP (Ley 5189). Se evalúan en orden; la primera que
# coincide define el cargo. 'entidad' y 'cargo' son regex sobre texto normalizado.
REGLAS_NOMINA = [
    {"entidad": r"SENADORES", "cargo": r"\bSENADOR", "titulo": "Senador/a", "poder": "legislativo"},
    {"entidad": r"DIPUTADOS", "cargo": r"\bDIPUTAD", "titulo": "Diputado/a", "poder": "legislativo"},
    {"entidad": r"PRESIDENCIA", "cargo": r"^VICE ?PRESIDENTE DE LA REPUBLICA", "titulo": "Vicepresidente/a de la República", "poder": "ejecutivo"},
    {"entidad": r"PRESIDENCIA", "cargo": r"^PRESIDENTE DE LA REPUBLICA", "titulo": "Presidente/a de la República", "poder": "ejecutivo"},
    {"entidad": r"MINISTERIO", "cargo": r"^MINISTR[OA]\b", "titulo": "Ministro/a", "poder": "ejecutivo"},
]


def clasificar(entidad: str, cargo: str) -> dict | None:
    ent, car = normalizar.nombre(entidad), normalizar.nombre(cargo)
    for regla in REGLAS_NOMINA:
        if re.search(regla["entidad"], ent) and re.search(regla["cargo"], car):
            return regla
    return None


def guardar(con: sqlite3.Connection, *, documento, nombre_completo, cargo, poder, institucion) -> int:
    nombre_norm = normalizar.nombre(nombre_completo)
    fila = None
    if documento:
        fila = con.execute("SELECT id FROM personas WHERE documento = ?", (documento,)).fetchone()
    if fila is None:
        fila = con.execute(
            "SELECT id FROM personas WHERE nombre_norm = ? AND cargo = ?", (nombre_norm, cargo)
        ).fetchone()
    if fila:
        con.execute(
            "UPDATE personas SET documento = COALESCE(documento, ?), institucion = ? WHERE id = ?",
            (documento, institucion, fila["id"]),
        )
        return fila["id"]
    cur = con.execute(
        "INSERT INTO personas (documento, nombre_completo, nombre_norm, cargo, poder, institucion)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (documento, nombre_completo.strip().title(), nombre_norm, cargo, poder, institucion),
    )
    return cur.lastrowid


def buscar_por_nombre(con: sqlite3.Connection, nombre: str, cargos: tuple[str, ...]) -> int | None:
    """Cruza un nombre de otra fuente (p.ej. lista de viáticos) con las personas cargadas.

    1) coincidencia exacta normalizada; 2) mismas palabras en otro orden;
    3) todas las palabras de un lado contenidas en el otro (nombres incompletos).
    Si hay más de un candidato, no asigna: es preferible dejarlo para revisión.
    """
    objetivo = normalizar.nombre(nombre)
    marcadores = ",".join("?" * len(cargos))
    filas = con.execute(
        f"SELECT id, nombre_norm FROM personas WHERE cargo IN ({marcadores})", cargos
    ).fetchall()
    exactas = [f["id"] for f in filas if f["nombre_norm"] == objetivo]
    if len(exactas) == 1:
        return exactas[0]
    tokens = set(objetivo.split())
    mismas = [f["id"] for f in filas if set(f["nombre_norm"].split()) == tokens]
    if len(mismas) == 1:
        return mismas[0]
    if len(tokens) >= 3:
        contenidas = [
            f["id"] for f in filas
            if tokens <= set(f["nombre_norm"].split()) or set(f["nombre_norm"].split()) <= tokens
        ]
        if len(contenidas) == 1:
            return contenidas[0]
    return None
