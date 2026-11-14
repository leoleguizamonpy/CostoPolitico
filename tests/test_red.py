"""Reproduce un servidor .gov.py que NO envía su certificado intermedio y verifica que la sesión
completa la cadena (descargando el intermedio de su URL "CA Issuers") sin desactivar la verificación."""
import datetime as dt
import http.server
import ssl
import threading

import pytest
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import AuthorityInformationAccessOID, NameOID

from costopolitico import red


def _cert(nombre, clave, emisor_nombre, emisor_clave, ca, aia=None, san=None):
    ahora = dt.datetime.now(dt.timezone.utc)
    b = (x509.CertificateBuilder()
         .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nombre)]))
         .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, emisor_nombre)]))
         .public_key(clave.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(ahora - dt.timedelta(days=1)).not_valid_after(ahora + dt.timedelta(days=30))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
         .add_extension(x509.SubjectKeyIdentifier.from_public_key(clave.public_key()), critical=False)
         .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(emisor_clave.public_key()), critical=False))
    if aia:
        b = b.add_extension(x509.AuthorityInformationAccess([x509.AccessDescription(
            AuthorityInformationAccessOID.CA_ISSUERS, x509.UniformResourceIdentifier(aia))]), critical=False)
    if san:
        b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False)
        b = b.add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    if ca:
        b = b.add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                          content_commitment=False, key_encipherment=False, data_encipherment=False,
                                          key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
    return b.sign(emisor_clave, hashes.SHA256())


def _servidor(handler, ctx=None):
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    if ctx:
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def cadena(tmp_path, monkeypatch):
    k_raiz, k_int, k_hoja = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
    raiz = _cert("Raiz de prueba", k_raiz, "Raiz de prueba", k_raiz, ca=True)
    inter = _cert("Intermedio de prueba", k_int, "Raiz de prueba", k_raiz, ca=True)
    der_inter = inter.public_bytes(serialization.Encoding.DER)

    class Emisor(http.server.BaseHTTPRequestHandler):  # sirve el intermedio por HTTP, como las CA reales
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(der_inter)
        def log_message(self, *a): pass
    emisor = _servidor(Emisor)

    hoja = _cert("localhost", k_hoja, "Intermedio de prueba", k_int, ca=False,
                 aia=f"http://127.0.0.1:{emisor.server_port}/inter.der", san="localhost")
    (tmp_path / "hoja.pem").write_bytes(hoja.public_bytes(serialization.Encoding.PEM))  # SOLO la hoja: cadena incompleta
    (tmp_path / "clave.pem").write_bytes(k_hoja.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp_path / "hoja.pem", tmp_path / "clave.pem")

    class Sitio(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        do_HEAD = do_GET
        def log_message(self, *a): pass
    sitio = _servidor(Sitio, ctx)

    # El "almacén de autoridades" de la prueba solo confía en nuestra raíz (como certifi con las raíces reales).
    raices = tmp_path / "raices.pem"
    raices.write_bytes(raiz.public_bytes(serialization.Encoding.PEM))
    import certifi
    monkeypatch.setattr(certifi, "where", lambda: str(raices))
    monkeypatch.setattr(red, "CARPETA_CERTS", tmp_path / "certs")
    monkeypatch.setattr(red, "PAQUETE", tmp_path / "certs" / "autoridades.pem")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(raices))
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1")
    yield f"https://localhost:{sitio.server_port}/"
    sitio.shutdown(); emisor.shutdown()


def test_sin_completar_falla_como_en_windows(cadena):
    with pytest.raises(requests.exceptions.SSLError):
        requests.get(cadena, timeout=10)  # requests normal, verificando: falla igual que en tu PC


def test_sesion_completa_la_cadena_y_verifica(cadena):
    s = red.sesion()
    r = s.get(cadena, timeout=10)
    assert r.text == "ok"
    assert "Intermedio de prueba" in red.PAQUETE.read_text(encoding="utf-8")
    assert s.verify == str(red.PAQUETE)  # sigue verificando, ahora con la cadena completa
    assert red.sesion().head(cadena, timeout=10).status_code == 200  # una sesión nueva reutiliza el paquete
