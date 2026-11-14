import csv

from costopolitico import verificacion
from costopolitico.db import conectar
from costopolitico.fuentes import senado, sfp_nomina
from tests.test_senado import DETALLE, NOMINA


def _base(tmp_path):
    con = conectar(tmp_path / "t.db")
    senado.importar_nomina(con, NOMINA)
    filas = ["anho,mes,descripcion_entidad,documento,nombres,apellidos,cargo,funcion,objeto_gasto,concepto,presupuestado,devengado"]
    for mes in (3, 4):
        filas += [f"2026,{mes},CAMARA DE SENADORES,1,ANA MARIA,PRUEBA GOMEZ,MIEMBROS,SENADOR NACIONAL,112,D,32606840,32606840",
                  f"2026,{mes},CAMARA DE SENADORES,2,JUAN CARLOS,EJEMPLO RUIZ,MIEMBROS,SENADOR NACIONAL,112,D,32606840,32606840"]
    filas.append("2026,4,CAMARA DE SENADORES,3,MARTA,EJEMPLO VERA,MIEMBROS,SENADOR NACIONAL,112,D,90000000,90000000")
    (tmp_path / "n.csv").write_text("\n".join(filas), encoding="utf-8")
    sfp_nomina.importar(con, tmp_path / "n.csv")
    senado.importar_detalle(con, DETALLE, 901)
    return con


def test_controles_detectan_problemas(tmp_path):
    con = _base(tmp_path)
    r = verificacion.controles(con)
    controles = {c for _, c, _ in r["hallazgos"]}
    assert "Sin asignar / para revisar" in controles          # el chofer
    assert "Cruces de nombre no exactos" in controles          # "Ana Prueba"
    assert "Mes con sueldos incompletos" in controles          # marzo tiene 2 de 3
    ruta = verificacion.informe_controles(con, tmp_path / "c.md")
    assert "Controles automáticos" in ruta.read_text(encoding="utf-8")


def test_muestra_y_resultado(tmp_path):
    con = _base(tmp_path)
    ruta = verificacion.muestra(con, n=6, semilla=1, ruta=tmp_path / "m.csv")
    filas = list(csv.DictReader(open(ruta, encoding="utf-8-sig")))
    assert 1 <= len(filas) <= 8 and all(f["fuente_url"].startswith("http") for f in filas)
    # misma semilla, misma muestra
    assert open(verificacion.muestra(con, n=6, semilla=1, ruta=tmp_path / "m2.csv"), encoding="utf-8-sig").read() == \
        open(ruta, encoding="utf-8-sig").read()
    # completar: todas coinciden salvo una con monto distinto
    for i, f in enumerate(filas):
        f["coincide"] = "sí"
        if i == 0:
            f["monto_en_fuente"] = str(int(f["monto_app"]) + 1000)
    with open(ruta, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=verificacion.COLUMNAS); w.writeheader(); w.writerows(filas)
    r = verificacion.resultado_muestra(ruta)
    assert r["revisadas"] == len(filas) and r["errores"] == 1
    bajo, alto = r["intervalo_95"]
    assert 0 <= bajo < r["tasa_error"] < alto <= 1


def test_intervalo_wilson():
    assert verificacion._wilson(0, 60)[1] < 0.07   # 0 errores en 60: error real probablemente < 7 %
    assert verificacion._wilson(0, 0) == (0.0, 1.0)
