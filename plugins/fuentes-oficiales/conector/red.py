# Fuentes oficiales (versión abierta) 0.3.1. Hecho por Jurium. Licencia MIT (LICENSE).
"""Red segura: solo HTTPS, solo dominios oficiales de la lista blanca y solo lectura.

Cualquier URL (también una redirección) fuera de DOMINIOS se rechaza antes de conectar."""
from __future__ import annotations

import codecs
import hashlib
import html
import http.client
import http.cookiejar
import json
import re
import socket
import ssl
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# Dominio -> en quién se confía para su certificado: "sistema" (almacén de Windows) o "fnmt" (solo las
# raíces de la FNMT de certificados/, porque el almacén de Windows rompe la cadena de estas webs).
DOMINIOS = {
    "www.boe.es": "sistema",                              # BOE y BORME (API de datos abiertos y buscador)
    "ovc.catastro.meh.es": "sistema",                     # Catastro, servicios web de consulta libre
    "ec.europa.eu": "sistema",                            # VIES, Comisión Europea
    "www.infosubvenciones.es": "fnmt",                    # BDNS, Base de Datos Nacional de Subvenciones
    "petete.tributos.hacienda.gob.es": "fnmt",            # DGT, consultas tributarias
    "serviciostelematicosext.hacienda.gob.es": "fnmt",    # TEAC, doctrina (DYCTEA)
    "hj.tribunalconstitucional.es": "fnmt",               # Tribunal Constitucional
    "publications.europa.eu": "sistema",                  # CELLAR (Oficina de Publicaciones UE): TJUE y Tribunal General
    # REGCON, registro de convenios colectivos. Confianza propia (aunque sea la del sistema) para que ninguna
    # redirección desde un boletín pueda llegar a él: su ficha lleva datos de quien tramita.
    "expinterweb.mites.gob.es": "regcon",
    # Sede de la AEAT, solo para el calendario del contribuyente (radar del despacho, 4-nov-2026). Confianza propia
    # por lo mismo que REGCON: ninguna redirección desde otro dominio llega a ella. Su iCal vive en Google
    # Calendar, fuera de la lista: no se usa.
    "sede.agenciatributaria.gob.es": "aeat",
}
# Boletines donde REGCON enlaza el texto de los convenios (recogidos de sus enlaces y con el certificado comprobado
# el 3 y 4-nov-2026). Fuera: bop.dipucr.es (certificado que no valida), bopbur.diputaciondeburgos.es y
# portaldogc.gencat.cat (solo TLS antiguo): de esos solo se nombra el boletín, sin enlace.
_FNMT_BOLETINES = {"app.dipalme.org", "bop.dpz.es", "www.dipucuenca.es"}
BOLETINES = frozenset((  # solo estos valen como enlace de publicación de un convenio (no las demás fuentes)
    "236ws.dpteruel.es", "aplicacions.dipta.cat", "app.dipalme.org", "boc.cantabria.es", "bocyl.jcyl.es",
    "boletin.dguadalajara.es", "bomemelilla.es", "bon.navarra.es", "bop.dacoruna.gal", "bop.depourense.es",
    "bop.diba.cat", "bop.dipcas.es", "bop.dipgra.es", "bop.dipsoria.es", "bop.dipualba.es", "bop.dipucordoba.es",
    "bop.dipujaen.es", "bop.dipuleon.es", "bop.diputoledo.es", "bop.dival.es", "bop.dphuesca.es", "bop.dpz.es",
    "bop.sede.diputaciondevalladolid.es", "boppo.depo.gal", "bopsevilla.dipusevilla.es", "deputacionlugo.gal",
    "docm.jccm.es", "doe.juntaex.es", "sedeelectronicadipusevilla.es", "www.navarra.es",
    "administracionelectronica.navarra.es", "dogc.gencat.cat", "dogv.gva.es", "ebop.diputaciolleida.cat",
    "egoitza.gipuzkoa.eus", "ias1.larioja.org", "juntadeandalucia.es", "miprincipado.asturias.es", "sede.asturias.es", "s2.diphuelva.es",
    "sede.diputaciondesalamanca.gob.es", "ssl4.ddgi.cat", "www.araba.eus", "www.bizkaia.eus", "www.boa.aragon.es",
    "www.bocm.es", "www.bopcadiz.es", "www.boplaspalmas.net", "www.bopmalaga.es", "www.bopsantacruzdetenerife.es",
    "www.borm.es", "www.caib.es", "www.dip-alicante.es", "www.dipsegovia.es", "www.dipta.cat", "www.dipucuenca.es",
    "www.diputacionavila.es", "www.diputaciondepalencia.es", "www.diputaciondezamora.es", "www.euskadi.eus",
    "www.gobiernodecanarias.org", "www.xunta.gal"))
