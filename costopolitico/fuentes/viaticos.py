"""Viáticos por viajes oficiales.

Diputados publica un PDF mensual "VIAJES OFICIALES / MISIONES PARLAMENTARIAS" en
https://www.diputados.gov.py (sección Transparencia) con columnas:
  Nº | DIPUTADO/A O FUNCIONARIO/A | RESOLUCIÓN | DESTINO | FECHA | MOTIVO | MONTO DEL VIÁTICO TOTAL
  ej. 1 | CARLOS ALBERTO NUÑEZ SALINAS | RES. ADM. Nº 1880 | CIUDAD DE PANAMÁ... |
      29/01/2025 AL 02/02/2025 | PARTICIPAR DEL FORO... | ₲ 5.073.097

El Senado publica beneficiario, destino, período, motivo y monto en su web.
Mientras se escribe su scraper específico, sus datos (o cualquier otra lista de
viáticos) se cargan con el CSV genérico: ver data/plantillas/viaticos.csv.

Las filas que no son de un legislador (funcionarios) o cuyo nombre no se puede
cruzar con seguridad quedan en la tabla sin_asignar para revisión manual.
"""
import csv
import re
from pathlib import Path

from .. import normalizar, personas

CARGOS_LEGISLATIVO = ("Senador/a", "Senador/a vitalicio/a", "Diputado/a")


def _guardar_viaje(con, *, nombre, destino, fechas, motivo, monto, origen, fuente_nombre,
                   fuente_url, resolucion="", devuelto=0, cargos=CARGOS_LEGISLATIVO) -> str:
    """Guarda un viaje. Si hubo devolución, el monto guardado es el neto (asignado - devuelto)."""
    inicio, fin = normalizar.rango_fechas(fechas) if isinstance(fechas, str) else fechas
    if not monto or not inicio:
        return "invalida"
    devuelto = devuelto or 0
    neto = max(monto - devuelto, 0)
    partes = [motivo, resolucion]  # el destino ya va en el concepto
    if devuelto:
        partes.append(f"asignado ₲ {monto:,} − devuelto ₲ {devuelto:,}".replace(",", "."))
    if devuelto > monto:
        partes.append("ATENCIÓN: la fuente informa una devolución mayor al monto asignado")
    pid, metodo = personas.buscar_con_metodo(con, nombre, cargos)
    if metodo in personas.METODOS_A_REVISAR:
        partes.append(f"cruce {metodo}: «{nombre}»")
    detalle = " · ".join(x for x in partes if x)
    monto = neto
    if pid is None:
        con.execute(
            "INSERT OR IGNORE INTO sin_asignar (origen, nombre, monto, detalle, fuente_url, huella)"
            " VALUES (?,?,?,?,?,?)",
            (origen, nombre, monto, detalle, fuente_url, normalizar.huella(origen, nombre, inicio, monto)),
        )
        return "sin_asignar"
    cur = con.execute(
        "INSERT OR IGNORE INTO gastos (persona_id, categoria, concepto, monto, periodo, fecha_inicio,"
        " fecha_fin, detalle, fuente_nombre, fuente_url, descargado_en, huella)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, "viatico", f"Viático — {destino}".strip(" —"), monto, inicio[:7], inicio, fin, detalle,
         fuente_nombre, fuente_url, normalizar.ahora(), normalizar.huella("viatico", pid, inicio, destino, monto)),
    )
    if cur.rowcount:
        return "nueva"
    # Mismo viaje ya cargado. Si viene de OTRO documento, puede ser doble publicación o doble
    # pago: se cuenta una sola vez y se deja para revisión, nunca se descarta en silencio.
    previo = con.execute(
        "SELECT fuente_url FROM gastos WHERE huella = ?",
        (normalizar.huella("viatico", pid, inicio, destino, monto),)).fetchone()
    if previo and previo["fuente_url"] != fuente_url:
        con.execute(
            "INSERT OR IGNORE INTO sin_asignar (origen, nombre, monto, detalle, fuente_url, huella)"
            " VALUES (?,?,?,?,?,?)",
            ("posible_duplicado", nombre, monto, f"{detalle} · ya cargado desde {previo['fuente_url']}",
             fuente_url, normalizar.huella("dup", fuente_url, previo["fuente_url"])),
        )
        return "posible_duplicado"
    return "repetida"


def _filas_pdf(ruta: Path):
    import pdfplumber

    encontradas = []
    with pdfplumber.open(ruta) as pdf:
        # 1) Tabla con bordes: una celda por columna.
        for pagina in pdf.pages:
            for tabla in pagina.extract_tables():
                for fila in tabla:
                    celdas = [re.sub(r"\s+", " ", c or "").strip() for c in fila]
                    # Fila de datos = empieza con número correlativo y trae un monto.
                    if len(celdas) >= 7 and celdas[0].isdigit() and normalizar.monto(celdas[-1]):
                        encontradas.append(celdas[:6] + [celdas[-1]])
        # 2) Sin bordes: se lee cada renglón de texto con una expresión regular.
        if not encontradas:
            for pagina in pdf.pages:
                for linea in (pagina.extract_text() or "").splitlines():
                    m = _RENGLON.match(linea.strip())
                    if m:
                        encontradas.append(list(m.groups()))
    yield from encontradas


_RENGLON = re.compile(
    r"^(\d+)\s+(.+?)\s+(RES\.?\s*ADM\.?\s*N\S*\s*\d+)\s+(.+?)\s+"
    r"(\d{1,2}/\d{1,2}/\d{4}(?:\s+AL\s+\d{1,2}/\d{1,2}/\d{4})?)\s+(.*?)\s*\S*?\s*(\d{1,3}(?:\.\d{3})+)$",
    re.IGNORECASE,
)


def importar_pdf_diputados(con, ruta, fuente_url: str) -> dict:
    stats = {"nueva": 0, "repetida": 0, "posible_duplicado": 0, "sin_asignar": 0, "invalida": 0}
    for c in _filas_pdf(Path(ruta)):
        _, nombre, resolucion, destino, fechas, motivo, monto = c[:7]
        estado = _guardar_viaje(
            con, nombre=nombre, destino=destino, fechas=fechas, motivo=motivo,
            monto=normalizar.monto(monto), resolucion=resolucion, origen="diputados_viaticos",
            fuente_nombre="Cámara de Diputados — Viajes oficiales y misiones parlamentarias",
            fuente_url=fuente_url,
        )
        stats[estado] += 1
    con.commit()
    return stats


def importar_csv(con, ruta, origen: str = "viaticos_csv") -> dict:
    """CSV con columnas: nombre,destino,fecha_inicio,fecha_fin,motivo,monto,fuente_nombre,fuente_url
    Fechas en DD/MM/AAAA. Cada fila debe traer su propia fuente."""
    stats = {"nueva": 0, "repetida": 0, "posible_duplicado": 0, "sin_asignar": 0, "invalida": 0}
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        for fila in csv.DictReader(f):
            if not (fila.get("fuente_url") or "").startswith("http"):
                stats["invalida"] += 1
                continue
            estado = _guardar_viaje(
                con, nombre=fila["nombre"], destino=fila.get("destino", ""),
                fechas=f"{fila['fecha_inicio']} AL {fila.get('fecha_fin') or fila['fecha_inicio']}",
                motivo=fila.get("motivo", ""), monto=normalizar.monto(fila["monto"]), origen=origen,
                fuente_nombre=fila.get("fuente_nombre") or "Carga manual", fuente_url=fila["fuente_url"],
            )
            stats[estado] += 1
    con.commit()
    return stats
