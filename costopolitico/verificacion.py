"""Verificación de los datos antes de publicar.

1. controles(): revisiones automáticas de consistencia sobre toda la base. No corrigen nada:
   señalan lo que hay que mirar, con el motivo.
2. muestra(): planilla con una muestra aleatoria estratificada de gastos, con el enlace a la
   fuente de cada uno, para comparar a mano. resultado_muestra() calcula la tasa de error con su
   intervalo de confianza a partir de la planilla completada.
"""
import csv
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from .db import RAIZ

CARPETA = RAIZ / "data" / "verificacion"


# ---------------------------------------------------------------- controles automáticos

def controles(con) -> dict:
    """Devuelve {'hallazgos': [(nivel, control, detalle)], 'resumen': {...}}.
    nivel: 'error' (casi seguro un problema), 'revisar' (puede estar bien), 'info'."""
    h = []

    def agregar(nivel, control, detalle):
        h.append((nivel, control, detalle))

    personas = {p["id"]: p for p in con.execute("SELECT * FROM personas")}

    # 1. Dietas y sueldos: dentro de un mismo cargo, el monto mensual suele ser igual para todos.
    #    Se señalan quienes se apartan mucho de lo habitual (moda) de su cargo en ese mes.
    por_mes = defaultdict(lambda: defaultdict(int))
    for f in con.execute("SELECT persona_id, periodo, SUM(monto) AS m FROM gastos"
                         " WHERE categoria='remuneracion' GROUP BY persona_id, periodo"):
        por_mes[(personas[f["persona_id"]]["cargo"], f["periodo"])][f["persona_id"]] = f["m"]
    for (cargo, periodo), montos in sorted(por_mes.items()):
        if len(montos) < 5 or not cargo.startswith(("Senador", "Diputado")):
            continue
        habitual = Counter(montos.values()).most_common(1)[0][0]
        for pid, m in montos.items():
            if habitual and abs(m - habitual) / habitual > 0.25:
                agregar("revisar", "Remuneración atípica",
                        f"{personas[pid]['nombre_completo']} ({cargo}), {periodo}: ₲ {m:,} "
                        f"vs. lo habitual ₲ {habitual:,}".replace(",", "."))

    # 2. Más de una dieta/sueldo base en el mismo mes (posible duplicado de la fuente).
    for f in con.execute("SELECT persona_id, periodo, concepto, COUNT(*) n FROM gastos"
                         " WHERE categoria='remuneracion' AND concepto IN ('Dieta','Sueldo')"
                         " GROUP BY persona_id, periodo, concepto HAVING n > 1"):
        agregar("revisar", "Dos sueldos o dietas en un mes",
                f"{personas[f['persona_id']]['nombre_completo']}, {f['periodo']}: {f['n']} líneas de «{f['concepto']}»")

    # 3. Viáticos: devoluciones mayores al asignado, montos en cero, viajes muy caros.
    for f in con.execute("SELECT persona_id, detalle, monto, fecha_inicio FROM gastos WHERE categoria='viatico'"):
        nombre = personas[f["persona_id"]]["nombre_completo"]
        if "ATENCIÓN" in (f["detalle"] or ""):
            agregar("error", "Devolución mayor al asignado (dato de la fuente)", f"{nombre}, {f['fecha_inicio']}")
    montos_v = [f["monto"] for f in con.execute("SELECT monto FROM gastos WHERE categoria='viatico' AND monto > 0")]
    if len(montos_v) >= 20:
        q = statistics.quantiles(montos_v, n=100)
        p99 = q[98]
        for f in con.execute("SELECT persona_id, concepto, monto, fecha_inicio, fuente_url FROM gastos"
                             " WHERE categoria='viatico' AND monto > ?", (p99,)):
            agregar("revisar", "Viático muy alto (1 % más caro)",
                    f"{personas[f['persona_id']]['nombre_completo']}, {f['fecha_inicio']}, {f['concepto']}: "
                    f"₲ {f['monto']:,} — {f['fuente_url']}".replace(",", "."))

    # 4. Viajes con fechas imposibles (fin antes del inicio, o más de 30 días).
    for f in con.execute("SELECT persona_id, fecha_inicio, fecha_fin, concepto FROM gastos"
                         " WHERE categoria='viatico' AND fecha_fin IS NOT NULL"):
        d = (date.fromisoformat(f["fecha_fin"]) - date.fromisoformat(f["fecha_inicio"])).days
        if d < 0 or d > 30:
            agregar("revisar", "Fechas de viaje raras",
                    f"{personas[f['persona_id']]['nombre_completo']}: {f['fecha_inicio']} a {f['fecha_fin']} ({f['concepto']})")

    # 5. Cruces de nombres no exactos (quedan anotados en el detalle).
    aprox = Counter()
    for f in con.execute("SELECT detalle FROM gastos WHERE detalle LIKE '%cruce %'"):
        for metodo in ("nombre corto", "solo apellidos", "aproximado", "alias"):
            if f"cruce {metodo}" in f["detalle"]:
                aprox[metodo] += 1
    for metodo, n in aprox.items():
        agregar("revisar" if metodo == "aproximado" else "info", "Cruces de nombre no exactos",
                f"{n} gastos asignados por «{metodo}» (ver detalle de cada gasto)")

    # 6. Posibles duplicados y pendientes sin asignar.
    for f in con.execute("SELECT origen, COUNT(*) n, SUM(monto) m FROM sin_asignar GROUP BY origen"):
        nivel = "revisar" if f["origen"] == "posible_duplicado" else "info"
        agregar(nivel, "Sin asignar / para revisar",
                f"{f['origen']}: {f['n']} registros, ₲ {f['m'] or 0:,}".replace(",", "."))

    # 7. Cobertura: legisladores sin sueldo cargado y meses con pocas personas.
    sin_sueldo = [p["nombre_completo"] for p in personas.values() if p["poder"] == "legislativo"
                  and not con.execute("SELECT 1 FROM gastos WHERE persona_id=? AND categoria='remuneracion'",
                                      (p["id"],)).fetchone()]
    if sin_sueldo:
        agregar("revisar", "Legisladores sin ningún sueldo cargado",
                f"{len(sin_sueldo)}: " + ", ".join(sin_sueldo[:15]) + (" …" if len(sin_sueldo) > 15 else ""))
    cobertura = {f["periodo"]: f["n"] for f in con.execute(
        "SELECT periodo, COUNT(DISTINCT persona_id) n FROM gastos WHERE categoria='remuneracion' GROUP BY periodo")}
    if cobertura:
        maximo = max(cobertura.values())
        for periodo, n in sorted(cobertura.items()):
            if n < 0.9 * maximo:
                agregar("revisar", "Mes con sueldos incompletos",
                        f"{periodo}: {n} personas con sueldo (el mes más completo tiene {maximo})")

    # 8. Montos que no pueden ser.
    for f in con.execute("SELECT COUNT(*) n FROM gastos WHERE monto < 0"):
        if f["n"]:
            agregar("error", "Montos negativos", f"{f['n']} gastos")

    resumen = Counter(n for n, _, _ in h)
    return {"hallazgos": h, "resumen": dict(resumen)}