DOMINIOS |= {d: "fnmt" if d in _FNMT_BOLETINES else "sistema" for d in BOLETINES}
MAX_BYTES = 8_000_000
MAX_BYTES_PDF = 25_000_000  # un boletín entero en PDF puede pesar más que una página web
VERSION = "0.3.1"
# Marca de la copia: "desarrollo" aquí; empaquetar.py pone el perfil del paquete ("light" o "premium"). Va en el
# User-Agent: un identificador opaco, sin datos de nadie.
MARCA = "light"
AGENTE = f"Jurium-fuentes-oficiales/{VERSION} (consulta puntual; {MARCA})"
INTENTOS = 2  # un reintento ante 5xx o fallo de red (con más, una web caída tardaba ~30 s en decirlo); 429, ninguno
# Juegos de caracteres que se aceptan de una fuente; cualquier otro (p. ej. punycode, que es lentísimo) se lee
# como UTF-8.
CHARSETS = {"utf-8", "iso8859-1", "iso8859-15", "cp1252", "ascii"}
_fin_herramienta = None  # plazo total de la herramienta en curso (lo fija plazo_herramienta)


MAX_PETICIONES = 80  # por herramienta: una llamada no puede convertirse en una ráfaga contra una web oficial
_peticiones = 0


def queda_herramienta() -> float | None:
    """Segundos que le quedan a la herramienta en curso (None si no tiene plazo)."""
    return None if _fin_herramienta is None else _fin_herramienta - time.monotonic()


def plazo_herramienta(segundos: float | None) -> None:
    """Fija cuánto puede tardar en total la herramienta que empieza (todas sus peticiones juntas) y pone a cero su
    contador de peticiones."""
    global _fin_herramienta, _peticiones
    _fin_herramienta = time.monotonic() + segundos if segundos else None
    _peticiones = 0


class FuenteError(Exception):
    """La fuente no respondió o respondió algo que no se puede usar. codigo = HTTP, si lo hubo."""

    def __init__(self, mensaje: str, codigo: int | None = None):
        super().__init__(mensaje)
        self.codigo = codigo


# Regla 3: un DNI (8 cifras y letra), NIE (X/Y/Z + 7 y letra) o NIF de persona física (K/L/M) no sale nunca hacia
# una fuente, con separadores o sin ellos ('12.345.678-Z'). Las referencias jurídicas (BOE-A-2003-23186, V0648-24,
# CELEX, ECLI, 'Ley 58/2003') no tienen esa forma.
_DNI = re.compile(r"(?<![0-9A-Z])[XYZKLM]?[ .-]?(?:[0-9][ .]?){7,8}[ -]?[A-Z](?![0-9A-Z])")


def sin_dni(valor: str) -> None:
    """ValueError si el texto lleva un DNI o NIE (también con cifras Unicode o de ancho completo)."""
    normal = "".join(str(unicodedata.decimal(c)) if unicodedata.decimal(c, None) is not None else c
                     for c in unicodedata.normalize("NFKC", valor[:3000])).upper()
    if _DNI.search(normal):
        raise ValueError("Eso parece un DNI o NIE: el conector no envía datos de personas a las fuentes (regla 3). "
                         "Quítalo de la consulta.")


