"""Pruebas con datos FICTICIOS que imitan el formato real de cada fuente.
Ningún nombre ni monto de estos archivos corresponde a una persona real."""
import json
from pathlib import Path

import pytest

from costopolitico import normalizar
from costopolitico.db import conectar
from costopolitico.exportar import exportar
from costopolitico.fuentes import sfp_nomina, viaticos

FIX = Path(__file__).parent / "fixtures"

NOMINA = """anho,mes,descripcion_entidad,documento,nombres,apellidos,cargo,objeto_gasto,concepto,presupuestado,devengado
2026,9,CAMARA DE SENADORES,1000001,ANA MARIA,PRUEBA GOMEZ,SENADORA NACIONAL,111,SUELDOS,40000000,40000000
2026,9,CAMARA DE SENADORES,1000001,ANA MARIA,PRUEBA GOMEZ,SENADORA NACIONAL,113,GASTOS DE REPRESENTACION,12000000,12000000
2026,9,CAMARA DE DIPUTADOS,1000002,JUAN CARLOS,EJEMPLO RUIZ,DIPUTADO NACIONAL,111,SUELDOS,"38.000.000","38.000.000"
2026,9,CAMARA DE DIPUTADOS,1000003,PEDRO,FICTICIO,ASESOR,144,JORNALES,5000000,5000000
2026,9,MINISTERIO DE SALUD PUBLICA,1000004,LUISA,DEMO VERA,MINISTRA,111,SUELDOS,37000000,37000000
2026,9,MINISTERIO DE SALUD PUBLICA,1000005,MARIO,MUESTRA,VICEMINISTRO,111,SUELDOS,30000000,30000000
"""


def _pdf_diputados(ruta: Path, bordes: bool = True):
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.platypus import SimpleDocTemplate, Table, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet

    filas = [
        ["Nº DE VIAJES", "DIPUTADO/A O FUNCIONARIO/A", "RESOLUCIÓN", "DESTINO", "FECHA", "MOTIVO", "MONTO DEL VIÁTICO TOTAL"],
        ["1", "JUAN CARLOS EJEMPLO RUIZ", "RES. ADM. Nº 9001", "MONTEVIDEO, URUGUAY", "03/09/2026 AL 05/09/2026", "SESION PLENARIA", "₲ 5.000.000"],
        ["2", "JUAN CARLOS EJEMPLO RUIZ", "RES. ADM. Nº 9002", "MADRID, ESPAÑA", "20/09/2026 AL 25/09/2026", "CURSO", "₲ 11.250.500"],
        ["3", "ROSA FUNCIONARIA TEST", "RES. ADM. Nº 9003", "LIMA, PERU", "10/09/2026 AL 12/09/2026", "TALLER", "₲ 4.100.000"],
    ]
    estilo = [("GRID", (0, 0), (-1, -1), 0.5, "black")] if bordes else []
    SimpleDocTemplate(str(ruta), pagesize=landscape(A4)).build(
        [Paragraph("SETIEMBRE AÑO 2026", getSampleStyleSheet()["Title"]), Table(filas, style=estilo)]
    )


@pytest.fixture
def con(tmp_path):
    return conectar(tmp_path / "t.db")


def test_normalizar():
    assert normalizar.nombre("Carlos  Alberto Núñez") == "CARLOS ALBERTO NUNEZ"
    assert normalizar.monto("₲ 5.073.097") == 5073097
    assert normalizar.monto("Gs. 1.234,50") == 1234
    assert normalizar.monto("") is None
    assert normalizar.monto("8000000.0") == 8000000      # decimal con punto, no miles
    assert normalizar.monto("123.45") == 123
    assert normalizar.monto("1.234") == 1234             # grupo de 3 dígitos: miles
    assert normalizar.monto("7400000") == 7400000
    assert normalizar.rango_fechas("29/01/2025 AL 02/02/2025") == ("2025-01-29", "2025-02-02")


def test_flujo_completo(con, tmp_path):
    csv_path = tmp_path / "nomina.csv"
    csv_path.write_text(NOMINA, encoding="utf-8")
    r = sfp_nomina.importar(con, csv_path)
    assert r["politicos"] == 4  # senadora (2 filas), diputado, ministra; no asesor ni viceministro
    cargos = {p["nombre_norm"]: p["cargo"] for p in con.execute("SELECT * FROM personas")}
    assert cargos == {
        "ANA MARIA PRUEBA GOMEZ": "Senador/a",
        "JUAN CARLOS EJEMPLO RUIZ": "Diputado/a",
        "LUISA DEMO VERA": "Ministro/a",
    }
    # Reimportar no duplica.
    assert sfp_nomina.importar(con, csv_path)["gastos_nuevos"] == 0

    pdf = tmp_path / "viajes.pdf"
    _pdf_diputados(pdf)
    r = viaticos.importar_pdf_diputados(con, pdf, "https://www.diputados.gov.py/ejemplo.pdf")
    assert r == {"nueva": 2, "repetida": 0, "posible_duplicado": 0, "sin_asignar": 1, "invalida": 0}

    salida = tmp_path / "data.json"
    exportar(con, salida)
    datos = json.loads(salida.read_text(encoding="utf-8"))
    dip = next(p for p in datos["personas"] if p["cargo"] == "Diputado/a")
    assert dip["totales"] == {"remuneracion": 38_000_000, "viatico": 16_250_500}
    assert all(g["fuente_url"].startswith("http") for g in dip["gastos"])
    sen = next(p for p in datos["personas"] if p["cargo"] == "Senador/a")
    assert sen["total"] == 52_000_000
    assert datos["pendientes_revision"] == 1


