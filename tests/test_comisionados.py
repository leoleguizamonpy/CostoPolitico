"""Comisionados: personal de otras instituciones en despachos. Datos FICTICIOS."""
import json
from pathlib import Path

import pytest

from costopolitico import personas
from costopolitico.db import conectar
from costopolitico.exportar import exportar
from costopolitico.fuentes import comisionados, sfp_nomina


@pytest.fixture
def con(tmp_path):
    c = conectar(tmp_path / "t.db")
    personas.guardar(c, nombre_completo="Rosa Elena Fantasía Benítez", nombres="ROSA ELENA",
                     apellidos="FANTASIA BENITEZ", cargo="Diputado/a", poder="legislativo",
                     institucion="Cámara de Diputados", silpy_id="800001")
    personas.guardar(c, nombre_completo="Marta Inventada Sosa", nombres="MARTA",
                     apellidos="INVENTADA SOSA", cargo="Senador/a", poder="legislativo",
                     institucion="Cámara de Senadores", silpy_id="800002")
    return c


def test_despacho_variantes():
    assert comisionados.despacho("PRESTA SERVICIOS DESPACHO LEGISLATIVO DEL DIPUTADO ROBERTO EJEMPLO") == \
        ("Diputado/a", "ROBERTO EJEMPLO")
    assert comisionados.despacho("PRESTA SERVICIOS EN EL DESPACHO DE LA SENADORA MARTA INVENTADA Nº 4177") == \
        ("Senador/a", "MARTA INVENTADA")
    assert comisionados.despacho("PRESTA SERVICIOS EN LA BANCADA \"A\" ANR.") is None
    assert comisionados.despacho("PRESTA SERVICIOS EN LA DIRECCION DE RELACIONES PUBLICAS") is None


def _pdf(ruta: Path, bordes: bool):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table

    st = getSampleStyleSheet()["BodyText"]
    p = lambda t: Paragraph(t, st)  # celdas que se parten en varios renglones, como en el PDF real
    filas = [
        ["Nº", "CEDULA", "NOMBRES APELLIDOS", "ENTIDAD DE ORIGEN", "FUNCION QUE CUMPLE", "RESOLUCION",
         "FECHA ACTO ADMINISTRATIVO", "FECHA DE FINALIZACION"],
        ["1", "700.001", "CARLOS PRUEBA UNO", p("MUNICIPALIDAD DE VILLA FICTICIA"),
         p("PRESTA SERVICIOS DESPACHO LEGISLATIVO DE LA DIPUTADA ROSA FANTASIA"), "Nº 5014", "01/02/2026", "31/12/2026"],
        ["2", "700.002", "LUCIA PRUEBA DOS", p("EMPRESA DE SERVICIOS DE PRUEBA"),
         p("PRESTA SERVICIOS EN EL DESPACHO DE LA SENADORA MARTA INVENTADA"), "Nº 4177", "08/04/2026", "31/12/2026"],
        ["3", "700.003", "JOSE PRUEBA TRES", p("MINISTERIO DE EJEMPLO"),
         p("PRESTA SERVICIOS EN LA DIRECCION DE SISTEMAS"), "Nº 5219", "16/03/2026", "31/12/2026"],
        ["4", "700.004", "ANA PRUEBA CUATRO", p("GOBERNACION DE PRUEBA"),
         p("PRESTA SERVICIOS DESPACHO LEGISLATIVO DEL DIPUTADO NADIE CONOCIDO"), "Nº 66", "12/07/2026", "31/12/2026"],
    ]
    estilo = [("GRID", (0, 0), (-1, -1), 0.5, "black")] if bordes else []
    SimpleDocTemplate(str(ruta), pagesize=landscape(A4)).build(
        [Paragraph("FUNCIONARIOS COMISIONADOS A LA HONORABLE CÁMARA DE DIPUTADOS ABRIL 2026",
                   getSampleStyleSheet()["Title"]),
         Table(filas, style=estilo, colWidths=[25, 60, 110, 120, 200, 55, 85, 85])])


@pytest.mark.parametrize("bordes", [True, False])
def test_importar_pdf(con, tmp_path, bordes):
    ruta = tmp_path / "c.pdf"
    _pdf(ruta, bordes)
    r = comisionados.importar_pdf(con, ruta, "https://ejemplo.invalid/c.pdf")
    assert r["filas"] == 4 and r["despacho"] == 3 and r["nuevas"] == 2 and r["sin_asignar"] == 1
    filas = {f["documento"]: dict(f) for f in con.execute("SELECT * FROM comisionados")}
    assert filas["700001"]["cargo_legislador"] == "Diputado/a" and filas["700001"]["desde"] == "2026-02-01"
    assert filas["700002"]["cargo_legislador"] == "Senador/a" and filas["700002"]["hasta"] == "2026-12-31"
    # Reimportar el mismo PDF no duplica.
    assert comisionados.importar_pdf(con, ruta, "https://ejemplo.invalid/c.pdf")["nuevas"] == 0