def informe_controles(con, ruta: Path | None = None) -> Path:
    r = controles(con)
    ruta = ruta or CARPETA / f"controles-{date.today():%Y-%m-%d}.md"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    lineas = [f"# Controles automáticos — {date.today():%d/%m/%Y}", "",
              f"Errores: {r['resumen'].get('error', 0)} · Para revisar: {r['resumen'].get('revisar', 0)}"
              f" · Información: {r['resumen'].get('info', 0)}", ""]
    for nivel in ("error", "revisar", "info"):
        items = [x for x in r["hallazgos"] if x[0] == nivel]
        if not items:
            continue
        lineas += [f"## {dict(error='Errores', revisar='Para revisar', info='Información')[nivel]}", ""]
        actual = None
        for _, control, detalle in items:
            if control != actual:
                lineas += ["", f"### {control}", ""]
                actual = control
            lineas.append(f"- {detalle}")
        lineas.append("")
    ruta.write_text("\n".join(lineas), encoding="utf-8")
    return ruta


# ---------------------------------------------------------------- verificación por muestreo

COLUMNAS = ["n", "persona", "cargo", "categoria", "concepto", "periodo", "fecha", "monto_app",
            "detalle", "fuente_url", "monto_en_fuente", "coincide", "nota"]


def muestra(con, n: int = 60, semilla: int | None = None, ruta: Path | None = None) -> Path:
    """Planilla con n gastos al azar para comparar contra la fuente.

    Estratificada para que entren todas las situaciones: se reparte entre categorías (sueldo,
    viático, personal de despacho) y se sobrerrepresentan los cruces de nombre no exactos, que son
    los de mayor riesgo. La semilla queda escrita en el archivo para poder repetir la muestra."""
    semilla = semilla if semilla is not None else random.randrange(10**6)
    azar = random.Random(semilla)
    filas = [dict(f) for f in con.execute(
        "SELECT g.*, p.nombre_completo AS persona, p.cargo FROM gastos g JOIN personas p ON p.id = g.persona_id")]
    if not filas:
        raise SystemExit("No hay gastos cargados para muestrear.")
    estratos = defaultdict(list)
    for f in filas:
        riesgo = "aprox" if any(m in (f["detalle"] or "") for m in ("cruce aproximado", "cruce solo apellidos",
                                                                    "cruce nombre corto")) else "normal"
        estratos[(f["categoria"], riesgo)].append(f)
    # Reparto: la mitad proporcional al tamaño, la otra mitad pareja entre estratos (y doble peso a "aprox").
    pesos = {k: len(v) / len(filas) * 0.5 + (0.5 / len(estratos)) * (2 if k[1] == "aprox" else 1)
             for k, v in estratos.items()}
    total_pesos = sum(pesos.values())
    elegidos = []
    for k, v in estratos.items():
        cuantos = min(len(v), max(1, round(n * pesos[k] / total_pesos)))
        elegidos += azar.sample(v, cuantos)
    azar.shuffle(elegidos)
    ruta = ruta or CARPETA / f"muestra-{date.today():%Y-%m-%d}-semilla{semilla}.csv"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS)
        w.writeheader()
        for i, f in enumerate(elegidos, 1):
            w.writerow({"n": i, "persona": f["persona"], "cargo": f["cargo"], "categoria": f["categoria"],
                        "concepto": f["concepto"], "periodo": f["periodo"], "fecha": f["fecha_inicio"] or "",
                        "monto_app": f["monto"], "detalle": f["detalle"] or "", "fuente_url": f["fuente_url"],
                        "monto_en_fuente": "", "coincide": "", "nota": ""})
    return ruta


