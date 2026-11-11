# Fuentes oficiales (versión abierta) 0.3.0. Hecho por Jurium. Licencia MIT (LICENSE).
"""Texto de un PDF de boletín oficial con la librería estándar (sin dependencias), con topes de memoria y tiempo.

Lee lo que publican los boletines (BOE, autonómicos, BOP): flujos Flate, flujos de objetos, fuentes con ToUnicode o
WinAnsi/Differences y cifrado RC4 con contraseña de usuario vacía (PDF que se abren sin contraseña pero llevan
permisos). Lo demás (AES, imágenes escaneadas) se dice, no se adivina.

Defensa en capas: dentro, topes de memoria, objetos, operadores, pasos y tiempo en cada recorrido; fuera, el PDF no se
lee en el proceso de las herramientas sino en uno aparte (texto_pdf_aislado), con tope de memoria, que se mata si pasa
del plazo; y ese proceso de las herramientas es a su vez un trabajador que el servidor mata si se cuelga."""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import time
import zlib

MAX_DESCOMPRIMIDO = 40_000_000  # entre todos los flujos del documento
MAX_OBJETOS = 200_000
MAX_PAGINAS = 2_000
MAX_OPERADORES = 6_000_000  # entre todas las páginas
MAX_DICCIONARIO = 200_000  # caracteres que se recorren buscando el cierre de un diccionario o array
MAX_PASOS = 2_000_000  # vueltas al leer fuentes (anchos y tablas de caracteres), entre todas
MAX_FUENTES = 500  # fuentes distintas en todo el documento (un boletín usa una docena)
MAX_MEMORIA = 1_000_000_000  # bytes: el proceso aparte no puede pasar de aquí (un boletín real usa ~100 MB)
MAX_TEXTO = 3_000_000  # caracteres de texto que se sacan como mucho
PLAZO = 25  # segundos (dentro); el proceso aparte se mata a los PLAZO + 10


class PdfError(Exception):
    pass


class _Lleno(Exception):
    """Ya hay MAX_TEXTO caracteres: se para de leer (no es un error)."""


_OBJ = re.compile(rb"(\d{1,7})\s+(\d{1,5})\s+obj\b")
_REF = re.compile(rb"(\d{1,7})\s+\d{1,5}\s+R\b")
_NOMBRE = rb"[^\s/<>\[\]()%{}]{1,127}"
_RELLENO = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


