# ¿Cuánto te cuestan tus políticos?

Cuánto dinero público se asigna a cada **senador, diputado y autoridad del Ejecutivo** del
Paraguay: sueldo, gastos de representación, viáticos y más. **Cada monto con su fuente oficial.**

## Principios

1. **Fuente en cada monto.** Nombre de la fuente, enlace y fecha de descarga. Sin fuente, no se publica.
2. **Lo personal separado de lo institucional.** El ranking muestra lo asignado a la persona.
   El gasto del ministerio o cámara que dirige va aparte y nunca se suma.
3. **Datos, no adjetivos.** La app muestra montos y comparaciones; no califica a nadie.
4. **Nada se descarta en silencio.** Lo que no se puede asignar con seguridad queda para revisión.

## Estructura

```
costopolitico/         código Python
  db.py                esquema SQLite (personas, gastos, sin_asignar)
  personas.py          quién cuenta como político y cómo se cruza entre fuentes
  fuentes/
    sfp_nomina.py      remuneraciones — nómina SFP (Ley 5189/14)
    senado.py          nómina de senadores y viajes con viáticos (senado.gov.py)
    diputados.py       nómina de diputados (+ SILpy) y planillas mensuales de viáticos
    viaticos.py        viáticos — PDF de Diputados + CSV genérico
  exportar.py          genera web/data.json
web/index.html         la app (un solo archivo, lee data.json)
data/plantillas/       plantillas CSV para carga manual
data/alias.csv         correcciones manuales de nombres que no cruzan solos
docs/fuentes.md        cada fuente: qué trae, formato, estado
tests/                 pruebas con datos ficticios
```

## Uso (en tu máquina o en el servidor)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Remuneraciones: descargar el CSV mensual desde https://datos.sfp.gov.py/data/funcionarios
python -m costopolitico nomina data/crudos/funcionarios_2026_9.csv

# 2. Todo lo automático, en el orden correcto (nóminas de ambas cámaras, viajes, exportación).
#    Es el comando para el cron mensual del VPS.
python -m costopolitico actualizar --desde 2023

#    O por partes:
python -m costopolitico diputados --desde 2023   # nómina + planillas mensuales de viáticos
python -m costopolitico senado --desde 2023      # nómina + viajes
python -m costopolitico diputados-pdf data/crudos/planilla.pdf --url "URL_DEL_PDF"   # un PDF suelto

# 2b. Otras listas de viáticos: completar data/plantillas/viaticos.csv (con fuente_url por fila)
python -m costopolitico viaticos-csv data/crudos/otros_viaticos.csv

# 3. Revisar lo que no se pudo asignar
python -m costopolitico pendientes

# 4. Publicar
python -m costopolitico exportar        # crea web/data.json
python -m http.server -d web 8000       # ver en http://localhost:8000
```

Conviene importar primero las nóminas (SFP y Senado): de ahí salen las personas a las que
después se asignan los viáticos. Todo es idempotente: reimportar no duplica.

## Pruebas

```bash
pip install pytest reportlab
python -m pytest
```

## Hoja de ruta

- [x] Base de datos, nómina SFP, viáticos de Diputados, app web
- [x] Scraper del Senado (nómina y viajes con viáticos)
- [x] Nómina de diputados y descarga automática de sus planillas de viáticos
- [ ] Descarga automática mensual (cron en el VPS)
- [ ] Viáticos de ministros (Contraloría / portales de cada ministerio)
- [ ] Fase 2: gasto institucional (DNCP, ejecución presupuestaria) en sección aparte
