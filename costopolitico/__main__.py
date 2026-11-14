"""Línea de comandos.

  python -m costopolitico nomina  RUTA_CSV_O_ZIP [--url URL]
  python -m costopolitico diputados-pdf RUTA_PDF --url URL_DEL_PDF
  python -m costopolitico viaticos-csv RUTA_CSV
  python -m costopolitico pendientes
  python -m costopolitico exportar
"""
import argparse

from .db import conectar
from .exportar import exportar
from .fuentes import sfp_nomina, viaticos


def main():
    ap = argparse.ArgumentParser(prog="costopolitico")
    ap.add_argument("--db", help="ruta a la base SQLite (por defecto data/costopolitico.db)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("nomina", help="importar CSV/ZIP mensual de la nómina SFP")
    s.add_argument("ruta")
    s.add_argument("--url", default=sfp_nomina.URL_PORTAL)

    s = sub.add_parser("diputados-pdf", help="importar PDF mensual de viáticos de Diputados")
    s.add_argument("ruta")
    s.add_argument("--url", required=True, help="URL pública del PDF (queda como fuente)")

    s = sub.add_parser("viaticos-csv", help="importar viáticos desde la plantilla CSV")
    s.add_argument("ruta")

    sub.add_parser("pendientes", help="listar filas que no se pudieron asignar")
    sub.add_parser("exportar", help="generar web/data.json")

    a = ap.parse_args()
    con = conectar(a.db)
    if a.cmd == "nomina":
        print(sfp_nomina.importar(con, a.ruta, a.url))
    elif a.cmd == "diputados-pdf":
        print(viaticos.importar_pdf_diputados(con, a.ruta, a.url))
    elif a.cmd == "viaticos-csv":
        print(viaticos.importar_csv(con, a.ruta))
    elif a.cmd == "pendientes":
        for f in con.execute("SELECT origen, nombre, monto, detalle FROM sin_asignar ORDER BY origen, nombre"):
            print(f"[{f['origen']}] {f['nombre']} — ₲ {f['monto']:,} — {f['detalle']}".replace(",", "."))
    elif a.cmd == "exportar":
        print(exportar(con))


if __name__ == "__main__":
    main()
