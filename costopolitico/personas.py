"""Quién cuenta como 'político' y cómo se lo identifica en cada fuente."""
import re
import sqlite3
from difflib import SequenceMatcher

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


def guardar(con: sqlite3.Connection, *, nombre_completo, cargo, poder, institucion, documento=None,
            nombres=None, apellidos=None, silpy_id=None, partido=None) -> int:
    """Crea o actualiza una persona. Busca primero por cédula, luego por ID del SILpy,
    luego por nombre dentro del mismo cargo; así la nómina SFP y las listas oficiales
    de cada cámara terminan en el mismo registro."""
    if nombres and apellidos:
        nombre_completo = f"{nombres} {apellidos}"
    nombre_norm = normalizar.nombre(nombre_completo)
    nombres_norm = normalizar.nombre(nombres) if nombres else None
    apellidos_norm = normalizar.nombre(apellidos) if apellidos else None

    pid = None
    if documento:
        f = con.execute("SELECT id FROM personas WHERE documento = ?", (documento,)).fetchone()
        pid = f["id"] if f else None
    if pid is None and silpy_id:
        f = con.execute("SELECT id FROM personas WHERE silpy_id = ?", (silpy_id,)).fetchone()
        pid = f["id"] if f else None
    if pid is None:
        pid = buscar_por_nombre(con, nombre_completo, (cargo,), permitir_corto=False)

    if pid:
        con.execute(
            "UPDATE personas SET documento = COALESCE(documento, ?), silpy_id = COALESCE(silpy_id, ?),"
            " partido = COALESCE(?, partido), nombres_norm = COALESCE(nombres_norm, ?),"
            " apellidos_norm = COALESCE(apellidos_norm, ?), institucion = ? WHERE id = ?",
            (documento, silpy_id, partido, nombres_norm, apellidos_norm, institucion, pid),
        )
        return pid
    cur = con.execute(
        "INSERT INTO personas (documento, nombre_completo, nombre_norm, nombres_norm, apellidos_norm,"
        " silpy_id, partido, cargo, poder, institucion) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (documento, nombre_completo.strip().title(), nombre_norm, nombres_norm, apellidos_norm,
         silpy_id, partido, cargo, poder, institucion),
    )
    return cur.lastrowid


PARTICULAS = {"DE", "DEL", "LA", "LAS", "LOS", "VDA", "Y"}


def _tokens(texto: str | None) -> list[str]:
    return [t for t in normalizar.nombre(texto or "").split() if t not in PARTICULAS]


def _parecido(a: str, b: str) -> bool:
    """Tolera errores de tipeo en palabras largas: 'KOBYKANSKI' ~ 'KOBYLANSKI'."""
    if a == b:
        return True
    if min(len(a), len(b)) < 5:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.85


def _alias(con, nombre: str) -> int | None:
    f = con.execute(
        "SELECT p.id FROM alias a JOIN personas p ON p.silpy_id = a.silpy_id OR p.documento = a.documento"
        " WHERE a.nombre_norm = ?", (normalizar.nombre(nombre),)).fetchall()
    return f[0]["id"] if len(f) == 1 else None


def buscar_por_nombre(con: sqlite3.Connection, nombre: str, cargos: tuple[str, ...],
                      permitir_corto: bool = True) -> int | None:
    return buscar_con_metodo(con, nombre, cargos, permitir_corto)[0]


# Métodos que no son coincidencia exacta: quedan anotados en el detalle del gasto.
METODOS_A_REVISAR = {"nombre corto", "solo apellidos", "aproximado"}


def buscar_con_metodo(con: sqlite3.Connection, nombre: str, cargos: tuple[str, ...],
                      permitir_corto: bool = True) -> tuple[int | None, str]:
    """Cruza un nombre de otra fuente (p.ej. lista de viáticos) con las personas cargadas.

    En orden: alias manual (data/alias.csv) → exacto → mismas palabras → nombre incompleto
    (3+ palabras, todas contenidas) → nombre corto (un nombre de pila + PRIMER apellido:
    en Paraguay "Juan Maciel" no es "Juan Eudes Afara Maciel") → solo apellidos ("Zacarías
    Irún") → aproximado (errores de tipeo en palabras largas).
    Solo asigna si hay UN candidato; si no, queda para revisión.
    """
    pid = _alias(con, nombre)
    if pid:
        return pid, "alias"
    objetivo = _tokens(nombre)
    if not objetivo:
        return None, ""
    marcadores = ",".join("?" * len(cargos))
    filas = con.execute(
        f"SELECT id, nombre_norm, nombres_norm, apellidos_norm FROM personas WHERE cargo IN ({marcadores})",
        cargos,
    ).fetchall()
    cand = [(f["id"], _tokens(f["nombre_norm"]), _tokens(f["nombres_norm"]), _tokens(f["apellidos_norm"]))
            for f in filas]
    s_obj = set(objetivo)

    def unico(ids):
        ids = list(dict.fromkeys(ids))
        return ids[0] if len(ids) == 1 else None

    pruebas = [
        ("exacto", lambda c: c[1] == objetivo),
        ("mismas palabras", lambda c: set(c[1]) == s_obj),
        ("nombre incompleto", lambda c: len(objetivo) >= 3 and (s_obj <= set(c[1]) or set(c[1]) <= s_obj)),
    ]
    if permitir_corto:
        pruebas += [
            ("nombre corto", lambda c: len(objetivo) == 2 and c[2] and c[3]
             and objetivo[0] in c[2] and objetivo[1] == c[3][0]),
            ("solo apellidos", lambda c: len(objetivo) >= 2 and c[3] == objetivo),
            ("aproximado", lambda c: len(objetivo) >= 2 and c[3] and _todos_parecidos(objetivo, c[1])
             and any(_parecido(t, c[3][0]) for t in objetivo)),
        ]
    for metodo, prueba in pruebas:
        pid = unico([c[0] for c in cand if prueba(c)])
        if pid:
            return pid, metodo
    return None, ""


def _todos_parecidos(origen: list[str], destino: list[str]) -> bool:
    """Cada palabra del nombre de origen se parece a una palabra distinta del destino."""
    libres = list(destino)
    for t in origen:
        par = next((d for d in libres if _parecido(t, d)), None)
        if par is None:
            return False
        libres.remove(par)
    return True