def comprobar_url(url: str) -> str:
    """Exige https y un host de la lista escrito tal cual: sin usuario, sin puerto, sin variantes."""
    # Sin espacios ni caracteres de control: urlsplit los quita en silencio y la conexión podría ver otra URL.
    if not isinstance(url, str) or not url.startswith("https://") or not url.isascii() \
            or any(c <= " " or c == "\x7f" for c in url):
        raise FuenteError(f"URL fuera de la lista de fuentes oficiales: {str(url)[:100]!r}")
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or p.netloc not in DOMINIOS:
        raise FuenteError(f"URL fuera de la lista de fuentes oficiales (host {p.netloc[:60]!r}).")
    return url


# Raíces de la FNMT, contrastadas el 1-nov-2026 en dos fuentes independientes (almacén de Mozilla y
# la sede de la FNMT). Huella fijada: si alguien cambia el archivo, el conector no arranca.
_RAICES_FNMT = {
    "EBC5570C29018C4D67B1AA127BAF12F703B4611EBC17B7DAB5573894179B93FA",  # AC RAIZ FNMT-RCM
    "554153B13D2CF9DDB753BFBE1A4E0AE08D0AA4187058FE60A2B862B2E4B87BCB",  # AC RAIZ FNMT-RCM SERVIDORES SEGUROS
}


def _contexto_fnmt() -> ssl.SSLContext:
    pems = re.findall(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----",
                      (Path(__file__).parent / "certificados" / "fnmt-raices.pem").read_text(encoding="ascii"), re.S)
    if {hashlib.sha256(ssl.PEM_cert_to_DER_cert(p)).hexdigest().upper() for p in pems} != _RAICES_FNMT:
        raise RuntimeError("certificados/fnmt-raices.pem no coincide con las huellas fijadas: no se usa.")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # verifica certificado y nombre; confía SOLO en la FNMT
    ctx.load_verify_locations(cadata="\n".join(pems))
    return ctx


_TLS = {"sistema": ssl.create_default_context(), "regcon": ssl.create_default_context(),
        "aeat": ssl.create_default_context(), "fnmt": _contexto_fnmt()}


