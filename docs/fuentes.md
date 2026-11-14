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
| 1 | Nómina de funcionarios — portal de datos abiertos SFP/VCHGO (Ley 5189/14) · https://datos.sfp.gov.py/data/funcionarios · diccionario: https://datos.sfp.gov.py/def/funcionarios | Remuneración mensual de cada funcionario, incluidos cargos electivos, por objeto de gasto (111 sueldos, 113 gastos de representación, etc.) | CSV mensual (a veces ZIP) | ✅ `fuentes/sfp_nomina.py` |
| 2 | Cámara de Diputados — "Viajes oficiales / Misiones parlamentarias" (sección Transparencia de diputados.gov.py) | Por viaje: diputado/a o funcionario/a, resolución, destino, fechas, motivo, monto del viático | PDF mensual | ✅ `fuentes/viaticos.py` (tablas con o sin bordes) |
| 3 | Cámara de Senadores — viajes y viáticos (senado.gov.py) | Beneficiario, destino, período, motivo, monto; a veces devoluciones | Web | 🟡 carga vía `data/plantillas/viaticos.csv` hasta escribir el scraper específico |
| 4 | Contraloría General — datos abiertos de rendiciones de viáticos | Viáticos de todo el sector público | Datos abiertos | ⏳ por revisar |
| 5 | DNCP — API de contrataciones (OCDS) · https://www.contrataciones.gov.py/datos/api/v3/doc/ | Compras y contratos por institución | API JSON | ⏳ fase 2 (gasto institucional) |
| 6 | Pedidos por Ley 5282/14 (informacionpublica.paraguay.gov.py) | Combustible, telefonía, asesores por legislador, todo lo que no se publica | Respuestas oficiales | ⏳ carga manual con URL de la respuesta como fuente |

## Problemas conocidos

- No todas las instituciones reportan a la SFP a tiempo; puede faltar algún mes.
- Las cámaras publican viáticos con atraso (a veces varios meses).
- Las listas de viáticos mezclan legisladores y funcionarios: lo que no se puede asignar
  con seguridad queda en `sin_asignar` y se revisa con `python -m costopolitico pendientes`.
- Los asesores figuran en la nómina de cada cámara, pero sin indicar a qué legislador
  responden. Hace falta otra fuente (resoluciones o pedido por Ley 5282).