@pytest.mark.parametrize("bordes", [True, False])
def test_pdf_con_y_sin_bordes(con, tmp_path, bordes):
    csv_path = tmp_path / "nomina.csv"
    csv_path.write_text(NOMINA, encoding="utf-8")
    sfp_nomina.importar(con, csv_path)
    pdf = tmp_path / "v.pdf"
    _pdf_diputados(pdf, bordes)
    r = viaticos.importar_pdf_diputados(con, pdf, "https://www.diputados.gov.py/ejemplo.pdf")
    assert r == {"nueva": 2, "repetida": 0, "posible_duplicado": 0, "sin_asignar": 1, "invalida": 0}
    montos = sorted(g[0] for g in con.execute("SELECT monto FROM gastos WHERE categoria='viatico'"))
    assert montos == [5_000_000, 11_250_500]


def test_viaticos_csv_exige_fuente(con, tmp_path):
    p = tmp_path / "v.csv"
    p.write_text(
        "nombre,destino,fecha_inicio,fecha_fin,motivo,monto,fuente_nombre,fuente_url\n"
        "X,Y,01/09/2026,02/09/2026,Z,1000,Senado,\n", encoding="utf-8")
    assert viaticos.importar_csv(con, p)["invalida"] == 1


def test_reglas_nomina_con_casos_reales():
    from costopolitico.personas import clasificar
    c = lambda e, car, f="": (clasificar(e, car, f) or {}).get("titulo")
    assert c("CAMARA DE SENADORES", "MIEMBROS", "SENADOR NACIONAL") == "Senador/a"
    assert c("CAMARA DE SENADORES", "JORNALES", "DESPACHO DEL SENADOR DIONISIO AMARILLA") is None
    assert c("CAMARA DE DIPUTADOS", "DIPUTADO NACIONAL", "PRESIDENTE H.C.D.") == "Diputado/a"
    assert c("CAMARA DE DIPUTADOS", "", "PRESTA SERVICIOS EN EL DESPACHO LEGISLATIVO DEL DIPUTADO X") is None
    assert c("CAMARA DE DIPUTADOS", "ASESOR", "DESPACHO DEL SENADOR JUAN AFARA") is None
    assert c("PRESIDENCIA DE LA REPUBLICA", "PRESIDENTE DE LA REPUBLICA") == "Presidente/a de la República"
    assert c("VICE PRESIDENCIA DE LA REPUBLICA", "VICEPRESIDENTE", "VICEPRESIDENTE") == "Vicepresidente/a de la República"
    assert c("VICE PRESIDENCIA DE LA REPUBLICA", "COMISIONADO/A", "CÁMARA DE SENADORES") is None
    assert c("PRESIDENCIA DE LA REPUBLICA", "SECRETARIO EJECUTIVO", "MINISTRO SECRETARIO EJECUTIVO") == "Ministro/a (Presidencia)"
    assert c("MINISTERIO DEL INTERIOR", "MINISTRO", "MINISTRO") == "Ministro/a"
    assert c("MINISTERIO DE SALUD PUBLICA Y BIENESTAR SOCIAL", "MINISTRO/MINISTRA DE SALUD", "MINISTRO A") == "Ministro/a"
    assert c("MINISTERIO DE ECONOMIA Y FINANZAS (MEF)", "VICEMINISTRO", "VICEMINISTRO") is None
    assert c("MINISTERIO DE RELACIONES EXTERIORES", "MINISTRO", "NO DISPONIBLE") is None  # rango diplomático
    assert c("MINISTERIO PUBLICO", "MINISTRO", "") is None
    assert c("MINISTERIO DE LA DEFENSA PUBLICA", "MINISTRO", "") is None


def test_zip_latin1_y_meses(con, tmp_path):
    import zipfile
    texto = ("anho,mes,descripcion_entidad,documento,nombres,apellidos,cargo,funcion,objeto_gasto,concepto,presupuestado,devengado\r\n"
             "2026,4,MINISTERIO DE AGRICULTURA Y GANADERÍA,3000001,ÑANDÚ,PEÑA PRUEBA,MINISTRO,MINISTRO,111,SUELDO,22000000,22000000\r\n"
             "2026,4,MINISTERIO DE AGRICULTURA Y GANADERÍA,3000001,ÑANDÚ,PEÑA PRUEBA,MINISTRO,MINISTRO,232,VIATICOS,500000,500000\r\n"
             "2026,4,MINISTERIO DE AGRICULTURA Y GANADERÍA,3000001,ÑANDÚ,PEÑA PRUEBA,MINISTRO,MINISTRO,232,VIATICOS,500000,500000\r\n")
    z = tmp_path / "funcionarios_2026_4.csv.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        f.writestr("funcionarios_2026_4.csv", texto.encode("latin-1"))
    r = sfp_nomina.importar(con, z)
    assert r["gastos_nuevos"] == 3  # los dos viáticos idénticos no se fusionan
    assert sfp_nomina.importar(con, z)["gastos_nuevos"] == 0  # reimportar no duplica
    p = con.execute("SELECT nombre_completo, cargo FROM personas").fetchone()
    assert tuple(p) == ("Ñandú Peña Prueba", "Ministro/a")
    cats = dict(con.execute("SELECT categoria, SUM(monto) FROM gastos GROUP BY categoria").fetchall())
    assert cats == {"remuneracion": 22_000_000, "viatico": 1_000_000}
    assert list(sfp_nomina.meses((2025, 11), (2026, 2))) == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]
