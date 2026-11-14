"""Genera web/data.json: lo único que lee el frontend."""
import json
from pathlib import Path

from . import normalizar
from .db import RAIZ

SALIDA = RAIZ / "web" / "data.json"


def exportar(con, salida: Path = SALIDA) -> dict:
    personas = []
    for p in con.execute("SELECT * FROM personas ORDER BY nombre_completo"):
        gastos = [dict(g) for g in con.execute(
            "SELECT categoria, concepto, monto, periodo, fecha_inicio, fecha_fin, detalle,"
            " fuente_nombre, fuente_url, descargado_en FROM gastos WHERE persona_id = ?"
            " ORDER BY COALESCE(fecha_inicio, periodo) DESC, monto DESC", (p["id"],))]
        totales = {}
        for g in gastos:
            totales[g["categoria"]] = totales.get(g["categoria"], 0) + g["monto"]
        periodos = sorted({g["periodo"] for g in gastos if g["periodo"] != "s/f"})
        personas.append({
            "id": p["id"],
            "nombre": p["nombre_completo"],
            "cargo": p["cargo"],
            "poder": p["poder"],
            "institucion": p["institucion"],
            "total": sum(totales.values()),
            "totales": totales,
            "periodo_desde": periodos[0] if periodos else None,
            "periodo_hasta": periodos[-1] if periodos else None,
            "gastos": gastos,
        })
    datos = {
        "titulo": "¿Cuánto te cuestan tus políticos?",
        "generado_en": normalizar.ahora(),
        "aviso": ("Montos asignados a cada persona según fuentes oficiales. No incluye el gasto de las "
                  "instituciones que dirigen. Los datos dependen de lo que cada institución publica."),
        "personas": personas,
        "cobertura": [dict(c) for c in con.execute(
            "SELECT categoria, fuente_nombre AS fuente, MIN(periodo) AS desde, MAX(periodo) AS hasta,"
            " COUNT(*) AS registros FROM gastos GROUP BY categoria, fuente_nombre ORDER BY categoria")],
        "pendientes_revision": con.execute("SELECT COUNT(*) FROM sin_asignar").fetchone()[0],
    }
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"personas": len(personas), "archivo": str(salida)}
