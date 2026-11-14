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

    sub.add_parser("pendientes", help="listar filas que no se pudieron asignar")
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
        # Orden: primero las nóminas (las personas), después los viajes que se cruzan con ellas.
        print("diputados — nómina:", diputados.descargar_nomina(con))
        print("senado:", senado.descargar_todo(con, desde_anho=a.desde))
        print("sueldos (SFP):", sfp_nomina.descargar_meses(con, desde=_mes(a.sueldos_desde)))
        print("diputados — viáticos:", diputados.descargar_viaticos(con, desde_anho=a.desde))
        print(exportar(con))
    elif a.cmd == "pendientes":
        for f in con.execute("SELECT origen, nombre, monto, detalle FROM sin_asignar ORDER BY origen, nombre"):
            print(f"[{f['origen']}] {f['nombre']} — ₲ {f['monto']:,} — {f['detalle']}".replace(",", "."))
    elif a.cmd == "exportar":
        print(exportar(con))


if __name__ == "__main__":
    main()
