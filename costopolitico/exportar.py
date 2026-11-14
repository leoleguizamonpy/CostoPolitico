"""Genera web/data.json: lo único que lee el frontend."""
import json
from pathlib import Path

import re

from . import normalizar
from .fuentes.silpy import movimiento
from .db import RAIZ

SALIDA = RAIZ / "web" / "data.json"


def _partido_corto(partido: str | None) -> str | None:
    """'Asociación Nacional Republicana ANR' -> 'ANR'; sin sigla, el nombre completo."""
    if not partido:
        return None
    m = re.search(r"\b([A-ZÑ]{2,6})\s*$", partido.strip())
    if m and not partido.isupper():  # sigla al final de un nombre escrito normal
        return m.group(1)
    nombre = re.sub(r"^(PARTIDO)\s+", "", partido.strip(), flags=re.IGNORECASE)
    return nombre.title() if nombre.isupper() else nombre


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def _agrupar_remuneraciones(gastos: list[dict]) -> list[dict]:
    """Un renglón por mes para remuneraciones (dieta + representación + …) y para el personal
    del despacho (cantidad de personas y desglose por cargo, sin nombres). Los viáticos quedan
    uno por viaje."""
    otros, por_mes = [], {}
    for g in gastos:
        if g["categoria"] not in ("remuneracion", "asesores") or g["periodo"] == "s/f":
            otros.append(g)
            continue
        m = por_mes.setdefault((g["categoria"], g["periodo"]), {**g, "monto": 0, "partes": {}, "refs": set()})
        m["monto"] += g["monto"]
        clave = g["concepto"] if g["categoria"] == "remuneracion" else (g.get("detalle") or "").split(" · ")[0].title()
        m["partes"][clave] = m["partes"].get(clave, 0) + g["monto"]
        if g.get("referencia"):
            m["refs"].add(g["referencia"])
    for (categoria, periodo), m in por_mes.items():
        a, mm = periodo.split("-")
        mes = f"{MESES[int(mm) - 1]} {a}"
        n = len(m.pop("refs"))
        m["concepto"] = (f"Remuneración de {mes}" if categoria == "remuneracion"
                         else f"Personal del despacho de {mes}: {n} persona{'s' if n != 1 else ''}")
        m["detalle"] = " · ".join(f"{k}: ₲ {v:,}".replace(",", ".") for k, v in
                                  sorted(m.pop("partes").items(), key=lambda kv: -kv[1]))
        m.pop("referencia", None)
        otros.append(m)
    for g in otros:
        g.pop("referencia", None)  # identificador interno: no se publica
    return sorted(otros, key=lambda g: (g.get("fecha_inicio") or g["periodo"]), reverse=True)


def _verificacion():
    ruta = RAIZ / "data" / "verificacion" / "ultima.json"
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None


def exportar(con, salida: Path = SALIDA) -> dict:
    personas = []
    for p in con.execute("SELECT * FROM personas ORDER BY nombre_completo"):
        gastos = [dict(g) for g in con.execute(
            "SELECT categoria, concepto, monto, periodo, fecha_inicio, fecha_fin, detalle,"
            " fuente_nombre, fuente_url, descargado_en, referencia FROM gastos WHERE persona_id = ?"
            " ORDER BY COALESCE(fecha_inicio, periodo) DESC, monto DESC", (p["id"],))]
        gastos = _agrupar_remuneraciones(gastos)
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
            "partido": _partido_corto(p["partido"]),
            "partido_nombre": p["partido"],
            "bancada": p["bancada"],
            "movimiento": movimiento(p["bancada"], p["partido"]),
            "suplente": bool(p["representante"] and "SUPLENTE" in p["representante"].upper()),
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
        "verificacion": _verificacion(),
        "pendientes_revision": con.execute("SELECT COUNT(*) FROM sin_asignar").fetchone()[0],
    }
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"personas": len(personas), "archivo": str(salida)}
