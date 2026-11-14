"""Diputados: HTML FICTICIO con la estructura de diputados.gov.py y SILpy (verificada nov. 2026)."""
import pytest

from costopolitico import personas
from costopolitico.db import conectar
from costopolitico.fuentes import diputados, senado


def _fila(n, silpy, nombre, partido):
    enlace = f'<a href="http://silpy.congreso.gov.py/parlamentario/{silpy}" target="_blank">{nombre}</a>' if silpy else nombre
    return f"<tr><td><p><span>{n:02d} </span></p></td><td><p><span>{enlace}</span></p></td><td><p><span>{partido}</span></p></td></tr>"


NOMINA = ("<table><tbody><tr><td>N°</td><td>NOMBRE DEL DIPUTADO</td><td>PARTIDO</td></tr>"
          + _fila(1, 800001, "EJEMPLO DE PRUEBA ANA LUCIA", "P1")
          + _fila(2, 800002, "MEZQUITA JUAN CARLOS", "P2")          # un solo apellido
          + _fila(3, None, "DA COSTA RUIZ PEDRO PABLO", "P1")        # sin ficha SILpy
          + _fila(4, 800004, "SOSA VDA DE TEST MARIA", "P3")
          + "</tbody></table>")
TITULOS = {"800001": "ANA LUCÍA EJEMPLO DE PRUEBA", "800002": "JUAN CARLOS MEZQUITA",
           "800004": "MARÍA SOSA VDA DE TEST usuario_redes"}


@pytest.fixture
def con(tmp_path):
    return conectar(tmp_path / "t.db")


def test_separar_nombre():
    assert diputados.separar_nombre("EJEMPLO DE PRUEBA ANA LUCIA", "ANA LUCÍA EJEMPLO DE PRUEBA") == \
        ("EJEMPLO DE PRUEBA", "ANA LUCIA", "silpy")
    assert diputados.separar_nombre("MEZQUITA JUAN CARLOS", "JUAN CARLOS MEZQUITA")[:2] == ("MEZQUITA", "JUAN CARLOS")
    assert diputados.separar_nombre("DA COSTA RUIZ PEDRO PABLO") == ("DA COSTA RUIZ", "PEDRO PABLO", "estimado")
    assert diputados.separar_nombre("SOSA VDA DE TEST MARIA", "MARÍA SOSA VDA DE TEST usuario_redes")[:2] == \
        ("SOSA VDA DE TEST", "MARIA")


def test_importar_nomina_y_cruzar(con):
    r = diputados.importar_nomina(con, NOMINA, TITULOS)
    assert r == {"diputados": 4, "corte_silpy": 3, "corte_estimado": 1}
    pid, metodo = personas.buscar_con_metodo(con, "Ana Ejemplo", ("Diputado/a",))
    assert metodo == "nombre corto"
    assert con.execute("SELECT nombre_completo FROM personas WHERE id=?", (pid,)).fetchone()[0] == "Ana Lucia Ejemplo De Prueba"
    assert personas.buscar_con_metodo(con, "Juan Mezquita", ("Diputado/a",))[1] == "nombre corto"


def test_documentos_ley_5189():
    html = """<table><tr><th>Fecha</th><th>Título</th><th>Archivo</th></tr>
    <tr><td>21/10/26</td><td>VIAJES OFICIALES DE MISIONES PARLAMENTARIAS SETIEMBRE_2026</td><td><a href="https://diputados.gov.py/storage/documentos/2_X.pdf">Ver</a></td></tr>
    <tr><td>21/10/26</td><td>INFORME DE VIAJES OFICIALES DE MISIONES PARLAMENTARIAS - SETIEMBRE 2026</td><td><a href="https://diputados.gov.py/storage/documentos/16_Y.pdf">Ver</a></td></tr>
    <tr><td>26/06/25</td><td>Misiones Parlamentarias - Mayo 2025</td><td><a href="https://diputados.gov.py/storage/documentos/2_Z.pdf">Ver</a></td></tr></table>"""
    docs = diputados.parsear_documentos(html)
    assert [diputados.es_planilla_de_viaticos(d["titulo"]) for d in docs] == [True, False, True]
    assert [diputados.anho_documento(d) for d in docs] == [2026, 2026, 2025]


def test_senado_solo_cruza_diputados_en_misiones_del_congreso(con):
    diputados.importar_nomina(con, NOMINA, TITULOS)
    detalle = """<table id="informes"><tbody><tr><td>1.</td><td>Juan Mezquita</td><td>Montevideo (Uruguay)</td>
    <td>Sesión del Parlasur.</td><td>01/09/2026 - 02/09/2026</td><td>4.000.000</td><td>0</td><td></td></tr></tbody></table>"""
    # Misión de la Cámara de Senadores: un diputado no puede ser el beneficiario -> revisión.
    assert senado.importar_detalle(con, detalle, 1, congreso=False)["sin_asignar"] == 1
    # Misión del Congreso Nacional (Parlasur): sí se cruza con diputados.
    assert senado.importar_detalle(con, detalle, 2, congreso=True)["nueva"] == 1