def test_sueldo_del_comisionado_va_al_legislador(con, tmp_path):
    ruta = tmp_path / "c.pdf"
    _pdf(ruta, True)
    comisionados.importar_pdf(con, ruta, "https://ejemplo.invalid/c.pdf")
    marta = con.execute("SELECT id FROM personas WHERE silpy_id='800002'").fetchone()["id"]
    rosa = con.execute("SELECT id FROM personas WHERE silpy_id='800001'").fetchone()["id"]
    firma_mar, firma_abr = comisionados.firma(con, "2026-03"), comisionados.firma(con, "2026-04")
    assert firma_mar != firma_abr  # Lucía empieza en abril: marzo no cambia por ella

    cab = "anho,mes,descripcion_entidad,documento,nombres,apellidos,cargo,funcion,objeto_gasto,concepto,presupuestado,devengado\n"
    filas = [
        # Comisionados: los paga otra institución.
        "{m},MUNICIPALIDAD DE VILLA FICTICIA,700001,CARLOS,PRUEBA UNO,AUXILIAR,COMISIONADO,111,SUELDOS,3000000,3000000",
        "{m},EMPRESA DE SERVICIOS DE PRUEBA,700002,LUCIA,PRUEBA DOS,TECNICA,COMISIONADA,111,SUELDOS,6000000,6000000",
        # No está en ningún despacho: no se suma a nadie.
        "{m},MINISTERIO DE EJEMPLO,700003,JOSE,PRUEBA TRES,TECNICO,SISTEMAS,111,SUELDOS,9000000,9000000",
    ]
    for mes in (3, 4):
        csv = tmp_path / f"n{mes}.csv"
        csv.write_text(cab + "\n".join(f.format(m=f"2026,{mes}") for f in filas) + "\n", encoding="utf-8")
        sfp_nomina.importar(con, csv)

    def tot(pid):
        return dict(con.execute("SELECT periodo, SUM(monto) FROM gastos WHERE persona_id=? AND categoria='asesores'"
                                " GROUP BY periodo", (pid,)).fetchall())
    assert tot(rosa) == {"2026-03": 3_000_000, "2026-04": 3_000_000}
    assert tot(marta) == {"2026-04": 6_000_000}  # en marzo todavía no estaba asignada
    assert con.execute("SELECT COUNT(*) FROM gastos WHERE monto=9000000").fetchone()[0] == 0

    out = tmp_path / "d.json"
    exportar(con, out)
    p = next(x for x in json.loads(out.read_text(encoding="utf-8"))["personas"] if x["id"] == marta)
    g = next(x for x in p["gastos"] if x["categoria"] == "asesores")
    assert "1 persona (1 comisionada de otras instituciones)" in g["concepto"]
    assert "Empresa De Servicios De Prueba" in g["detalle"]
    assert "LUCIA" not in json.dumps(p).upper() and "700002" not in json.dumps(p)


def test_personal_de_planta_no_se_cuenta_dos_veces(con, tmp_path):
    """Si la cédula está comisionada pero la nómina de la cámara ya lo muestra en el despacho,
    se cuenta una sola vez (como personal del despacho)."""
    con.execute("INSERT INTO comisionados (documento, persona_id, cargo_legislador, nombre_legislador, desde, hasta,"
                " fuente_url, descargado_en, huella) VALUES ('700009', 1, 'Diputado/a', 'Rosa Fantasia',"
                " '2026-01-01', '2026-12-31', 'x', 'x', 'h')")
    csv = tmp_path / "n.csv"
    csv.write_text(
        "anho,mes,descripcion_entidad,documento,nombres,apellidos,cargo,funcion,objeto_gasto,concepto,presupuestado,devengado\n"
        "2026,4,CAMARA DE DIPUTADOS,700009,EVA,PRUEBA,JORNALES,DESPACHO LEGISLATIVO DE LA DIPUTADA ROSA FANTASIA,144,JORNALES,4000000,4000000\n",
        encoding="utf-8")
    r = sfp_nomina.importar(con, csv)
    assert r["personal_despacho"] == 1 and r["comisionados"] == 0