class _SoloOficiales(urllib.request.HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        nueva = comprobar_url(urllib.parse.urljoin(req.full_url, newurl))  # FuenteError: sale de open() sin reintentos
        # La conexión usa la confianza TLS del host de origen: no se salta a un host con otra (p. ej. a uno de los
        # que solo confían en la raíz FNMT fijada), porque se validaría con el almacén de Windows.
        if DOMINIOS[urllib.parse.urlsplit(nueva).netloc] != DOMINIOS[urllib.parse.urlsplit(req.full_url).netloc]:
            raise FuenteError("Redirección a otra fuente con otra confianza TLS (host "
                              f"{urllib.parse.urlsplit(nueva).netloc[:60]!r}): no se sigue.")
        fp.close()  # la librería leería entero (sin tope) el cuerpo de la redirección: se descarta sin leerlo
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _HTTPS(urllib.request.HTTPSHandler):
    """Como el de la librería, pero apunta el socket de cada conexión para poder cortarla al vencer el plazo."""

    def __init__(self, context, abiertas: list):
        super().__init__(context=context)
        self.abiertas = abiertas

    def https_open(self, req):
        abiertas = self.abiertas

        class Conexion(http.client.HTTPSConnection):
            def connect(self):
                super().connect()
                abiertas.append(self.sock)  # el socket, no la conexión: la librería suelta su referencia

        return self.do_open(Conexion, req, context=self._context)


class Sesion:
    """Una conversación con una fuente (guarda cookies: la DGT y el TC las necesitan entre buscar y leer)."""

    def __init__(self):
        galletas = http.cookiejar.CookieJar()
        self._abiertas = []
        # ProxyHandler({}): directo a la fuente, nunca por un proxy del sistema o de HTTPS_PROXY.
        self._abridores = {ancla: urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _SoloOficiales, _HTTPS(ctx, self._abiertas),
            urllib.request.HTTPCookieProcessor(galletas))
            for ancla, ctx in _TLS.items()}

    def texto(self, url: str, params: dict | list | None = None, *, datos: dict | list | None = None,
              cabeceras: dict | None = None, timeout: int = 30) -> str:
        """timeout = plazo TOTAL de la petición (reintentos y redirecciones incluidos). La petición corre en un
        hilo aparte y, pase lo que pase dentro (una web que gotea cabeceras, redirecciones lentas), a los
        timeout segundos se responde con error: una fuente lenta o manipulada no bloquea el servidor."""
        cuerpo, charset, _ = self._traer(url, params, datos, cabeceras, timeout, MAX_BYTES)
        return cuerpo.decode(charset, "replace")

    def binario(self, url: str, timeout: int = 45) -> tuple[bytes, str]:
        """(bytes, tipo de contenido) de un documento (p. ej. el PDF de un boletín), con tope de MAX_BYTES_PDF."""
        cuerpo, _, tipo = self._traer(url, None, None, None, timeout, MAX_BYTES_PDF)
        return cuerpo, tipo

    def _traer(self, url, params, datos, cabeceras, timeout, max_bytes) -> tuple[bytes, str, str]:
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        comprobar_url(url)
        host = urllib.parse.urlsplit(url).netloc
        global _peticiones
        _peticiones += 1
        if _fin_herramienta is not None and _peticiones > MAX_PETICIONES:
            raise FuenteError(f"Esta consulta ya ha hecho {MAX_PETICIONES} peticiones a las fuentes: se para aquí para "
                              "no cargar las webs oficiales. Divídela en partes más pequeñas.")
        if _fin_herramienta is not None:
            queda = _fin_herramienta - time.monotonic()
            if queda < 2:
                raise FuenteError("La consulta agotó su tiempo total; acótala o repítela más tarde.")
            timeout = min(timeout, queda)
        cuerpo = urllib.parse.urlencode(datos).encode() if datos is not None else None
        pet = urllib.request.Request(url, data=cuerpo, headers={"User-Agent": AGENTE, **(cabeceras or {})})
        resultado = {}

        def trabajar():
            try:
                resultado["ok"] = self._pedir(pet, host, time.monotonic() + timeout, max_bytes)
            except Exception as e:
                resultado["error"] = e

        hilo = threading.Thread(target=trabajar, daemon=True)
        hilo.start()
        hilo.join(timeout + 1)
        abiertas, self._abiertas[:] = self._abiertas[:], []
        if hilo.is_alive():  # se corta la conexión: el hilo termina en vez de quedarse esperando
            for s in abiertas:
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            raise FuenteError(f"{host} no respondió en {int(timeout)} s; reintenta más tarde.")
        if "error" in resultado:
            raise resultado["error"]
        return resultado["ok"]

    def _pedir(self, pet: urllib.request.Request, host: str, limite: float, max_bytes: int) -> tuple[bytes, str, str]:
        for intento in range(INTENTOS):
            try:
                queda = limite - time.monotonic()
                if queda <= 1:
                    raise TimeoutError("se agotó el plazo de la consulta")
                with self._abridores[DOMINIOS[host]].open(pet, timeout=queda) as r:
                    trozos, leidos = [], 0
                    while trozo := r.read1(65536):  # read1 devuelve lo que haya: el plazo se comprueba de verdad
                        trozos.append(trozo)
                        leidos += len(trozo)
                        if leidos > max_bytes:
                            raise FuenteError("Respuesta demasiado grande; acota la consulta.")
                        if time.monotonic() > limite:
                            raise TimeoutError("la respuesta llega demasiado despacio")
                    try:
                        charset = codecs.lookup(r.headers.get_content_charset() or "utf-8").name
                    except LookupError:
                        charset = "utf-8"
                    if charset not in CHARSETS:
                        charset = "utf-8"
                    return b"".join(trozos), charset, r.headers.get_content_type()
            except urllib.error.HTTPError as e:
                if e.code in (500, 502, 503, 504) and intento < INTENTOS - 1 and limite - time.monotonic() > 5:
                    time.sleep(1.5 * (intento + 1))
                    continue
                motivo = {404: "no existe", 429: "pide esperar antes de otra consulta"}.get(
                    e.code, "caída temporal de la web oficial; reintenta en unos minutos" if e.code >= 500 else "error")
                raise FuenteError(f"{host} respondió HTTP {e.code} ({motivo}).", e.code) from None
            except (urllib.error.URLError, OSError) as e:  # incluye TimeoutError y fallos de TLS
                if intento < INTENTOS - 1 and limite - time.monotonic() > 5:
                    time.sleep(1.5 * (intento + 1))
                    continue
                motivo = getattr(e, "reason", e)
                if isinstance(motivo, TimeoutError) or "timed out" in str(motivo):
                    motivo = "no respondió a tiempo"
                raise FuenteError(f"No se pudo conectar con {host}: {motivo}. Reintenta en unos minutos.") from None
        raise FuenteError("Sin respuesta de la fuente.")

    def json(self, url: str, params: dict | None = None, **kw):
        texto_ = self.texto(url, params, cabeceras={"Accept": "application/json"}, **kw)
        try:
            return json.loads(texto_)
        except (ValueError, RecursionError):
            raise FuenteError("La fuente no devolvió JSON válido (¿no existe lo que buscas?).") from None


