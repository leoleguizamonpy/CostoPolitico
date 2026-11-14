"""Línea de comandos.

  python -m costopolitico nomina  RUTA_CSV_O_ZIP [--url URL]   (un archivo suelto)
  python -m costopolitico sueldos [--desde 2023-07]         (baja e importa los meses de la SFP)
  python -m costopolitico diputados-pdf RUTA_PDF --url URL_DEL_PDF
  python -m costopolitico viaticos-csv RUTA_CSV
  python -m costopolitico senado [--desde 2023]
  python -m costopolitico diputados [--desde 2023]
  python -m costopolitico actualizar [--desde 2023]   (todo lo automático + exportar)
  python -m costopolitico pendientes
  python -m costopolitico exportar
"""
import argparse

from .db import conectar
from .exportar import exportar
from .fuentes import diputados, senado, sfp_nomina, viaticos


def _mes(texto: str) -> tuple[int, int]:
    a, m = texto.split("-")
    return int(a), int(m)


def _pendientes(con, ruta_csv=None):
    """Agrupa por nombre: un mismo funcionario puede tener decenas de viajes."""
    import csv

    from . import personas

    filas = con.execute(
        "SELECT origen, nombre, COUNT(*) AS n, SUM(monto) AS total, MIN(fuente_url) AS ejemplo"
        " FROM sin_asignar GROUP BY origen, nombre ORDER BY total DESC").fetchall()
    salida = []
    for f in filas:
        sug = personas.sugerencias(con, f["nombre"]) if f["origen"] != "posible_duplicado" else []
        mejor = sug[0] if sug else None
        linea = f"[{f['origen']}] {f['nombre']} — {f['n']} registro(s), ₲ {f['total'] or 0:,}".replace(",", ".")
        if mejor and mejor[0] >= 0.75:
            linea += f"  → ¿{mejor[1]} ({mejor[2]}, id {mejor[3]})? parecido {mejor[0]}"
        print(linea)
        salida.append({"origen": f["origen"], "nombre_fuente": f["nombre"], "registros": f["n"],
                       "monto_total": f["total"] or 0, "ejemplo_fuente": f["ejemplo"],
                       **{f"sugerencia_{i + 1}": f"{s_[1]} | {s_[2]} | id {s_[3]} | {s_[0]}" for i, s_ in enumerate(sug)}})
    if ruta_csv and salida:
        campos = list(dict.fromkeys(k for fila in salida for k in fila))
        with open(ruta_csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=campos)
            w.writeheader()
            w.writerows(salida)
        print(f"\nCSV para revisar: {ruta_csv}. Para corregir, copiá nombre_fuente y el id elegido"
              " a data/alias.csv (columna silpy_id o documento) y volvé a correr la importación.")


def main():
    ap = argparse.ArgumentParser(prog="costopolitico")
    ap.add_argument("--db", help="ruta a la base SQLite (por defecto data/costopolitico.db)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("nomina", help="importar CSV/ZIP mensual de la nómina SFP")
    s.add_argument("ruta")
    s.add_argument("--url", default=sfp_nomina.URL_PORTAL)

    s = sub.add_parser("sueldos", help="bajar e importar la nómina mensual de la SFP (meses nuevos)")
    s.add_argument("--desde", default="2023-07", help="AAAA-MM (por defecto, inicio del período 2023-2028)")

    s = sub.add_parser("diputados-pdf", help="importar PDF mensual de viáticos de Diputados")
    s.add_argument("ruta")
    s.add_argument("--url", required=True, help="URL pública del PDF (queda como fuente)")

    s = sub.add_parser("viaticos-csv", help="importar viáticos desde la plantilla CSV")
    s.add_argument("ruta")

    s = sub.add_parser("senado", help="bajar nómina de senadores y viajes con viáticos desde senado.gov.py")
    s.add_argument("--desde", type=int, default=2023, help="año desde el que se bajan misiones")

    s = sub.add_parser("diputados", help="bajar nómina de diputados y planillas de viáticos")
    s.add_argument("--desde", type=int, default=2023)

    s = sub.add_parser("actualizar", help="nóminas, sueldos, viajes y exportación (para cron)")
    s.add_argument("--desde", type=int, default=2023, help="año desde el que se bajan los viajes")
    s.add_argument("--sueldos-desde", default="2023-07", help="AAAA-MM desde el que se bajan sueldos")

    s = sub.add_parser("pendientes", help="listar lo que no se pudo asignar (con sugerencias)")
    s.add_argument("--csv", help="además, escribir un CSV para revisar (p.ej. data/revision.csv)")
    sub.add_parser("exportar", help="generar web/data.json")

    a = ap.parse_args()
    con = conectar(a.db)
    if a.cmd == "nomina":
        print(sfp_nomina.importar(con, a.ruta, a.url))
    elif a.cmd == "sueldos":
        print(sfp_nomina.descargar_meses(con, desde=_mes(a.desde)))
    elif a.cmd == "diputados-pdf":
        print(viaticos.importar_pdf_diputados(con, a.ruta, a.url))
    elif a.cmd == "viaticos-csv":
        print(viaticos.importar_csv(con, a.ruta))
    elif a.cmd == "senado":
        print(senado.descargar_todo(con, desde_anho=a.desde))
    elif a.cmd == "diputados":
        print("nómina:", diputados.descargar_nomina(con))
        print("viáticos:", diputados.descargar_viaticos(con, desde_anho=a.desde))
    elif a.cmd == "actualizar":
        # Orden: primero las nóminas (las personas), después sueldos y viajes que se cruzan con ellas.
        # Si una fuente falla, se sigue con las demás y la web se genera igual con lo que haya.
        pasos = [
            ("diputados — nómina", lambda: diputados.descargar_nomina(con)),
            ("senado", lambda: senado.descargar_todo(con, desde_anho=a.desde)),
            ("sueldos (SFP)", lambda: sfp_nomina.descargar_meses(con, desde=_mes(a.sueldos_desde))),
            ("diputados — viáticos", lambda: diputados.descargar_viaticos(con, desde_anho=a.desde)),
        ]
        fallas = []
        for nombre, paso in pasos:
            try:
                print(f"{nombre}:", paso(), flush=True)
            except Exception as e:  # noqa: BLE001 - se informa y se sigue
                con.rollback()
                fallas.append(nombre)
                print(f"AVISO: falló «{nombre}»: {type(e).__name__}: {str(e)[:300]}", flush=True)
        print(exportar(con))
        if fallas:
            print("Terminó con fallas en:", ", ".join(fallas))
            raise SystemExit(2)
    elif a.cmd == "pendientes":
        _pendientes(con, a.csv)
    elif a.cmd == "exportar":
        print(exportar(con))


if __name__ == "__main__":
    main()
