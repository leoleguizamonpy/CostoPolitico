# ¿Cuánto te cuestan tus políticos?

Cuánto dinero público se asigna a cada **senador, diputado y autoridad del Ejecutivo** del
Paraguay: sueldo, gastos de representación, viáticos y personal de su despacho (incluido el
comisionado desde otras instituciones). **Cada monto con
su fuente oficial.**

La web muestra cuánto cuestan todos juntos por día (con un contador en vivo desde las 00:00),
un gráfico mensual apilado por categoría, filtros por cámara, año y mes, y el ranking con la
ficha de cada autoridad.

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

## Windows: todo de una

1. Instalá Python 3.10+ desde https://www.python.org/downloads/ (marcá **Add python.exe to PATH**).
2. Bajá el proyecto (Code → Download ZIP, o `git clone`) y descomprimilo.
3. Doble clic en **`correr.bat`**. Instala todo, baja los datos (cámaras desde 2025, sueldos
   desde enero de 2026), genera la web y la abre en http://localhost:8000.

Carga completa 2023-2026 (horas, ~1,5 GB): en esa carpeta, `correr.bat -Completo`.

## Uso (en tu máquina o en el servidor)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Remuneraciones: baja e importa los meses de la nómina SFP (desde julio de 2023 por defecto).
#    Son ~45 MB por mes; los meses ya importados se saltan.
python -m costopolitico sueldos --desde 2023-07

# 2. Todo lo automático, en el orden correcto (nóminas de ambas cámaras, viajes, exportación).
#    Es el comando para el cron mensual del VPS.
python -m costopolitico actualizar --desde 2023

#    O por partes:
python -m costopolitico diputados --desde 2023   # nómina + planillas mensuales de viáticos
python -m costopolitico senado --desde 2023      # nómina + viajes
python -m costopolitico comisionados --desde 2023  # personal de otras instituciones en despachos
                                                  # (después correr "sueldos": suma sus sueldos)
python -m costopolitico diputados-pdf data/crudos/planilla.pdf --url "URL_DEL_PDF"   # un PDF suelto

# 2b. Otras listas de viáticos: completar data/plantillas/viaticos.csv (con fuente_url por fila)
python -m costopolitico viaticos-csv data/crudos/otros_viaticos.csv

# 3. Revisar lo que no se pudo asignar (con los legisladores más parecidos como sugerencia)
python -m costopolitico pendientes --csv data/revision.csv

# 4. Publicar
python -m costopolitico exportar        # crea web/data.json
python -m http.server -d web 8000       # ver en http://localhost:8000
```

Conviene importar primero las nóminas (SFP y Senado): de ahí salen las personas a las que
después se asignan los viáticos. Todo es idempotente: reimportar no duplica.

## Verificar antes de publicar

La app nombra a personas reales con montos de dinero público: antes de publicar (y después de
cada cambio grande) conviene verificar.

```bash
python -m costopolitico controles                  # revisiones automáticas → data/verificacion/controles-FECHA.md
python -m costopolitico pendientes --csv data/revision.csv   # lo que no se pudo asignar, con sugerencias
python -m costopolitico muestra --n 60             # planilla con 60 gastos al azar → data/verificacion/
```

1. **Controles**: revisá el informe (remuneraciones atípicas, sueldos duplicados, devoluciones
   raras, fechas imposibles, viajes publicados dos veces, meses incompletos).
2. **Muestra**: abrí la planilla en Excel; para cada fila abrí `fuente_url`, buscá el monto y
   completá `monto_en_fuente` y `coincide` (sí/no). La muestra sobrerrepresenta los cruces de
   nombre no exactos, que son los de más riesgo.
3. **Resultado**: `python -m costopolitico resultado-muestra "RUTA_DE_LA_PLANILLA"` da la tasa de
   error con su intervalo de confianza del 95 %. Con `--publicar`, ese resultado aparece en la
   página de metodología.

Cada ficha de la web tiene **Reportar un error**, que abre un issue prellenado en este
repositorio (etiqueta `error-de-datos`). La URL se cambia en `REPORTAR_URL`, dentro de
`web/index.html`.

## Publicar en un VPS

Todo está en `deploy/` (Ubuntu/Debian, nginx, systemd):

```bash
# En el VPS, como root:
git clone https://github.com/leoleguizamonpy/CostoPolitico.git /opt/costopolitico
DOMINIO=midominio.com bash /opt/costopolitico/deploy/instalar.sh
certbot --nginx -d midominio.com           # HTTPS
systemctl start costopolitico.service      # primera carga (horas: ~1,5 GB de nómina SFP)
journalctl -u costopolitico -f             # ver el progreso
```

Después, `costopolitico.timer` actualiza solo el día 25 de cada mes: baja lo nuevo, regenera
`data.json`, lo publica en `/var/www/costopolitico` y deja en `logs/` el registro y la lista de
pendientes a revisar.

## Pruebas

```bash
pip install pytest reportlab
python -m pytest
```

## Hoja de ruta

- [x] Base de datos, nómina SFP, viáticos de Diputados, app web
- [x] Scraper del Senado (nómina y viajes con viáticos)
- [x] Nómina de diputados y descarga automática de sus planillas de viáticos
- [x] Descarga automática de sueldos (SFP)
- [x] Kit de publicación en VPS (nginx + systemd, actualización mensual)
- [x] Personal comisionado de otras instituciones en despachos (listados de Diputados)
- [ ] Comisionados a despachos del Senado desde otras instituciones
- [ ] Nómina mensual del Senado (PDF, al día; cubre el hueco de la SFP desde junio 2026)
- [ ] Canciller (no identificable en la nómina SFP)
- [ ] Viáticos de ministros (Contraloría / portales de cada ministerio)
- [ ] Fase 2: gasto institucional (DNCP, ejecución presupuestaria) en sección aparte