def analizar_xml(texto_: str) -> ET.Element:
    """XML de una fuente, con la estructura acotada (profundidad y número de elementos), comprobada por trozos
    de 64 KB: un XML anómalo se rechaza antes de ocupar memoria de más."""
    # Las fuentes no usan DTD; con una, las entidades multiplican el texto (hasta x100 dentro de lo que permite expat).
    mayus = texto_.upper()  # en cualquier parte (un comentario largo delante no lo esconde); ATTLIST copia sus
    # valores por defecto en cada elemento, así que también multiplica
    if any(d in mayus for d in ("<!DOCTYPE", "<!ENTITY", "<!ATTLIST", "<!ELEMENT", "<!NOTATION")):
        raise FuenteError("La fuente devolvió un XML con declaraciones de tipo (DTD); no se procesa.")
    lector = ET.XMLPullParser(events=("start", "end"))
    raiz, profundidad, elementos = None, 0, 0
    try:
        trozos = [texto_[i:i + 65536] for i in range(0, len(texto_), 65536)]
        for trozo in trozos + [None]:
            if trozo is None:
                lector.close()  # siempre: un XML sin cerrar es un error, no se acepta a medias
            else:
                lector.feed(trozo)
            for evento, elemento in lector.read_events():
                if evento == "end":
                    profundidad -= 1
                    continue
                raiz = elemento if raiz is None else raiz
                profundidad, elementos = profundidad + 1, elementos + 1
                if profundidad > 32 or elementos > 300_000:
                    raise FuenteError("La fuente devolvió un XML con una estructura anómala; no se procesa.")
    except ET.ParseError:
        raise FuenteError("La fuente devolvió un XML que no se puede leer; reintenta más tarde.") from None
    if raiz is None:
        raise FuenteError("La fuente devolvió un XML vacío.")
    return raiz


def parrafos(raiz: ET.Element, etiquetas: tuple) -> list[ET.Element]:
    """Elementos con esas etiquetas que no están dentro de otro de ellos, en orden. Así el texto de párrafos
    anidados se lee una sola vez (con iter() se copiaría una vez por nivel)."""
    salida, pila = [], [raiz]
    while pila:
        e = pila.pop()
        if e.tag in etiquetas:
            salida.append(e)
        else:
            pila.extend(reversed(e))
    return salida


