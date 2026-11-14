"""Senado: HTML FICTICIO con la misma estructura que senado.gov.py (verificada en nov. 2026)."""
import pytest

from costopolitico.db import conectar
from costopolitico.fuentes import senado, sfp_nomina


def _senador(n, apellidos, nombres, silpy, partido):
    return (f'<div class="col-12"><a target="new" href="https://silpy.congreso.gov.py/legislador/{silpy}"'
            f' class="fw-bold fs-5">{n}. {apellidos}, {nombres}</a> <br> <i></i>'
            f' <span class="fw-bold">{partido}</span> | <span class="fw-bold fst-italic">MIEMBRO</span></div>')


NOMINA = "".join([
    _senador(1, "Prueba Gómez", "Ana María", 900001, "Partido Uno"),
    _senador(2, "Ejemplo Ruiz", "Juan Carlos", 900002, "Partido Dos"),
    _senador(3, "Ejemplo Vera", "Marta", 900003, "Partido Uno"),
    _senador(1, "Demo Antiguo", "Ramón", 900099, "Partido Dos"),  # vitalicio: la numeración reinicia
])

MISIONES = """<table id="example"><tbody>
<tr><td>1.</td><td><div>CAMARA DE SENADORES</div></td><td>MISION AL EXTERIOR</td><td>09-SETIEMBRE</td><td>2026</td>
<td><a href="https://www.senado.gov.py/x.html?idMision=901">2 Informe/s</a></td></tr>
<tr><td>2.</td><td><div>CAMARA DE SENADORES</div></td><td>MISION AL INTERIOR</td><td>08-AGOSTO</td><td>2015</td>
<td><a href="https://www.senado.gov.py/x.html?idMision=100">5 Informe/s</a></td></tr>
</tbody></table>"""

DETALLE = """<table id="informes"><thead><tr><th>#</th><th>Beneficiario</th><th>Destino</th><th>Descripción</th>
<th>Fecha</th><th>Monto asignado</th><th>Monto devuelto</th><th>Archivos</th></tr></thead><tbody>
<tr><td>1.</td><td>Ana Prueba</td><td>Montevideo (Uruguay)</td><td>Sesión ordinaria.</td>
<td>01/09/2026 - 02/09/2026</td><td>8.000.000</td><td>2.500.000</td>
<td><a href="https://adminweb.senado.gov.py/web/descarga?file=mision-1">Informe</a></td></tr>
<tr><td>2.</td><td>Juan Ejemplo</td><td>Lima (Perú)</td><td>Foro.</td>
<td>10/09/2026 - 12/09/2026</td><td>6.000.000</td><td>0</td>
<td><a href="https://adminweb.senado.gov.py/web/descarga?file=mision-2">Informe</a></td></tr>
<tr><td>3.</td><td>Pedro Chofer</td><td>Encarnación (Itapúa)</td><td>Chofer de la comitiva.</td>
<td>05/09/2026 - 05/09/2026</td><td>300.000</td><td>0</td><td></td></tr>
</tbody></table>"""


@pytest.fixture
def con(tmp_path):
    return conectar(tmp_path / "t.db")


def test_parsers():
    lista = senado.parsear_nomina(NOMINA)
    assert [s["vitalicio"] for s in lista] == [False, False, False, True]
    assert lista[0] == {"silpy_id": "900001", "apellidos": "Prueba Gómez", "nombres": "Ana María",
                        "partido": "Partido Uno", "vitalicio": False}
    assert senado.parsear_misiones(MISIONES) == [
        {"id": 901, "congreso": False, "tipo": "MISION AL EXTERIOR", "mes": "09-SETIEMBRE", "anho": 2026},
        {"id": 100, "congreso": False, "tipo": "MISION AL INTERIOR", "mes": "08-AGOSTO", "anho": 2015},
    ]
    viajes = senado.parsear_detalle(DETALLE)
    assert viajes[0]["asignado"] == 8_000_000 and viajes[0]["devuelto"] == 2_500_000
    assert viajes[2]["informe"] is None


def test_importa_neto_y_cruza_nombres_cortos(con, tmp_path):
    assert senado.importar_nomina(con, NOMINA) == {"senadores": 3, "vitalicios": 1}
    r = senado.importar_detalle(con, DETALLE, 901)
    # "Juan Ejemplo": un solo senador se llama Juan y se apellida Ejemplo -> se asigna.
    # El chofer no es senador -> sin_asignar.
    assert r == {"nueva": 2, "repetida": 0, "posible_duplicado": 0, "sin_asignar": 1, "invalida": 0}
    filas = {f["nombre_completo"]: f for f in con.execute(
        "SELECT p.nombre_completo, g.monto, g.detalle, g.fuente_url FROM gastos g JOIN personas p ON p.id = g.persona_id")}
    ana = filas["Ana María Prueba Gómez"]
    assert ana["monto"] == 5_500_000  # neto: asignado - devuelto
    assert "devuelto" in ana["detalle"] and "nombre corto" in ana["detalle"]
    assert ana["fuente_url"].endswith("mision-1")
    # Reimportar no duplica.
    assert senado.importar_detalle(con, DETALLE, 901)["repetida"] == 2


