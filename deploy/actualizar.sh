#!/usr/bin/env bash
# Corre en el VPS: actualiza la base, regenera web/data.json y lo publica en la carpeta de nginx.
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only --quiet || echo "aviso: no se pudo actualizar el código (se sigue con el actual)"
.venv/bin/pip install --quiet -r requirements.txt

FECHA=$(date +%Y-%m-%d)
mkdir -p logs
.venv/bin/python -m costopolitico actualizar --desde 2023 2>&1 | tee "logs/actualizar-$FECHA.log"
.venv/bin/python -m costopolitico pendientes > "logs/pendientes-$FECHA.txt" || true

# Publicar: copia atómica para que nadie vea un data.json a medio escribir.
DESTINO=/var/www/costopolitico
install -d "$DESTINO"
cp web/index.html "$DESTINO/index.html.tmp" && mv "$DESTINO/index.html.tmp" "$DESTINO/index.html"
cp web/data.json  "$DESTINO/data.json.tmp"  && mv "$DESTINO/data.json.tmp"  "$DESTINO/data.json"
echo "publicado: $(date -Is)"