class _Pdf:
    def __init__(self, datos: bytes):
        if not datos.startswith(b"%PDF-"):
            raise PdfError("No es un PDF.")
        self.datos, self.queda, self.operadores, self.control = datos, MAX_DESCOMPRIMIDO, 0, 5_000
        self.fin = time.monotonic() + PLAZO
        self.objs: dict[int, tuple[int, int]] = {}  # número -> (inicio, fin) en datos; el último gana (ediciones)
        self.sueltos: dict[int, bytes] = {}  # objetos que vienen dentro de flujos de objetos
        self.flujos: dict[int, bytes] = {}
        self.fuentes: dict[int, _Fuente] = {}
        self.cmaps: dict[int, dict] = {}  # ToUnicode ya leídos (varias fuentes comparten el mismo)
        self.pasos = self.caracteres = 0
        ms = []
        for m in _OBJ.finditer(datos):
            ms.append(m)
            if len(ms) > MAX_OBJETOS:
                raise PdfError("PDF con demasiados objetos.")
        for i, m in enumerate(ms):
            self.objs[int(m.group(1))] = (m.end(), ms[i + 1].start() if i + 1 < len(ms) else len(datos))
        self.clave = None
        cifrado = re.search(rb"/Encrypt\s+(\d{1,7})\s+\d{1,5}\s+R", datos)
        if cifrado:
            self.clave = self._clave(self.cabecera(int(cifrado.group(1))))
        for n in list(self.objs):
            cab = self.cabecera(n)
            if re.search(rb"/Type\s*/ObjStm", cab):
                self._desempaquetar(n, cab)

    def vigilar(self) -> None:
        if time.monotonic() > self.fin:
            raise PdfError("El PDF tarda demasiado en leerse; se corta.")

    def gastar(self, n: int) -> None:
        """Cuenta vueltas de bucles que no son operadores (tablas de fuentes): con tope y vigilando el plazo."""
        self.pasos += n
        if self.pasos > MAX_PASOS:
            raise PdfError("El PDF tiene tablas de fuentes anómalas; no se lee.")
        self.vigilar()

    # --- objetos ---
    def crudo(self, n: int) -> bytes:
        if n in self.sueltos:
            return self.sueltos[n]
        a, b = self.objs.get(n, (0, 0))
        trozo = self.datos[a:b]
        i = trozo.rfind(b"endobj")
        return trozo[:i] if i >= 0 else trozo

    def cabecera(self, n: int) -> bytes:
        """El diccionario del objeto, mirando solo sus primeros MAX_DICCIONARIO bytes (sin copiar el objeto entero:
        se pide muchas veces y un objeto puede pesar megas)."""
        if n in self.sueltos:
            c = self.sueltos[n][:MAX_DICCIONARIO]
        else:
            a, b = self.objs.get(n, (0, 0))
            c = self.datos[a:min(b, a + MAX_DICCIONARIO)]
        i = c.find(b"stream")
        c = c[:i] if i >= 0 else c
        i = c.rfind(b"endobj")
        return c[:i] if i >= 0 else c

    def flujo(self, n: int) -> bytes:
        self.vigilar()  # también al repetir uno ya leído: un formulario pintado mil veces no se escapa del plazo
        if n in self.flujos:
            return self.flujos[n]
        c = self.crudo(n)
        i = c.find(b"stream")
        if i < 0:
            return b""
        cab, i = c[:i], i + 6
        i += 2 if c[i:i + 2] == b"\r\n" else 1 if c[i:i + 1] in (b"\n", b"\r") else 0
        j = c.rfind(b"endstream")
        cuerpo = c[i:j if j >= i else len(c)]
        if self.clave and b"/XRef" not in cab:
            cuerpo = _rc4(hashlib.md5(self.clave + n.to_bytes(4, "little")[:3] + bytes(2)).digest()
                          [:min(len(self.clave) + 5, 16)], cuerpo, self.vigilar)
        filtros = re.findall(rb"/(" + _NOMBRE + rb")", self.valor(cab, b"Filter"))
        if filtros and filtros != [b"FlateDecode"] and filtros != [b"Fl"]:
            cuerpo = b""  # imágenes u otros filtros: no son texto
        elif filtros:
            d = zlib.decompressobj()
            try:
                sale = d.decompress(cuerpo, self.queda + 1)  # tope: una bomba de compresión no pasa de aquí
            except zlib.error:
                sale = b""
            if len(sale) > self.queda:
                raise PdfError("El PDF descomprimido pasa del tope; no se lee.")
            self.queda -= len(sale)
            cuerpo = sale
        self.flujos[n] = cuerpo
        return cuerpo

    def _desempaquetar(self, n: int, cab: bytes) -> None:
        m_n, m_f = re.search(rb"/N\s+(\d{1,6})", cab), re.search(rb"/First\s+(\d{1,9})", cab)
        if not (m_n and m_f):
            return
        f, primero = self.flujo(n), int(m_f.group(1))
        cuantos = 2 * min(int(m_n.group(1)), MAX_OBJETOS)
        nums = [int(x) for x in f[:primero].split(None, cuantos)[:cuantos] if x.isdigit()]
        pares = list(zip(nums[::2], nums[1::2]))
        anterior = -1
        for k, (num, off) in enumerate(pares):
            fin = pares[k + 1][1] if k + 1 < len(pares) else len(f) - primero
            if off <= anterior or fin < off:  # desplazamientos que no crecen: objetos solapados, flujo anómalo
                break
            anterior = off
            if num not in self.objs:  # cada objeto, con tope: no puede ser una copia de medio flujo
                self.sueltos[num] = f[primero + off:primero + min(fin, off + MAX_DICCIONARIO)]

    def valor(self, dic: bytes, clave: bytes) -> bytes:
        """El valor de /clave en un diccionario: referencia, nombre, número, array o diccionario (lo primero que
        aparezca con ese nombre exacto)."""
        for m in re.finditer(rb"/" + re.escape(clave) + rb"(?![^\s/<>\[\]()%{}])", dic):
            resto = dic[m.end():m.end() + MAX_DICCIONARIO].lstrip()
            if resto.startswith(b"<<"):
                return resto[:_cierre(resto, b"<<", b">>")]
            if resto.startswith(b"["):
                return resto[:_cierre(resto, b"[", b"]")]
            r = _REF.match(resto) or re.match(rb"/?" + _NOMBRE, resto)
            return r.group(0) if r else b""
        return b""

    def resolver(self, v: bytes) -> bytes:
        m = _REF.fullmatch(v.strip())
        return self.cabecera(int(m.group(1))).lstrip() if m else v

    # --- cifrado ---
    def _clave(self, enc: bytes) -> bytes:
        v, r = re.search(rb"/V\s+(\d)", enc), re.search(rb"/R\s+(\d)", enc)
        o, p = re.search(rb"/O\s*<([0-9A-Fa-f]{64})>", enc), re.search(rb"/P\s+(-?\d{1,11})", enc)
        ident = re.search(rb"/ID\s*\[\s*<([0-9A-Fa-f]{2,64})>", self.datos)
        if not (v and r and o and p and ident) or v.group(1) not in b"124" or b"/AESV" in enc \
                or b"/Standard" not in enc:
            raise PdfError("El PDF está cifrado de una forma que este lector no abre.")
        largo = re.search(rb"/Length\s+(\d{2,3})", enc)
        n = 5 if v.group(1) == b"1" else max(5, min(16, int(largo.group(1)) // 8 if largo else 16))
        meta = bytes([255]) * 4 if int(r.group(1)) >= 4 and re.search(rb"/EncryptMetadata\s+false", enc) else b""
        h = hashlib.md5(_RELLENO + bytes.fromhex(o.group(1).decode()) + (int(p.group(1)) & 0xFFFFFFFF)
                        .to_bytes(4, "little") + bytes.fromhex(ident.group(1).decode()) + meta).digest()
        if int(r.group(1)) >= 3:
            for _ in range(50):
                h = hashlib.md5(h[:n]).digest()
        return h[:n]

    # --- páginas ---
    def _raiz(self) -> bytes:
        fin = len(self.datos)
        for _ in range(20):  # los 20 últimos 'trailer', hacia atrás
            i = self.datos.rfind(b"trailer", 0, fin)
            if i < 0:
                break
            if b"/Root" in (trozo := self.datos[i + 7:i + 3007]):
                return self.resolver(self.valor(trozo, b"Root"))
            fin = i
        for n in sorted(self.objs, key=lambda n: self.objs[n][0], reverse=True):  # flujo de referencias (PDF 1.5)
            cab = self.cabecera(n)
            if re.search(rb"/Type\s*/XRef", cab) and b"/Root" in cab:
                return self.resolver(self.valor(cab, b"Root"))
        raise PdfError("PDF sin catálogo: no se puede leer.")

    def paginas(self):
        pila, vistos, hechas = [(self.valor(self._raiz(), b"Pages"), b"", 0)], set(), 0
        while pila and hechas < MAX_PAGINAS:
            self.vigilar()
            ref, recursos_padre, prof = pila.pop()
            m = _REF.fullmatch(ref.strip())
            if not m or int(m.group(1)) in vistos or prof > 30:
                continue
            vistos.add(int(m.group(1)))
            nodo = self.cabecera(int(m.group(1)))
            recursos = self.resolver(self.valor(nodo, b"Resources")) or recursos_padre  # se heredan del padre
            if re.search(rb"/Type\s*/Pages\b", nodo):
                pila.extend((h + b" 0 R", recursos, prof + 1)
                            for h in reversed(_REF.findall(self.valor(nodo, b"Kids"))[:MAX_PAGINAS]))
            else:
                hechas += 1
                yield nodo, recursos

    def fuentes_de(self, recursos: bytes) -> dict:
        dic = self.resolver(self.valor(recursos, b"Font"))
        fuentes = {}
        for nombre, num in re.findall(rb"/(" + _NOMBRE + rb")\s+(\d{1,7})\s+\d{1,5}\s+R", dic)[:200]:
            n = int(num)
            if n not in self.fuentes:
                if len(self.fuentes) >= MAX_FUENTES:
                    raise PdfError("PDF con demasiadas fuentes.")
                self.fuentes[n] = _Fuente(self, n)
            fuentes[nombre] = self.fuentes[n]
        return fuentes


def _cierre(s: bytes, abre: bytes, cierra: bytes) -> int:
    """Fin del diccionario o array que empieza en s[0] (anidado), sin pasar de MAX_DICCIONARIO."""
    nivel, i, n = 0, 0, min(len(s), MAX_DICCIONARIO)
    while i < n:
        if s.startswith(abre, i):
            nivel, i = nivel + 1, i + len(abre)
        elif s.startswith(cierra, i):
            nivel, i = nivel - 1, i + len(cierra)
            if nivel == 0:
                return i
        else:
            i += 1
    return n


def _rc4(clave: bytes, datos: bytes, vigilar) -> bytes:
    s, j = list(range(256)), 0
    for i in range(256):
        j = (j + s[i] + clave[i % len(clave)]) & 255
        s[i], s[j] = s[j], s[i]
    sale, i, j = bytearray(len(datos)), 0, 0
    for k, b in enumerate(datos):
        if not k & 0xFFFFF:  # cada MB: en Python puro, 24 MB son segundos
            vigilar()
        i = (i + 1) & 255
        j = (j + s[i]) & 255
        s[i], s[j] = s[j], s[i]
        sale[k] = b ^ s[(s[i] + s[j]) & 255]
    return bytes(sale)


def _num(v: bytes) -> float:
    try:
        return float(v)
    except ValueError:
        return 0.0


def _utf16(h: bytes) -> str:
    try:
        return bytes.fromhex(h.decode("ascii")).decode("utf-16-be", "replace") if h else ""
    except ValueError:
        return ""


def _cmap(pdf: _Pdf, s: bytes) -> dict[int, str]:
    """Tabla código -> texto de un ToUnicode. Cada vuelta cuenta en el presupuesto del PDF."""
    mapa: dict[int, str] = {}
    for bloque in _bloques(s, b"beginbfchar", b"endbfchar"):
        pares = re.findall(rb"<([0-9A-Fa-f]{1,8})>\s*<([0-9A-Fa-f]{0,64})>", bloque)[:10_000]
        pdf.gastar(len(pares) + 1)
        for a, b in pares:
            mapa[int(a, 16)] = _utf16(b)
    for bloque in _bloques(s, b"beginbfrange", b"endbfrange"):
        for m in re.finditer(rb"<([0-9A-Fa-f]{1,8})>\s*<([0-9A-Fa-f]{1,8})>\s*(<[0-9A-Fa-f]{0,64}>|\[[^\[\]]{0,20000}\])",
                             bloque):
            a, b, c = m.groups()
            ini = int(a, 16)
            fin = min(int(b, 16), ini + 65_535)
            pdf.gastar(max(0, fin - ini) + 1)  # un rango que se repite sobre los mismos códigos también cuenta
            if c.startswith(b"["):
                for k, h in enumerate(re.findall(rb"<([0-9A-Fa-f]{0,64})>", c)[:fin - ini + 1]):
                    mapa[ini + k] = _utf16(h)
            elif base := _utf16(c[1:-1]):
                for k in range(fin - ini + 1):
                    mapa[ini + k] = base[:-1] + chr(min(ord(base[-1]) + k, 0x10FFFF))
    return mapa


def _bloques(s: bytes, inicio: bytes, fin: bytes) -> list[bytes]:
    """Lo que hay entre cada inicio y su fin, de forma lineal (una regex no voraz sería cuadrática si falta el fin)."""
    return [t.partition(fin)[0] for t in s.split(inicio)[1:501]]


_WIN = {i: bytes([i]).decode("cp1252", "replace") for i in range(32, 256)}
_GLIFOS = {"space": " ", "aacute": "á", "eacute": "é", "iacute": "í", "oacute": "ó", "uacute": "ú", "ntilde": "ñ",
           "Aacute": "Á", "Eacute": "É", "Iacute": "Í", "Oacute": "Ó", "Uacute": "Ú", "Ntilde": "Ñ", "udieresis": "ü",
           "Udieresis": "Ü", "ccedilla": "ç", "Ccedilla": "Ç", "ordfeminine": "ª", "ordmasculine": "º", "hyphen": "-",
           "endash": "–", "emdash": "—", "quoteright": "’", "quoteleft": "‘", "quotedblleft": "“", "quotedblright": "”",
           "periodcentered": "·", "euro": "€", "bullet": "•", "agrave": "à", "egrave": "è", "ograve": "ò",
           "idieresis": "ï", "fi": "fi", "fl": "fl", "degree": "°", "section": "§", "percent": "%", "period": ".",
           "comma": ",", "colon": ":", "semicolon": ";", "parenleft": "(", "parenright": ")", "slash": "/"}
_GLIFOS |= {c: c for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"}
_GLIFOS |= dict(zip(("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"), "0123456789"))


def _glifo(nombre: str) -> str:
    if nombre in _GLIFOS:
        return _GLIFOS[nombre]
    m = re.fullmatch(r"uni([0-9A-Fa-f]{4})", nombre)
    return chr(int(m.group(1), 16)) if m else ""


class _Fuente:
    def __init__(self, pdf: _Pdf, num: int):
        cab = pdf.cabecera(num)
        self.dos_bytes = b"/Type0" in cab or b"Identity-H" in cab
        self.mapa: dict[int, str] = {}
        # Anchos de los glifos (milésimas de cuerpo): dicen dónde acaba cada trozo de texto, para saber si el
        # siguiente va pegado (misma palabra) o con hueco (espacio).
        self.anchos: dict[int, float] = {}
        self.ancho_defecto = 500.0
        if self.dos_bytes:
            hija = pdf.resolver((re.findall(rb"\d{1,7}\s+\d{1,5}\s+R", pdf.valor(cab, b"DescendantFonts")) or [b""])[0])
            dw = re.match(rb"\d{1,5}", pdf.valor(hija, b"DW"))
            self.ancho_defecto = float(dw.group(0)) if dw else 1000.0
            w = pdf.resolver(pdf.valor(hija, b"W"))
            # [^\[\]]: una lista sin cerrar ('1[1[1[...') no hace que la regex recorra el resto desde cada posición.
            for m in re.finditer(rb"(\d{1,5})\s*\[([^\[\]]{0,20000})\]|(\d{1,5})\s+(\d{1,5}\s+[\d.]{1,8})",
                                 w[1:-1] if w.startswith(b"[") else b""):
                ini, lista, fin, ancho = m.groups()
                if ini:
                    valores = re.findall(rb"-?[\d.]{1,8}", lista)[:5000]
                    pdf.gastar(len(valores) + 1)
                    for k, v in enumerate(valores):
                        self.anchos[int(ini) + k] = _num(v)
                elif fin:
                    hasta, valor = ancho.split()
                    tramo = range(int(fin), min(int(hasta), int(fin) + 5000) + 1)
                    pdf.gastar(len(tramo) + 1)
                    for k in tramo:
                        self.anchos[k] = _num(valor)
        else:
            primero = re.match(rb"\d{1,5}", pdf.valor(cab, b"FirstChar"))
            lista = pdf.resolver(pdf.valor(cab, b"Widths"))
            if primero:
                pdf.gastar(257)  # cuenta aunque el array sea compartido: si no, 500 fuentes lo leen gratis
                for k, v in enumerate(re.findall(rb"-?[\d.]{1,8}", lista)[:256]):
                    self.anchos[int(primero.group(0)) + k] = _num(v)
        tu = _REF.match(pdf.valor(cab, b"ToUnicode").strip())
        if tu:
            if int(tu.group(1)) not in pdf.cmaps:
                pdf.cmaps[int(tu.group(1))] = _cmap(pdf, pdf.flujo(int(tu.group(1)))[:2_000_000])
            self.mapa = pdf.cmaps[int(tu.group(1))]
        enc = pdf.resolver(pdf.valor(cab, b"Encoding"))
        dif = pdf.valor(enc, b"Differences") if enc.startswith(b"<<") else b""
        self.base = dict(_WIN) if dif else _WIN  # la tabla común se comparte; solo se copia si se cambia
        codigo = 0
        for tok in re.findall(rb"\d{1,5}|/" + _NOMBRE, dif)[:3000]:
            if tok[:1] == b"/":
                self.base[codigo] = _glifo(tok[1:].decode("latin-1")) or self.base.get(codigo, "")
                codigo += 1
            else:
                codigo = int(tok)


    def codigos(self, b: bytes) -> list[int]:
        return [int.from_bytes(b[i:i + 2], "big") for i in range(0, len(b) - 1, 2)] if self.dos_bytes else list(b)

    def ancho(self, b: bytes) -> float:
        """Ancho del texto en milésimas del cuerpo de letra."""
        if self.dos_bytes:  # sin construir la lista de códigos (una cadena de megas la haría enorme)
            return sum(self.anchos.get(int.from_bytes(b[i:i + 2], "big"), self.ancho_defecto)
                       for i in range(0, len(b) - 1, 2))
        return sum(self.anchos.get(c, self.ancho_defecto) for c in b)

    def decodificar(self, b: bytes) -> str:
        return "".join(self.mapa.get(c) or ("" if self.dos_bytes else self.base.get(c, "")) for c in self.codigos(b))


_TOKEN = re.compile(rb"\s*(?:(\()|<([0-9A-Fa-f\s]{0,40000})>|(<<|>>|\[|\])|(/[^\s/<>\[\]()%{}]{0,127})|"
                    rb"([+-]?(?:\d{1,12}\.?\d{0,12}|\.\d{1,12}))|([A-Za-z'\"*]{1,3}[0-9]?)|(%[^\r\n]{0,10000})|(.))", re.S)
_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}


def _cadena(s: bytes, i: int) -> tuple[bytes, int]:
    """Cadena literal desde después de '(' (paréntesis anidados y escapes). Devuelve (bytes, posición final)."""
    nivel, sale, n = 1, bytearray(), len(s)
    while i < n:
        c = s[i]
        if c == 0x5C:  # barra invertida
            sig = s[i + 1:i + 2]
            if sig in _ESCAPES:
                sale += _ESCAPES[sig]
                i += 2
            elif sig.isdigit():
                m = re.match(rb"[0-7]{1,3}", s[i + 1:i + 4])
                sale.append(int(m.group(0), 8) & 255 if m else 0)
                i += 1 + (len(m.group(0)) if m else 1)
            else:
                i += 2
            continue
        if c == 0x28:
            nivel += 1
        elif c == 0x29:
            nivel -= 1
            if nivel == 0:
                return bytes(sale), i + 1
        sale.append(c)
        i += 1
    return bytes(sale), n


class _Cursor:
    """Dónde va el texto en la página. Al moverse decide qué separa lo que viene de lo anterior: salto de línea si
    cambia la altura, espacio si hay hueco y nada si sigue la misma palabra (hay boletines que parten las palabras en
    trozos colocados uno tras otro)."""

    def __init__(self, sale: list):
        self.sale, self.tam, self.tc, self.tw, self.tl = sale, 1.0, 0.0, 0.0, 0.0
        self.fin_x = self.fin_y = None  # dónde acabó el último texto (en la página)
        self.empezar()

    def empezar(self, a=1.0, d=1.0, e=0.0, f=0.0) -> None:
        self.a, self.d, self.e, self.f = a or 1.0, d or 1.0, e, f
        self.lx = self.ly = self.cx = self.cy = 0.0

    def linea(self, tx: float, ty: float) -> None:
        self.lx, self.ly = self.lx + tx, self.ly + ty
        self.cx, self.cy = self.lx, self.ly

    def escribir(self, texto_: str, ancho: float, espacios: int) -> None:
        x, y = self.e + self.cx * self.a, self.f + self.cy * self.d
        if self.fin_x is not None and self.sale and not self.sale[-1].endswith("\n"):
            alto, em = abs(self.tam * self.d), abs(self.tam * self.a)
            if abs(y - self.fin_y) > 0.5 * alto:
                self.sale.append("\n")
            elif not self.sale[-1].endswith(" ") and (x - self.fin_x > 0.15 * em or x < self.fin_x - 2 * em):
                self.sale.append(" ")  # hueco, o vuelta atrás en la misma altura (otra columna)
        self.sale.append(texto_)
        self.cx += ancho * self.tam / 1000 + self.tc * len(texto_) + self.tw * espacios
        self.fin_x, self.fin_y = self.e + self.cx * self.a, y

    def hueco(self, v: float) -> None:  # número dentro de TJ: desplazamiento en milésimas
        self.cx -= v * self.tam / 1000
        if v < -180 and self.sale and not self.sale[-1].endswith((" ", "\n")):
            self.sale.append(" ")


def _contenido(pdf: _Pdf, s: bytes, fuentes: dict, recursos: bytes, prof: int) -> str:
    """El texto de un flujo de contenido, en el orden en que se pinta."""
    sale, pila, fuente, i = [], [], None, 0
    c = _Cursor(sale)

    def mostrar(b: bytes) -> None:
        if fuente:
            texto_ = fuente.decodificar(b[:2 * (MAX_TEXTO - pdf.caracteres) + 2])  # no decodificar más de lo que cabe
            pdf.caracteres += len(texto_)
            if pdf.caracteres > MAX_TEXTO:
                raise _Lleno
            c.escribir(texto_, fuente.ancho(b), b.count(32) if not fuente.dos_bytes else 0)

    while i < len(s):
        m = _TOKEN.match(s, i)
        if not m:
            break
        i = m.end()
        pdf.operadores += 1
        if pdf.operadores >= pdf.control:  # no '% 5000': los saltos de cadenas y Do lo esquivarían
            pdf.control = pdf.operadores + 5_000
            pdf.vigilar()
            if pdf.operadores > MAX_OPERADORES:
                raise PdfError("El PDF tiene demasiado contenido; se corta.")
        if m.group(1):
            b, i = _cadena(s, i)
            pdf.operadores += len(b) // 1000  # una cadena de megas cuesta como miles de operadores
            pila.append(("s", b))
        elif m.group(2) is not None:
            h = re.sub(rb"\s", b"", m.group(2))
            pila.append(("s", bytes.fromhex((h + b"0" if len(h) % 2 else h).decode("ascii"))))
        elif m.group(3):
            pila.append(("d", m.group(3)))
        elif m.group(4):
            pila.append(("n", m.group(4)))
        elif m.group(5):
            pila.append(("f", float(m.group(5))))
        elif m.group(6):
            op = m.group(6)
            nums = [v for t, v in pila if t == "f"]
            cadenas = [v for t, v in pila if t == "s"]
            if op == b"BI":  # imagen en línea: hasta su fin
                j = s.find(b"EI", i)
                i = j + 2 if j >= 0 else len(s)
            elif op == b"BT":
                c.empezar()
            elif op == b"Tf":
                nombres = [v for t, v in pila if t == "n"]
                fuente = fuentes.get(nombres[-1][1:]) if nombres else fuente
                c.tam = nums[-1] if nums else c.tam
            elif op in (b"Tc", b"Tw", b"TL") and nums:
                setattr(c, op.decode().lower(), nums[-1])
            elif op == b"Tm" and len(nums) >= 6:
                c.empezar(nums[-6], nums[-3], nums[-2], nums[-1])
            elif op in (b"Td", b"TD") and len(nums) >= 2:
                if op == b"TD":
                    c.tl = -nums[-1]
                c.linea(nums[-2], nums[-1])
            elif op in (b"T*", b"'", b'"'):
                if op == b'"' and len(nums) >= 2:
                    c.tw, c.tc = nums[-2], nums[-1]
                c.linea(0, -c.tl if c.tl else -c.tam)
                if op != b"T*" and cadenas:
                    mostrar(cadenas[-1])
            elif op == b"Tj" and cadenas:
                mostrar(cadenas[-1])
            elif op == b"TJ":
                for t, v in pila:
                    if t == "s":
                        mostrar(v)
                    elif t == "f":
                        c.hueco(v)
            elif op == b"Do" and prof < 3:  # formularios (XObject) que llevan texto
                pdf.operadores += 1_000  # cada Do mira un objeto entero: cuenta como mucho trabajo
                pdf.vigilar()
                nombres = [v for t, v in pila if t == "n"]
                ref = _REF.match(pdf.valor(pdf.resolver(pdf.valor(recursos, b"XObject")), nombres[-1][1:]).strip())                     if nombres else None
                if ref and re.search(rb"/Subtype\s*/Form", cab := pdf.cabecera(int(ref.group(1)))):
                    rec = pdf.resolver(pdf.valor(cab, b"Resources")) or recursos
                    sale.append("\n" + _contenido(pdf, pdf.flujo(int(ref.group(1))), pdf.fuentes_de(rec) or fuentes,
                                                    rec, prof + 1) + "\n")
            pila = []
        if len(pila) > 5_000:
            pila = pila[-50:]
    return "".join(sale)


def _sin_cabeceras(paginas: list[str]) -> list[str]:
    """Quita las cabeceras y pies que se repiten en las páginas (fecha y número del boletín, 'cve:', 'Verificable
    en...'): mirando las 8 primeras y 8 últimas líneas de cada página, con las cifras igualadas."""
    if len(paginas) < 3:
        return paginas
    forma = lambda linea: re.sub(r"[0-9]+", "#", linea)  # noqa: E731
    cuenta: dict[str, int] = {}
    for p in paginas:
        lineas = p.split("\n")
        for linea in set(lineas[:8] + lineas[-8:]):
            cuenta[forma(linea)] = cuenta.get(forma(linea), 0) + 1
    repetidas = {f for f, n in cuenta.items() if n >= max(3, len(paginas) // 2) and f.strip()}
    salida = []
    for p in paginas:
        lineas = p.split("\n")
        borde = set(range(8)) | set(range(len(lineas) - 8, len(lineas)))
        salida.append("\n".join(linea for k, linea in enumerate(lineas) if k not in borde or forma(linea) not in repetidas))
    return salida


def texto_pdf(datos: bytes, max_caracteres: int = 3_000_000) -> str:
    """Texto del PDF, página a página (separadas por salto de página '\\f'), sin cabeceras ni pies repetidos."""
    pdf, partes, total = _Pdf(datos), [], 0
    for nodo, recursos in pdf.paginas():
        refs = _REF.findall(pdf.valor(nodo, b"Contents"))
        if len(refs) == 1 and b"stream" not in pdf.crudo(int(refs[0])):  # apunta a una lista de flujos
            refs = _REF.findall(pdf.cabecera(int(refs[0])))
        flujo = b"\n".join(pdf.flujo(int(r)) for r in list(dict.fromkeys(refs))[:200])
        try:
            t = _contenido(pdf, flujo, pdf.fuentes_de(recursos), recursos, 0)
        except _Lleno:
            partes.append("[... el PDF sigue: se ha parado en el tope de texto.]")
            break
        t = "\n".join(" ".join(linea.split()) for linea in t.split("\n"))
        partes.append(re.sub(r"\n{2,}", "\n", t).strip())
        total += len(partes[-1])
        if total > max_caracteres:
            break
    return "\n\f".join(_sin_cabeceras(partes))


def texto_pdf_aislado(datos: bytes, plazo: float | None = None) -> str:
    """texto_pdf en un proceso aparte (el mismo Python, aislado: -I -B), que se mata si pasa del plazo. Lo que haga
    un PDF manipulado (bucles, memoria) le pasa a ese proceso, no al servidor. plazo: lo que le quede a la
    herramienta, si es menos que PLAZO + 10."""
    plazo = PLAZO + 10 if plazo is None else min(PLAZO + 10, plazo)
    if plazo < 2:
        raise PdfError("La consulta agotó su tiempo total antes de leer el PDF; repítela.")
    try:
        r = subprocess.run([sys.executable, "-I", "-B", __file__], input=datos, capture_output=True,
                           timeout=plazo)
    except subprocess.TimeoutExpired:
        raise PdfError("El PDF tarda demasiado en leerse; se corta.") from None
    if r.returncode != 0:
        motivo = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise PdfError(motivo[-1][:300] if motivo and r.returncode == 2 else "el lector de PDF falló con este archivo")
    return r.stdout[:4 * MAX_TEXTO + 1000].decode("utf-8", "replace")


def _job(tope: int | None):
    """Un Job Object de Windows (ctypes, librería estándar) que mata a sus procesos al cerrarse y, si se pide, les pone
    tope de memoria. Devuelve (job, kernel32); PdfError si no se puede crear."""
    import ctypes
    from ctypes import wintypes

    class _Io(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class _Basica(ctypes.Structure):
        _fields_ = [("a", ctypes.c_longlong), ("b", ctypes.c_longlong), ("flags", wintypes.DWORD),
                    ("min", ctypes.c_size_t), ("max", ctypes.c_size_t), ("procesos", wintypes.DWORD),
                    ("afinidad", ctypes.c_size_t), ("prioridad", wintypes.DWORD), ("clase", wintypes.DWORD)]

    class _Extendida(ctypes.Structure):
        _fields_ = [("basica", _Basica), ("io", _Io), ("memoria_proceso", ctypes.c_size_t),
                    ("memoria_trabajo", ctypes.c_size_t), ("pico_proceso", ctypes.c_size_t),
                    ("pico_trabajo", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    info = _Extendida()
    info.basica.flags = 0x2000 | (0x100 if tope else 0)  # KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.memoria_proceso = tope or 0
    job = k32.CreateJobObjectW(None, None)
    if not (job and k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))):
        raise PdfError("No se pudo crear el control del proceso.")
    return job, k32


def _limitar_memoria(tope: int = MAX_MEMORIA) -> None:
    """Tope de memoria del propio proceso, puesto por el sistema operativo. Si no se puede poner, PdfError: sin tope
    no hay garantía. Sus hijos lo heredan y mueren con él."""
    if sys.platform == "win32":
        job, k32 = _job(tope)
        if not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
            raise PdfError("No se pudo limitar la memoria del proceso; no se trabaja.")
    else:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (tope, tope))


def cerrar_job(job) -> None:
    if sys.platform == "win32" and job:
        import ctypes
        ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(job))


def atar_al_padre(proceso) -> object | None:
    """Mete un proceso hijo en un Job que se cierra cuando muere este proceso (aunque lo maten de golpe): así el hijo
    no se queda huérfano y colgado. Hay que guardar lo que devuelve mientras viva el hijo."""
    if sys.platform != "win32":
        return None
    job, k32 = _job(None)
    if not k32.AssignProcessToJobObject(job, int(proceso._handle)):
        raise PdfError("No se pudo atar el proceso de las herramientas al servidor.")
    return job


if __name__ == "__main__":  # el proceso aparte: PDF por la entrada, texto por la salida, error por stderr
    try:
        _limitar_memoria()
        sys.stdout.buffer.write(texto_pdf(sys.stdin.buffer.read(30_000_000)).encode("utf-8", "replace"))
    except (PdfError, MemoryError) as e:  # en UTF-8: el texto de la consola de Windows no lo es
        sys.stderr.buffer.write((str(e) if isinstance(e, PdfError) else "El PDF pide demasiada memoria; se corta.")
                                .encode("utf-8"))
        sys.exit(2)
