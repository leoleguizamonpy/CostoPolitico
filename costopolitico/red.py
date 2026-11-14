"""Conexiones HTTP con verificación de certificados que también funciona con sitios .gov.py.

Varios servidores del Estado no envían el certificado intermedio de su cadena TLS. Los
navegadores lo resuelven solos (lo descargan de la dirección "CA Issuers" que trae el propio
certificado); Python no, y falla con CERTIFICATE_VERIFY_FAILED.

Acá se hace lo mismo que el navegador, SIN desactivar la verificación: si la conexión falla por
la cadena incompleta, se baja el certificado intermedio desde su URL "CA Issuers", se agrega a un
paquete de autoridades propio (certifi + intermedios) en data/certs/ y se reintenta verificando
la cadena completa. Funciona igual en Windows, macOS y Linux.
"""
import socket
import ssl
from pathlib import Path
from urllib.parse import urlparse

import requests

from .db import RAIZ

USER_AGENT = "CostoPolitico/0.1 (transparencia; github.com/leoleguizamonpy/CostoPolitico)"
CARPETA_CERTS = RAIZ / "data" / "certs"
PAQUETE = CARPETA_CERTS / "autoridades.pem"

def _paquete_base() -> Path:
    import certifi

    CARPETA_CERTS.mkdir(parents=True, exist_ok=True)
    if not PAQUETE.exists():
        PAQUETE.write_text(Path(certifi.where()).read_text(encoding="utf-8"), encoding="utf-8")
    return PAQUETE


def _url_emisor(host: str, puerto: int = 443) -> str | None:  # noqa: D401
    """Lee el certificado del servidor (sin confiar en él) y devuelve su URL 'CA Issuers'."""
    from cryptography import x509
    from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # solo para LEER el certificado; nada se envía ni se confía
    with socket.create_connection((host, puerto), timeout=30) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    cert = x509.load_der_x509_certificate(der)
    try:
        aia = cert.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
    except x509.ExtensionNotFound:
        return None
    for d in aia:
        if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS:
            return d.access_location.value
    return None


def completar_cadena(host: str, puerto: int = 443) -> bool:
    """Descarga el certificado intermedio del host y lo agrega al paquete. True si agregó algo."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding

    url = _url_emisor(host, puerto)
    if not url:
        return False
    datos = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT}).content
    try:
        intermedio = x509.load_der_x509_certificate(datos)
    except ValueError:
        intermedio = x509.load_pem_x509_certificate(datos)
    pem = intermedio.public_bytes(Encoding.PEM).decode("ascii")
    paquete = _paquete_base()
    contenido = paquete.read_text(encoding="utf-8")
    if pem in contenido:
        return False
    paquete.write_text(contenido + f"\n# Intermedio de {host} ({intermedio.subject.rfc4514_string()})\n" + pem,
                       encoding="utf-8")
    return True


class Sesion(requests.Session):
    """requests.Session que, ante un certificado incompleto, completa la cadena y reintenta."""

    def __init__(self):
        super().__init__()
        self.headers["User-Agent"] = USER_AGENT
        if PAQUETE.exists():
            self.verify = str(PAQUETE)

    def request(self, method, url, *args, **kwargs):
        # Se pasa explícito: si no, la variable de entorno REQUESTS_CA_BUNDLE pisa al paquete.
        if self.verify == str(PAQUETE):
            kwargs.setdefault("verify", self.verify)
        try:
            return super().request(method, url, *args, **kwargs)
        except requests.exceptions.SSLError as e:
            if "CERTIFICATE_VERIFY_FAILED" not in str(e):
                raise
            u = urlparse(url)
            agregado = completar_cadena(u.hostname, u.port or 443)
            if not agregado and self.verify == str(PAQUETE):
                raise  # ya teníamos el intermedio: el problema es otro, no se oculta
            self.verify = str(_paquete_base())
            kwargs["verify"] = self.verify
            return super().request(method, url, *args, **kwargs)


def sesion() -> Sesion:
    return Sesion()
