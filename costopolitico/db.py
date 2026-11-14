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
    return con
