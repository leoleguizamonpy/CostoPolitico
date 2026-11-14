#!/usr/bin/env bash
# Instalación inicial en el VPS (Ubuntu/Debian). Correr como root:
#   curl -fsSL https://raw.githubusercontent.com/leoleguizamonpy/CostoPolitico/main/deploy/instalar.sh | DOMINIO=midominio.com bash
# o, con el repo ya clonado:  sudo DOMINIO=midominio.com bash deploy/instalar.sh
set -euo pipefail
: "${DOMINIO:?Definí DOMINIO, p.ej. DOMINIO=cuantotecuestan.com.py}"

apt-get update -qq
apt-get install -y -qq python3-venv git nginx certbot python3-certbot-nginx

id costopolitico >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin costopolitico
if [ ! -d /opt/costopolitico/.git ]; then
  git clone https://github.com/leoleguizamonpy/CostoPolitico.git /opt/costopolitico
fi
chown -R costopolitico: /opt/costopolitico
sudo -u costopolitico python3 -m venv /opt/costopolitico/.venv
sudo -u costopolitico /opt/costopolitico/.venv/bin/pip install --quiet -r /opt/costopolitico/requirements.txt
install -d -o costopolitico /var/www/costopolitico

sed "s/DOMINIO/$DOMINIO/g" /opt/costopolitico/deploy/nginx.conf > /etc/nginx/sites-available/costopolitico
ln -sf /etc/nginx/sites-available/costopolitico /etc/nginx/sites-enabled/costopolitico
nginx -t && systemctl reload nginx

cp /opt/costopolitico/deploy/costopolitico.{service,timer} /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now costopolitico.timer

echo
echo "Listo. Siguientes pasos:"
echo "  1. Certificado HTTPS:       certbot --nginx -d $DOMINIO"
echo "  2. Primera carga de datos:  systemctl start costopolitico.service   (puede tardar horas)"
echo "  3. Ver el progreso:         journalctl -u costopolitico -f"
echo "  4. Revisar pendientes:      less /opt/costopolitico/logs/pendientes-*.txt"
