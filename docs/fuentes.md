# Fuentes de datos

Regla del proyecto: **cada monto publicado tiene fuente oficial (nombre + URL) y fecha de descarga.**
Lo que no tiene fuente no entra.

## Separación clave

| Bloque | Qué incluye | Dónde va |
|---|---|---|
| **Asignado a la persona** | sueldo, gastos de representación, bonificaciones, viáticos, pasajes, asesores a su cargo | tabla `gastos` → ranking de la app |
| **Gasto de la institución que dirige** | presupuesto ejecutado, compras y contratos de un ministerio o cámara | fase 2, sección aparte, **nunca sumado** al bloque anterior |

## Fuentes

| # | Fuente | Qué trae | Formato | Estado en el código |
|---|---|---|---|---|
| 1 | Nómina de funcionarios — portal de datos abiertos SFP/VCHGO (Ley 5189/14) · listado: https://datos.sfp.gov.py/data/funcionarios/download · archivo: `https://datos.sfp.gov.py/data/funcionarios_{año}_{mes}.csv.zip` | Remuneración mensual de cada funcionario por objeto de gasto (112 dieta, 113 gastos de representación, 111 sueldo, 133 bonificaciones, 232 viáticos…). Se toma solo lo **devengado** | CSV mensual en ZIP, Latin-1, ~1 millón de filas | ✅ `fuentes/sfp_nomina.py` — descarga mensual automática (`sueldos`), lectura en streaming, registro de meses ya importados |
| 2 | Cámara de Diputados — nómina alfabética (diputados.gov.py/diputados/nomina-alfabetica) + ficha de cada diputado en SILpy | Los 80 diputados, partido e ID del SILpy. La nómina trae "APELLIDOS NOMBRES" sin separar; el corte exacto sale de comparar con el nombre de la ficha del SILpy ("Nombres Apellidos"). Sin ficha (5 de 80 en nov. 2026), se estima con la convención de dos apellidos | HTML | ✅ `fuentes/diputados.py` |
| 2b | Cámara de Diputados — "Viajes oficiales de misiones parlamentarias" (listado Ley 5189: diputados.gov.py/transparencia/ley-5189) | Por viaje: diputado/a o funcionario/a, resolución, destino, fechas, motivo, monto del viático | PDF mensual (Word, tabla con bordes) | ✅ `fuentes/diputados.py` + `fuentes/viaticos.py`. Se omiten los "INFORME DE VIAJES…" (informes narrativos sin montos) |
| 3 | Cámara de Senadores — nómina alfabética (senado.gov.py/index.php/menu-senadores/sub-menu-nomina-alfabetica.html) | Los 45 senadores + vitalicios, con partido e ID del SILpy | HTML | ✅ `fuentes/senado.py` |
| 3b | Cámara de Senadores — "Detalles de viajes nacionales e internacionales" (Transparencia activa, Ley 5189) | Por viaje: beneficiario, destino, motivo, fechas, **monto asignado y monto devuelto**, informe PDF. Registros desde 2008 | HTML (tabla por misión `?idMision=N`) | ✅ `fuentes/senado.py` — se guarda el **neto** (asignado − devuelto) y el informe PDF como fuente |
| 3c | Cámara de Senadores — "Nóminas y listados" (Transparencia activa) | Nómina mensual de senadores, funcionarios, contratados y comisionados del Senado y del Congreso. **Al día (septiembre 2026)**: cubre el hueco de la SFP | PDF apaisado (~17 páginas, tabla densa) en adminweb.senado.gov.py/web/descarga?file=nomina-N | ⏳ estructura por leer con pdfplumber |
| 2c | Cámara de Diputados — "Anexo del personal" (listado Ley 5189) | Planilla mensual de personal | PDF | ⏳ por revisar |
| 4 | Contraloría General — datos abiertos de rendiciones de viáticos | Viáticos de todo el sector público | Datos abiertos | ⏳ por revisar |
| 5 | DNCP — API de contrataciones (OCDS) · https://www.contrataciones.gov.py/datos/api/v3/doc/ | Compras y contratos por institución | API JSON | ⏳ fase 2 (gasto institucional) |
| 6 | Pedidos por Ley 5282/14 (informacionpublica.paraguay.gov.py) | Combustible, telefonía, asesores por legislador, todo lo que no se publica | Respuestas oficiales | ⏳ carga manual con URL de la respuesta como fuente |

## Nómina SFP: quién cuenta como político (verificado con abril de 2026)

| Quién | Cómo figura en la nómina | Resultado abril 2026 |
|---|---|---|
| Senadores | Cámara de Senadores, cargo "MIEMBROS" (o "PRESIDENTE", "VICE PTE."), función "SENADOR NACIONAL" | 44 · ₲ 37.900.000/mes (dieta 32.606.840 + representación 5.293.160) |
| Diputados | Cámara de Diputados, cargo "DIPUTADO NACIONAL" | 80 · ₲ 29.562.000/mes (dieta 25.433.335 + representación 4.128.665) |
| Presidente | Presidencia, cargo "PRESIDENTE DE LA REPUBLICA" | ₲ 37.908.800/mes |
| Vicepresidente | Vice Presidencia (entidad aparte), cargo "VICEPRESIDENTE" | ₲ 36.780.000/mes |
| Ministros | Ministerios, cargo o función "MINISTRO/A" | 15 |
| Ministros-secretarios | Presidencia, cargo o función "MINISTRO/A…" (secretarías con rango de ministro) | 23 |