# Regla del conector: el HTML de fuera nunca pasa por regex con repeticiones sin tope (salvo una clase de caracteres
# simple sin anidar, que es lineal) ni por html.parser (en
# Python 3.12.10 se cuelga con '<!--' repetido). Solo str.find/partition, que avanzan siempre: tiempo lineal.
_SALTO = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}
_FIN_OCULTO = re.compile(r"</(?:script|style)", re.I)


def plano(fragmento: str) -> str:
    """HTML a texto legible: párrafos y saltos de línea, sin etiquetas, comentarios, scripts ni entidades."""
    partes, i, n = [], 0, len(fragmento)
    while i < n:
        j = fragmento.find("<", i)
        if j < 0:
            partes.append(fragmento[i:])
            break
        partes.append(fragmento[i:j])
        if fragmento.startswith("<!--", j):
            k = fragmento.find("-->", j + 4)
            fin = k + 3
        else:
            k = fragmento.find(">", j)
            fin = k + 1
        if k < 0:  # etiqueta o comentario sin cerrar: el resto no es texto
            break
        nombre = (fragmento[j + 1:min(k, j + 12)].lstrip("/").split() or [""])[0].lower()
        if nombre in ("script", "style") and fragmento[j + 1] != "/":
            m = _FIN_OCULTO.search(fragmento, fin)
            if not m:
                break
            fin = fragmento.find(">", m.end()) + 1 or n
        elif nombre.rstrip("/") in _SALTO:
            partes.append("\n")
        i = fin
    # Una entidad numérica de miles de cifras haría fallar html.unescape (límite de Python): se quita antes.
    limpio = re.sub(r"&#[xX]?[0-9a-fA-F]{9,};?", "", "".join(partes))
    lineas = (" ".join(linea.split()) for linea in html.unescape(limpio).split("\n"))
    return "\n".join(linea for linea in lineas if linea)


def bloques(pagina: str, marcador: str, maximo: int = 20000) -> list[str]:
    """Trozos de la página que empiezan en cada aparición de marcador, de como mucho maximo caracteres."""
    return [marcador + t[:maximo] for t in pagina.split(marcador)[1:]]


def entre(texto_: str, inicio: str, fin: str) -> str:
    """Lo que hay entre la primera aparición de inicio y el siguiente fin, o '' (sin regex: lineal)."""
    i = texto_.find(inicio)
    if i < 0:
        return ""
    j = texto_.find(fin, i + len(inicio))
    return texto_[i + len(inicio):j] if j >= 0 else ""


def campo(patron: str, trozo: str, grupo: int = 1) -> str:
    """Primer grupo de una regex de longitud acotada (p. ej. 'BOE-A-[0-9]{4}-[0-9]{1,6}'), o ''."""
    m = re.search(patron, trozo)
    return m.group(grupo) if m else ""


def recortar(texto_: str, max_caracteres: int, desde: int | None = None) -> str:
    """Como mucho 100.000 caracteres por respuesta. Con desde (herramientas que lo admiten), se lee por partes y el
    aviso dice desde dónde seguir; sin él, solo se puede pedir hasta 100.000."""
    n = min(100_000, max(500, max_caracteres))
    inicio = max(0, desde or 0)
    trozo = texto_[inicio:inicio + n]
    quedan = len(texto_) - inicio - len(trozo)
    if quedan <= 0:
        return trozo
    seguir = f"pide el resto con desde={inicio + len(trozo)}" if desde is not None else \
        "pide más con max_caracteres (hasta 100.000)"
    return trozo + f"\n[... recortado: quedan {quedan} caracteres; {seguir}.]"


def corto(texto_, n: int = 5000):
    """Campo de texto libre con tope (una fuente manipulada no llena el contexto de Claude)."""
    return texto_[:n] + "…" if isinstance(texto_, str) and len(texto_) > n else texto_


def tope(n: int, maximo: int) -> int:
    """Número de resultados entre 1 y maximo, venga lo que venga."""
    return max(1, min(int(n), maximo))


def texto(url, params=None, **kw) -> str:
    return Sesion().texto(url, params, **kw)


def json_(url, params=None, **kw):
    return Sesion().json(url, params, **kw)