def _wilson(errores: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de confianza del 95 % para una proporción (método de Wilson; sirve con pocos casos)."""
    if n == 0:
        return 0.0, 1.0
    p = errores / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centro - margen), min(1.0, centro + margen)


def resultado_muestra(ruta: Path) -> dict:
    """Lee la planilla completada. En 'coincide' se escribe sí / no (o se deja vacío si no se revisó).
    Si 'monto_en_fuente' está completo y difiere de 'monto_app', cuenta como error aunque diga sí."""
    revisadas, errores, detalle = 0, 0, []
    with open(ruta, newline="", encoding="utf-8-sig") as fh:
        for f in csv.DictReader(fh):
            c = (f.get("coincide") or "").strip().lower()
            if not c:
                continue
            revisadas += 1
            en_fuente = "".join(ch for ch in (f.get("monto_en_fuente") or "") if ch.isdigit())
            difiere = en_fuente and int(en_fuente) != int(f["monto_app"])
            if c in ("no", "n", "0", "false") or difiere:
                errores += 1
                detalle.append(f"#{f['n']} {f['persona']} — {f['concepto']}: app ₲ {int(f['monto_app']):,}"
                               f"{' / fuente ₲ ' + format(int(en_fuente), ',') if en_fuente else ''}"
                               f"{' — ' + f['nota'] if f.get('nota') else ''}".replace(",", "."))
    bajo, alto = _wilson(errores, revisadas)
    return {"revisadas": revisadas, "errores": errores,
            "tasa_error": errores / revisadas if revisadas else None,
            "intervalo_95": (bajo, alto), "detalle": detalle}