Las reglas están ancladas para **no** tomar a los funcionarios de los despachos ("PRESTA SERVICIOS
EN EL DESPACHO LEGISLATIVO DEL DIPUTADO…", "DESPACHO DEL SENADOR…"), que son cientos. Se excluyen
a propósito: el Ministerio Público y la Defensa Pública (no son el Ejecutivo) y el Ministerio de
Relaciones Exteriores, donde "MINISTRO" es un rango diplomático (más de 240 registros). **El
canciller no se puede identificar en la nómina** (casi todos los registros tienen función "NO
DISPONIBLE"): queda pendiente de otra fuente.

**Personal de despacho (asesores, secretarios, choferes).** En las cámaras, muchos funcionarios
tienen una función que nombra al legislador: "DESPACHO DEL SENADOR DIONISIO AMARILLA", "PRESTA
SERVICIOS EN EL DESPACHO LEGISLATIVO DE LA DIPUTADA …", "ENCARGADO DE DESPACHO LEGISLATIVO DE LA
DIPUTADA … RESOLUCIÓN …". Su costo se asigna a ese legislador (categoría "Personal del despacho").
En la web se muestra agregado por mes (cantidad de personas y desglose por cargo), sin nombres.
En abril de 2026: 72 personas en despachos de senadores (₲ 477.589.479) y 83 en despachos de
diputados (₲ 222.927.273). Es un **mínimo comprobable**: quien figura sin indicar a qué despacho
sirve no se puede atribuir. Nombres que no cruzan (p.ej. "DESPACHO DEL SENADOR WALTER", cortado
en la fuente) quedan en pendientes.

La misma persona puede figurar con otro segundo apellido (de casada: "Valiente Cabrera" en la
nómina, "Valiente de Rodríguez" en el Senado). Se unen por primer nombre + primer apellido dentro
del mismo cargo, solo con un único candidato y nunca si tienen cédula o ID del SILpy distintos.

**Hueco de datos:** los archivos están completos hasta abril de 2026; mayo viene parcial y desde
junio de 2026 el portal publica archivos casi vacíos (1-6 KB; octubre, 1,4 MB). El importador no
marca esos meses como importados y los vuelve a intentar en cada corrida.

## Cómo se cruzan los nombres

Las fuentes escriben los nombres de formas distintas ("Dionisio Amarilla", "Javier Zacarías",
"Walter Kobykanski" con errata). El cruce (`personas.buscar_con_metodo`) prueba, en orden:
alias manual → exacto → mismas palabras → nombre incompleto → nombre corto (un nombre de pila +
**primer** apellido) → solo apellidos → aproximado (erratas en palabras largas).
Solo asigna si hay **un** candidato. Los métodos no exactos quedan escritos en el detalle de cada
gasto ("cruce nombre corto: «…»") para que cualquiera pueda verificarlo. Lo que no se resuelve
se corrige a mano en `data/alias.csv`.

Prueba con datos reales del Senado (nov. 2026): de 572 nombres distintos en viajes desde 2023,
56 se asignaron a 35 senadores, todos revisados a mano sin errores. El resto son funcionarios,
choferes, prensa y exsenadores.

## Problemas conocidos

- No todas las instituciones reportan a la SFP a tiempo; puede faltar algún mes (ver "Hueco de datos").
- Un senador con permiso que asume como ministro (p.ej. Enrique Riera, Interior) aparece como dos
  registros: senador (sin cobro mientras dura el permiso) y ministro.
- Las cámaras publican viáticos con atraso (a veces varios meses).
- Las listas de viáticos mezclan legisladores y funcionarios: lo que no se puede asignar
  con seguridad queda en `sin_asignar` y se revisa con `python -m costopolitico pendientes`.
- La nómina del Senado solo lista a los senadores **actuales**: los viajes de exsenadores
  (renuncias, pérdidas de investidura) quedan en `sin_asignar` hasta cargar el padrón histórico.
- Los viajes de diputados al Parlasur aparecen en la web del Senado, en misiones del
  **Congreso Nacional**. Solo en esas misiones se cruza también con diputados; en las de la
  Cámara de Senadores solo con senadores (evita asignar a un diputado el viaje de un funcionario
  del Senado con nombre común). Verificado con datos reales: los 19 diputados encontrados en la
  web del Senado aparecen únicamente en misiones del Congreso Nacional.
- La API de datos abiertos del Congreso (datos.congreso.gov.py) respondía con error 502 en
  noviembre de 2026; por eso se usan las páginas públicas.
- Los asesores figuran en la nómina de cada cámara, pero sin indicar a qué legislador
  responden. Hace falta otra fuente (resoluciones o pedido por Ley 5282).
