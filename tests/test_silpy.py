"""Ficha del SILpy: HTML FICTICIO con la estructura real (verificada nov. 2026)."""
from costopolitico.fuentes.silpy import movimiento, parsear_ficha

FICHA = """<html><head><title>MARÍA PRUEBA DE EJEMPLO </title></head><body>
<label><span class="ui-outputlabel-label">Representante: </span></label><span title="Tipo">SUPLENTE [2023-2028]</span>
<label title="Partido/Movimiento/Alianza/Concertación"><span>Part./Mov./Ali./Conc.: </span></label><span title="Partido">Partido Liberal Radical Auténtico PLRA</span>
<div class="ui-outputpanel"> <span class="font-bold"> VICELIDER </span> de la Bancada <span class="font-bold font-italic">BANCADA DEL PARTIDO LIBERAL RADICAL AUTÉNTICO PLRA - C</span></div>
<div class="ui-outputpanel"><span class="block font-italic text-purple-700">Jura en reemplazo del Senador X (01/01/2026).</span></div>
</body></html>"""


def test_parsear_ficha():
    f = parsear_ficha(FICHA)
    assert f == {"nombre": "MARÍA PRUEBA DE EJEMPLO", "partido": "Partido Liberal Radical Auténtico PLRA",
                 "representante": "SUPLENTE [2023-2028]",
                 "bancada": "BANCADA DEL PARTIDO LIBERAL RADICAL AUTÉNTICO PLRA - C", "rol_bancada": "Vicelider"}


def test_movimiento_textos_reales():
    anr, plra = "Asociación Nacional Republicana ANR", "Partido Liberal Radical Auténtico PLRA"
    assert movimiento('BANCADA DE LA ASOCIACIÓN NACIONAL REPUBLICANA ANR - A "HONOR COLORADO"', anr) == 'A "Honor Colorado"'
    assert movimiento("BANCADA DE LA ASOCIACIÓN NACIONAL REPUBLICANA ANR - B", anr) == "B"
    assert movimiento('Asociación Nacional Republicana Partido Colorado (ANR) - Independiente "A"', anr) == 'Independiente "A"'
    assert movimiento('Partido Liberal Radical Autentico (PLRA) "B"', plra) == "B"
    assert movimiento("Partido Liberal Radical Auténtico (PLRA) – Eligio Ayala", plra) == "Eligio Ayala"
    assert movimiento("BANCADA DEL MOVIMIENTO CONCIENCIA DEMOCRÁTICA NACIONAL -YO CREO",
                      "Movimiento Conciencia Democrática Nacional") == "Yo Creo"
    assert movimiento("BANCADA DEL PARTIDO PATRIA QUERIDA - PPQ", "Partido Patria Querida PPQ") is None
    assert movimiento("BANCADA INDEPENDIENTE", "INDEPENDIENTE") is None
    assert movimiento(None, anr) is None