def test_nombre_corto_ambiguo_no_se_asigna(con):
    senado.importar_nomina(con, NOMINA.replace(_senador(1, "Demo Antiguo", "Ramón", 900099, "Partido Dos"), "")
                           + _senador(4, "Ejemplo Sosa", "Juan", 900004, "Partido Tres"))
    r = senado.importar_detalle(con, DETALLE, 901)
    assert r["sin_asignar"] == 2  # "Juan Ejemplo" ahora coincide con dos senadores


def test_nomina_sfp_y_senado_terminan_en_la_misma_persona(con, tmp_path):
    senado.importar_nomina(con, NOMINA)
    csv = tmp_path / "n.csv"
    csv.write_text(
        "anho,mes,descripcion_entidad,documento,nombres,apellidos,cargo,objeto_gasto,concepto,devengado\n"
        "2026,9,CAMARA DE SENADORES,1000001,ANA MARIA,PRUEBA GOMEZ,SENADORA,111,SUELDOS,40000000\n",
        encoding="utf-8")
    sfp_nomina.importar(con, csv)
    filas = con.execute("SELECT documento, silpy_id FROM personas WHERE nombre_norm = 'ANA MARIA PRUEBA GOMEZ'").fetchall()
    assert [tuple(f) for f in filas] == [("1000001", "900001")]


def test_variantes_de_nombre(con):
    from costopolitico import personas

    senado.importar_nomina(con, "".join([
        _senador(1, "Prueba Gómez", "Ana María", 900001, "P"),
        _senador(2, "Kowalski Brandt", "Walter Janusz", 900005, "P"),
        _senador(3, "Maciel Duarte", "Juan Eudes", 900006, "P"),
    ]))
    cargos = ("Senador/a",)

    def quien(nombre):
        pid, metodo = personas.buscar_con_metodo(con, nombre, cargos)
        nom = con.execute("SELECT nombre_completo FROM personas WHERE id = ?", (pid,)).fetchone() if pid else None
        return (nom[0] if nom else None), metodo

    assert quien("Walter Kowalsky") == ("Walter Janusz Kowalski Brandt", "aproximado")
    assert quien("Kowalski Brandt") == ("Walter Janusz Kowalski Brandt", "solo apellidos")
    assert quien("Janusz Kowalski") == ("Walter Janusz Kowalski Brandt", "nombre corto")  # segundo nombre
    assert quien("Ana Gómez") == (None, "")      # segundo apellido: no alcanza
    assert quien("Ana Prueba de Gómez")[0] == "Ana María Prueba Gómez"  # partícula ignorada
    assert quien("Juan Duarte") == (None, "")    # Duarte es segundo apellido
    assert quien("Pedro Desconocido") == (None, "")


def test_alias_manual(con, tmp_path):
    from costopolitico import personas
    from costopolitico.db import cargar_alias

    senado.importar_nomina(con, NOMINA)
    alias = tmp_path / "alias.csv"
    alias.write_text("nombre_fuente,silpy_id,documento,nota\nAnita P.,900001,,errata\n", encoding="utf-8")
    cargar_alias(con, alias)
    pid, metodo = personas.buscar_con_metodo(con, "Anita P.", ("Senador/a",))
    assert metodo == "alias" and pid is not None


def test_mismo_viaje_en_dos_documentos_queda_para_revision(con):
    senado.importar_nomina(con, NOMINA)
    senado.importar_detalle(con, DETALLE, 901)
    otro = DETALLE.replace("mision-1", "mision-99")  # mismo viaje publicado en otra misión
    r = senado.importar_detalle(con, otro, 902)
    assert r["posible_duplicado"] == 1 and r["nueva"] == 0
    assert con.execute("SELECT COUNT(*) FROM gastos WHERE categoria='viatico'").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM sin_asignar WHERE origen='posible_duplicado'").fetchone()[0] == 1


def test_devolucion_mayor_al_asignado(con):
    senado.importar_nomina(con, NOMINA)
    raro = DETALLE.replace("<td>2.500.000</td>", "<td>9.000.000</td>")
    senado.importar_detalle(con, raro, 901)
    g = con.execute("SELECT monto, detalle FROM gastos WHERE fuente_url LIKE '%mision-1'").fetchone()
    assert g["monto"] == 0 and "ATENCIÓN" in g["detalle"]
