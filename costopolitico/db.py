"""Base de datos SQLite de CostoPolitico.

Principio: cada monto guardado tiene fuente (nombre + URL) y fecha de descarga.
Montos siempre en guaraníes enteros.
"""
import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DB_POR_DEFECTO = RAIZ / "data" / "costopolitico.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS personas (
    id              INTEGER PRIMARY KEY,
    documento       TEXT UNIQUE,          -- cédula, cuando la fuente la trae
    nombre_completo TEXT NOT NULL,
    nombre_norm     TEXT NOT NULL,        -- mayúsculas, sin tildes, para cruzar fuentes
    nombres_norm    TEXT,                 -- solo nombres de pila (si la fuente los separa)
    apellidos_norm  TEXT,
    silpy_id        TEXT UNIQUE,          -- ID del legislador en silpy.congreso.gov.py
    partido         TEXT,
    cargo           TEXT NOT NULL,        -- Senador/a, Diputado/a, Ministro/a...
    poder           TEXT NOT NULL CHECK (poder IN ('legislativo', 'ejecutivo')),
    institucion     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_personas_nombre ON personas(nombre_norm);

-- Gastos ASIGNADOS A LA PERSONA (sueldo, viáticos, etc.).
-- El gasto de la institución que dirige va aparte (fase 2), nunca sumado acá.
CREATE TABLE IF NOT EXISTS gastos (
    id            INTEGER PRIMARY KEY,
    persona_id    INTEGER NOT NULL REFERENCES personas(id),
    categoria     TEXT NOT NULL CHECK (categoria IN ('remuneracion', 'viatico', 'pasaje', 'asesores', 'otros')),
    concepto      TEXT NOT NULL,
    monto         INTEGER NOT NULL,       -- guaraníes
    periodo       TEXT NOT NULL,          -- YYYY-MM
    fecha_inicio  TEXT,                   -- YYYY-MM-DD (viajes)
    fecha_fin     TEXT,
    detalle       TEXT,
    fuente_nombre TEXT NOT NULL,
    fuente_url    TEXT NOT NULL,
    descargado_en TEXT NOT NULL,
    huella        TEXT NOT NULL UNIQUE    -- evita duplicados al reimportar
);
CREATE INDEX IF NOT EXISTS ix_gastos_persona ON gastos(persona_id);

-- Alias manuales para nombres que el cruce automático no resuelve (se cargan de data/alias.csv).
CREATE TABLE IF NOT EXISTS alias (
    nombre_norm TEXT PRIMARY KEY,
    silpy_id    TEXT,
    documento   TEXT
);

-- Filas de una fuente que no se pudieron asignar a ninguna persona.
-- Se revisan a mano: nunca se descartan en silencio.
CREATE TABLE IF NOT EXISTS sin_asignar (
    id          INTEGER PRIMARY KEY,
    origen      TEXT NOT NULL,
    nombre      TEXT NOT NULL,
    monto       INTEGER,
    detalle     TEXT,
    fuente_url  TEXT NOT NULL,
    huella      TEXT NOT NULL UNIQUE
);
"""


def conectar(ruta=None) -> sqlite3.Connection:
    ruta = Path(ruta) if ruta else DB_POR_DEFECTO
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(ESQUEMA)
    cargar_alias(con)
    return con


ALIAS_CSV = RAIZ / "data" / "alias.csv"


def cargar_alias(con, ruta=ALIAS_CSV) -> int:
    """data/alias.csv: nombre tal como aparece en la fuente -> silpy_id o cédula.
    Para los casos que el cruce automático no resuelve (p.ej. 'Pedro Días Verón')."""
    import csv
    from .normalizar import nombre

    ruta = Path(ruta)
    if not ruta.exists():
        return 0
    n = 0
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        for fila in csv.DictReader(f):
            if not (fila.get("nombre_fuente") or "").strip():
                continue
            con.execute(
                "INSERT OR REPLACE INTO alias (nombre_norm, silpy_id, documento) VALUES (?, ?, ?)",
                (nombre(fila["nombre_fuente"]), (fila.get("silpy_id") or "").strip() or None,
                 (fila.get("documento") or "").strip() or None),
            )
            n += 1
    con.commit()
    return n
