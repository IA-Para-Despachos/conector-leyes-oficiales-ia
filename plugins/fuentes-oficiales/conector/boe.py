# Fuentes oficiales (versión abierta) 0.3.0. Hecho por Jurium. Licencia MIT (LICENSE).
"""BOE y BORME: API de datos abiertos (sumarios, legislación consolidada, documentos) y el buscador
web de legislación (la búsqueda por palabras de la API devuelve error 500 desde, al menos, nov-2026)."""
from __future__ import annotations

import re
import time
import unicodedata
from datetime import date, datetime, timedelta

from red import (FuenteError, Sesion, analizar_xml, bloques, campo, corto, entre, json_, parrafos, plano, recortar,
                 texto, tope)

API = "https://www.boe.es/datosabiertos/api"
WEB = "https://www.boe.es"


def fecha_aaaammdd(fecha: str | None) -> str:
    """'2026-10-30', '30/10/2026', '20261030' u 'hoy'/'ayer' -> '20261030'."""
    f = " ".join(_sin_acentos(fecha or "hoy").strip().lower().split())
    if f in ("hoy", ""):
        return date.today().strftime("%Y%m%d")
    if f == "ayer":
        return (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    larga = re.fullmatch(r"([0-9]{1,2}) de ([a-z]{4,10}) de ([0-9]{4})", f)  # '30 de octubre de 2026'
    if larga and larga.group(2) in _MESES:
        f = f"{larga.group(1)}/{_MESES[larga.group(2)]}/{larga.group(3)}"
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(f, formato).strftime("%Y%m%d")
        except ValueError:
            pass
    if re.fullmatch(r"[0-9]{1,4}[-/.][0-9]{1,2}[-/.][0-9]{1,4}", f):
        raise ValueError(f"La fecha {fecha[:40]!r} no existe (revisa el día y el mes).")
    raise ValueError(f"Fecha no válida: {fecha[:40]!r} (usa AAAA-MM-DD o DD/MM/AAAA).")


def fecha_ddmmaaaa(fecha: str) -> str:
    """Formato de los formularios de Hacienda, BDNS y TC."""
    f = fecha_aaaammdd(fecha)
    return f"{f[6:]}/{f[4:6]}/{f[:4]}"


def _lista(x) -> list:
    return x if isinstance(x, list) else ([] if x is None else [x])


# Sin unicodedata.normalize: en Python 3.12 tarda ~80 s con 8 MB de 'Á' (un texto manipulado colgaría el servidor).
# Tabla de letras con tilde (castellano, catalán, gallego, euskera) y, aparte, las tildes que lleguen sueltas.
_TILDES = str.maketrans("áàâäãåéèêëíìîïóòôöõúùûüñçÁÀÂÄÃÅÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÑÇ",
                        "aaaaaaeeeeiiiiooooouuuuncAAAAAAEEEEIIIIOOOOOUUUUNC")
_DIACRITICOS = re.compile(r"[̀-ͯ]")


def _sin_acentos(s: str) -> str:
    return _DIACRITICOS.sub("", s.translate(_TILDES))


def _contiene(texto_: str, busca: str | None) -> bool:
    return not busca or _sin_acentos(busca).lower() in _sin_acentos(texto_).lower()


def _llano(s: str) -> str:
    return " " + " ".join(re.sub(r"[^a-z0-9]+", " ", _sin_acentos(s).lower()).split()) + " "


def _contiene_palabras(llano: str, palabras: list[str]) -> bool:
    """Todas las palabras, como palabras enteras ('IVA' no casa con 'conservación'); una sigla vale también
    desarrollada ('IRPF' casa con 'Impuesto sobre la Renta de las Personas Físicas')."""
    return all(f" {p} " in llano or (p in _SIGLAS and _llano(_SIGLAS[p]) in llano) for p in palabras)


_VACIAS = {"del", "las", "los", "que", "para", "por", "con", "una", "uno", "sus", "sobre", "como", "entre", "sin"}


def pasajes(partes: list, buscar_en: str, etiqueta=None) -> dict:
    """Los párrafos donde aparecen todas las palabras de buscar_en (al principio de palabra: 'iva' no casa con
    'efectiva'; 'deduc' sí con 'deducción'), literales y con su sección. partes = [(sección, [párrafos])];
    etiqueta(sección, párrafo) devuelve el nuevo rótulo dentro de la sección ('fundamento jurídico 3') o None.
    Si ningún párrafo las tiene todas, se mira cada rótulo entero. Hasta 8 pasajes de 1.500 caracteres."""
    # 'artículo 22' busca la cita ('art. 22.4', 'artículo 22'), no un 'artículo' y un '22' sueltos en el párrafo.
    art = re.match(r"\s*art(?:[ií]culos?|s?\.?)\s*([0-9]+(?:\.[0-9]+)*)(?![0-9])(.*)$", buscar_en, re.I | re.S)
    numero_art = " ".join(re.findall("[0-9]+", art.group(1))) if art else ""
    terminos = [t for t in _llano(art.group(2) if art else buscar_en).split()
                if (len(t) >= 3 or t.isdigit()) and t not in _VACIAS][:6]
    if not terminos and not numero_art:
        raise ValueError("buscar_en: la materia en una o dos palabras ('vehículo', 'deducción vehículo').")
    def tiene(t: str) -> bool:  # al principio de palabra; un número, como palabra entera ('82' no casa con '820')
        llano = _llano(t[:200_000])
        return ((not numero_art or re.search(rf" art(?:iculos?|s)? {numero_art}(?![0-9])", llano))
                and all(re.search(rf"(?<![0-9a-z]){p}(?![0-9])", llano) if p.isdigit() else f" {p}" in llano
                        for p in terminos))
    bloques_, sueltos = [], []  # (rótulo, [párrafos]) y párrafos que casan
    for seccion, lista in partes:
        rotulo = seccion
        for p in lista[:5000]:
            nuevo = etiqueta(seccion, p) if etiqueta else None
            if nuevo or not bloques_ or bloques_[-1][0] != rotulo:
                rotulo = f"{seccion} · {nuevo}" if nuevo else rotulo
                bloques_.append((rotulo, []))
            bloques_[-1][1].append(p)
            if tiene(p):
                sueltos.append((rotulo, p))
    nota = None
    if not sueltos:  # las palabras, en párrafos distintos del mismo rótulo
        sueltos = [(r, "\n".join(ps)) for r, ps in bloques_ if tiene("\n".join(ps))]
        nota = "Ningún párrafo tiene todas las palabras: son rótulos que las tienen en párrafos distintos."
    # Primero dos por rótulo (que los antecedentes no se coman los ocho y falten los fundamentos), luego el resto.
    cuenta, elegidos = {}, []
    for k, (rotulo, _) in enumerate(sueltos):
        cuenta[rotulo] = cuenta.get(rotulo, 0) + 1
        if cuenta[rotulo] <= 2 and len(elegidos) < 8:
            elegidos.append(k)
    elegidos += [k for k in range(len(sueltos)) if k not in elegidos][:8 - len(elegidos)]
    salida = {"pasajes": []}
    for rotulo, t in (sueltos[k] for k in sorted(elegidos)):
        ini = 0
        if len(t) > 1500:  # ventana alrededor de la primera palabra
            i = _sin_acentos(t[:200_000]).lower().find(terminos[0])
            ini = max(0, i - 300)
        salida["pasajes"].append({"donde": rotulo, "texto": ("[...] " if ini else "") + t[ini:ini + 1500].strip()
                                  + (" [... sigue]" if len(t) > ini + 1500 else "")})
    if len(sueltos) > 8:
        salida["nota_pasajes"] = f"Aparece en {len(sueltos)} sitios; se muestran 8, como mucho 2 por apartado (acota con más palabras)."
    if nota and sueltos:
        salida["nota"] = nota
    if not sueltos:
        salida["aviso"] = ("No aparece con esas palabras (se buscan al principio de palabra y todas a la vez): prueba "
                           "con menos, con la raíz ('deduc') o con un sinónimo. Para el texto entero, sin buscar_en.")
    return salida


class SinBoletin(FuenteError):
    """Ese día no hay diario (domingo, festivo o fecha futura)."""


def _sumario(diario: str, fecha: str) -> dict:
    f = fecha_aaaammdd(fecha)
    try:
        datos = json_(f"{API}/{diario}/sumario/{f}")
    except FuenteError as e:
        if e.codigo in (400, 404):
            raise SinBoletin(f"No hay {diario.upper()} del {f[6:]}/{f[4:6]}/{f[:4]}: no se publicó ese día (domingo, "
                             "sábado en el BORME, festivo) o la fecha es futura.",
                             e.codigo) from None
        raise
    if str(datos.get("status", {}).get("code")) != "200":
        raise SinBoletin(f"No hay {diario.upper()} publicado el {f[6:]}/{f[4:6]}/{f[:4]}.")
    return datos["data"]["sumario"]


def sumario_boe(fecha: str = "hoy", seccion: str | None = None, contiene: str | None = None,
                max_resultados: int = 100) -> dict:
    s = _sumario("boe", fecha)
    secciones = [sec for d in _lista(s.get("diario")) for sec in _lista(d.get("seccion"))]
    if seccion:  # admite '1', '2A', 'III', 'V.B'...
        romanos = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5"}
        cod = re.sub(r"[^0-9A-Z]", "", seccion.upper())
        cod = romanos.get(cod.rstrip("ABC"), cod.rstrip("ABC")) + cod[len(cod.rstrip("ABC")):]
        if cod not in ("1", "2", "2A", "2B", "3", "4", "5", "5A", "5B", "5C"):
            raise ValueError("Sección no válida: usa 1, 2A, 2B, 3, 4, 5A, 5B o 5C.")
        # Válida pero ausente ese día (no todos los días hay de todas): 0 resultados, no error.
        secciones = [x for x in secciones if str(x.get("codigo", "")).upper().startswith(cod)]
    # Cada campo de la fuente se recorta ANTES de normalizarlo, y departamento y epígrafe se normalizan una sola vez:
    # un sumario manipulado (nombres de megas repetidos en cada item) no multiplica el trabajo.
    txt = lambda x, n=1000: corto(x if isinstance(x, str) else "", n)  # noqa: E731
    busca = _llano(txt(contiene, 200)).split() if contiene else []
    limite = tope(max_resultados, 100)  # lo que pasa de 100 no llegaría a Claude

    def todos():  # (sección, departamento, epígrafe, item). Un BOE real tiene unos cientos de items y epígrafes:
        n = 0      # tope de 5.000 contando ambos, y el departamento se normaliza una vez, no por epígrafe
        for sec in secciones:
            for dep in _lista(sec.get("departamento")):
                nombre_dep = txt(dep.get("nombre"), 300)
                llano_dep = _llano(nombre_dep) if busca else ""
                for e in _lista(dep.get("epigrafe")) + [{"item": dep.get("item")}]:
                    n += 1
                    if n > 5000:
                        return
                    if not isinstance(e, dict) or not e.get("item"):
                        continue
                    epigrafe = txt(e.get("nombre"), 300)
                    contexto = llano_dep + (_llano(epigrafe) if busca and epigrafe else "")
                    for it in _lista(e.get("item")):
                        n += 1
                        if n > 5000:
                            return
                        yield sec, nombre_dep, epigrafe, contexto, it if isinstance(it, dict) else {}

    items, total = [], 0
    for sec, nombre_dep, epigrafe, contexto, it in todos():
        titulo = txt(it.get("titulo"))
        if busca and not _contiene_palabras(_llano(titulo) + contexto, busca):
            continue
        total += 1
        if len(items) < limite:  # solo se construye lo que se devuelve
            url = it.get("url_html")
            items.append({"id": txt(it.get("identificador"), 40), "titulo": titulo,
                          "seccion": txt(sec.get("nombre"), 300), "departamento": nombre_dep,
                          "epigrafe": epigrafe or None,
                          "fuente": url if isinstance(url, str)
                          and re.fullmatch(r"https://www\.boe\.es/[A-Za-z0-9/_.?=&%-]{1,200}", url) else None})
    return {"fecha": fecha_aaaammdd(fecha), "total": total, "items": items,
            **({"nota": "Nada ese día con esas palabras (enteras) o en esa sección."} if not items and (contiene or seccion)
               else {}),
            "fuente": f"{WEB}/boe/dias/{fecha_aaaammdd(fecha)[:4]}/{fecha_aaaammdd(fecha)[4:6]}/{fecha_aaaammdd(fecha)[6:]}/"}


def novedades_boe(contiene: str, desde: str, hasta: str = "hoy", seccion: str | None = None) -> dict:
    if not (contiene or "").strip():
        raise ValueError("Indica qué buscar en 'contiene' (p. ej. 'convenio colectivo').")
    d0, d1 = (datetime.strptime(fecha_aaaammdd(x), "%Y%m%d").date() for x in (desde, hasta))
    if d1 < d0 or (d1 - d0).days > 31:
        raise ValueError("El periodo debe ir de 'desde' a 'hasta' y no pasar de 31 días.")
    encontrados, sin_boe, cortado = [], 0, None
    limite = time.monotonic() + 80  # hasta 27 sumarios; deja margen dentro del plazo total de la herramienta
    dia = d0
    total = 0
    while dia <= d1:
        if time.monotonic() > limite:
            cortado = f"Barrido cortado por tiempo: revisado hasta el {(dia - timedelta(days=1)).isoformat()}. Pide el resto aparte."
            break
        if dia.weekday() < 6:  # el BOE sale de lunes a sábado
            try:
                del_dia = sumario_boe(dia.strftime("%Y%m%d"), seccion, contiene, 100)
                total += del_dia["total"]
                encontrados += [dict(i, fecha=dia.isoformat()) for i in del_dia["items"]]
            except SinBoletin:  # festivo; cualquier otro fallo de la fuente se propaga, no se oculta
                sin_boe += 1
        dia += timedelta(days=1)
    return {"contiene": contiene, "desde": d0.isoformat(), "hasta": d1.isoformat(),
            "total": total, "items": encontrados[::-1][:100], "dias_sin_boe": sin_boe,  # recientes primero
            "fuente": f"{WEB}/boe/dias/",
            **({"aviso": cortado} if cortado else {}),
            **({"nota": "Ningún título del BOE trae todas esas palabras en el periodo (se buscan como palabras "
                        "enteras). Prueba con menos palabras o con sinónimos."} if not encontrados else {})}


_SIGLAS = {"iva": "impuesto sobre el valor anadido", "irpf": "impuesto sobre la renta de las personas fisicas",
           "lgt": "general tributaria", "lec": "de enjuiciamiento civil", "lsc": "de sociedades de capital",
           "lopd": "proteccion de datos personales", "lopdgdd": "proteccion de datos personales",
           "autonomos": "estatuto del trabajo autonomo", "startups": "fomento del ecosistema de las empresas emergentes",
           "leta": "estatuto del trabajo autonomo", "itp": "transmisiones patrimoniales y actos juridicos documentados",
           "lmv": "de los mercados de valores y de los servicios de inversion",
           "del mercado de valores": "de los mercados de valores", "mercado de valores": "mercados de valores", "teletrabajo": "trabajo a distancia",
           "antifraude": "medidas de prevencion y lucha contra el fraude fiscal",
           "ley de la renta": "ley del impuesto sobre la renta de las personas fisicas",
           "lisos": "infracciones y sanciones en el orden social",
           "morosidad": "medidas de lucha contra la morosidad en las operaciones comerciales",
           "smi": "salario minimo interprofesional", "iprem": "indicador publico de renta de efectos multiples",
           "isd": "impuesto sobre sucesiones y donaciones", "ibi": "impuesto sobre bienes inmuebles",
           "iae": "impuesto sobre actividades economicas", "erte": "regulacion temporal de empleo",
           "ertes": "regulacion temporal de empleo"}
_SUSTITUIDAS = {
    "sociedades anonimas": ("sociedades de capital", "La Ley de Sociedades Anónimas (TR de 1989) está derogada: la "
                            "sustituye la Ley de Sociedades de Capital (RDLeg 1/2010), que es la que sigue."),
    "sociedades de responsabilidad limitada": ("sociedades de capital", "La Ley de Sociedades de Responsabilidad "
                                               "Limitada (1995) está derogada: la sustituye la Ley de Sociedades de "
                                               "Capital (RDLeg 1/2010), que es la que sigue."),
    "firma electronica": ("servicios electronicos de confianza", "La Ley 59/2003 de firma electrónica está "
                          "derogada: la sustituye la Ley 6/2020, de servicios electrónicos de confianza, que es la que "
                          "sigue."),
    "procedimiento laboral": ("reguladora de la jurisdiccion social", "La Ley de Procedimiento Laboral (RDLeg 2/1995) "
                              "está derogada: la sustituye la Ley 36/2011, reguladora de la jurisdicción social, que "
                              "es la que sigue.")}
_RANGOS = {"ley organica": ("ley organica",), "lo": ("ley organica",), "ley": ("ley",), "l": ("ley",),
           "real decreto legislativo": ("real decreto legislativo",), "rdleg": ("real decreto legislativo",),
           "rdl": ("real decreto legislativo", "real decreto-ley"), "real decreto-ley": ("real decreto-ley",),
           "real decreto ley": ("real decreto-ley",), "rdley": ("real decreto-ley",), "real decreto": ("real decreto",),
           "rd": ("real decreto",), "orden": ("orden",),
           # autonómicas (examen de preguntas de oro, 5-nov: el DLeg 1/2010 de Madrid no se encontraba)
           "decreto legislativo": ("decreto legislativo",), "dleg": ("decreto legislativo",),
           "decreto-ley": ("decreto-ley",), "decreto ley": ("decreto-ley",), "decreto": ("decreto",)}
_RANGO = (r"ley organica|lo|ley|l|real decreto legislativo|rdleg|rdl|real decreto-ley|real decreto ley|rdley|"
          r"real decreto|rd|orden|decreto legislativo|dleg|decreto-ley|decreto ley|decreto")
# Comunidades tal como el BOE las nombra en el departamento de cada norma autonómica (sin tildes, '-' como espacio).
_COMUNIDADES = {"madrid": "madrid", "andalucia": "andalucia", "cataluna": "cataluna", "catalunya": "cataluna",
                "valenciana": "valencia", "valencia": "valencia", "navarra": "navarra", "pais vasco": "pais vasco",
                "euskadi": "pais vasco", "galicia": "galicia", "murcia": "murcia", "castilla y leon": "castilla y leon",
                "castilla la mancha": "castilla la mancha", "aragon": "aragon", "canarias": "canarias",
                "cantabria": "cantabria", "extremadura": "extremadura", "la rioja": "rioja", "rioja": "rioja",
                "illes balears": "balears", "baleares": "balears", "asturias": "asturias", "ceuta": "ceuta",
                "melilla": "melilla"}
_COMUNIDAD = re.compile(r",?\s*\b(?:(?:de|del|de la)\s+)?(?:(?:comunidad|comunitat|region|principado|ciudad)(?:\s+"
                        r"(?:autonoma|foral))?\s+(?:de\s+(?:la\s+|las\s+)?|del\s+)?)?(" + "|".join(
                            sorted(_COMUNIDADES, key=len, reverse=True)) + r")\b")
_ID_NORMA = re.compile(r"([A-Za-z]{2,6})-([A-Za-z])-([0-9]{4})-([0-9]{1,6})")


def id_norma(texto_: str) -> str | None:
    """'BOE-A-2003-23186' o una autonómica consolidada en el BOE ('BOCM-m-2010-90068', 'DOCM-q-2010-90043'),
    escrita como sea; None si no tiene esa forma (los BOE-B, BORME y FIS no son normas consolidadas)."""
    m = _ID_NORMA.fullmatch((texto_ or "").strip())
    if not m:
        return None
    prefijo, letra = m.group(1).upper(), m.group(2)
    if prefijo == "BOE":
        return f"BOE-A-{m.group(3)}-{m.group(4)}" if letra.upper() == "A" else None
    if prefijo in ("BORME", "FIS"):
        return None
    return f"{prefijo}-{letra.lower()}-{m.group(3)}-{m.group(4)}"


def anio(ident: str) -> str:
    """Año del id de una norma ('BOE-A-2003-23186' -> '2003'; también 'BOCM-m-2010-90068')."""
    partes = (ident or "").split("-")
    return partes[2] if len(partes) > 2 else ""


def comunidad(consulta: str) -> tuple[str, str | None]:
    """('ley 5/2021', 'andalucia') de 'ley 5/2021 de andalucia': la consulta sin la comunidad y la comunidad."""
    llana = consulta.replace("-", " ")  # 'castilla-la mancha'; 'decreto-ley' queda 'decreto ley', que también vale
    m = _COMUNIDAD.search(llana)
    if not m:
        return consulta, None
    return " ".join((llana[:m.start()] + " " + llana[m.end():]).split()) or consulta, _COMUNIDADES[m.group(1)]


def _de_la_comunidad(r: dict, clave: str) -> bool:
    return clave in _sin_acentos(r["titulo"]).lower().replace("-", " ").partition(")")[0]
# En el análisis del BOE, una derogación parcial nombra lo que deroga antes del "por <norma>".
_PARCIAL = ("art", "disposici", "precepto", "apartado", "anexo", "parrafo", "capitulo", "titulo", "letra", "numero",
            "inciso", "seccion", "tabla", "lo indicado", "lo senalado", "en lo que", "en cuanto", "cuanto se oponga")


_DEROGADAS: dict[str, str | None] = {}  # caché de la sesión, solo con respuestas que llegaron bien


def derogada(ident: str) -> str | None:
    """Si el BOE recoge que la norma está derogada o sustituida entera (aunque sea con excepciones), lo dice; si
    no, None. El campo 'estatus_derogacion' del BOE no es fiable (la LO 15/1999 sale como no derogada). Primero la
    nota inicial del texto consolidado ('Norma derogada...', 'entró en vigor el texto refundido...'); si no hay
    nota, el análisis de la norma. Se guarda en caché (una verificación repite la misma ley), salvo si la fuente
    falló: un fallo de red no puede quedar como 'no derogada' toda la sesión."""
    return estado_derogacion(ident)[0]


def _marca_derogacion(ident: str) -> dict:
    """{'derogada': motivo}, {'derogacion': 'no se pudo comprobar…'} o {} si consta vigente."""
    motivo, comprobado = estado_derogacion(ident)
    if not comprobado:
        return {"derogacion": "no se pudo comprobar (el BOE no respondió): compruébalo con articulo_vigente"}
    return {"derogada": motivo} if motivo else {}


def estado_derogacion(ident: str) -> tuple[str | None, bool]:
    """(motivo o None, si se pudo comprobar). Un fallo del BOE no puede pasar por 'no derogada'."""
    if ident not in _DEROGADAS:
        try:
            _DEROGADAS[ident] = _derogada(ident)
        except FuenteError:
            return None, False
    return _DEROGADAS[ident], True


def _derogada(ident: str) -> str | None:
    try:
        nota = plano(texto(f"{API}/legislacion-consolidada/id/{ident}/texto/bloque/no",
                           cabeceras={"Accept": "application/xml"}, timeout=15))[:3000]  # la nota es corta
    except FuenteError as e:
        if e.codigo != 404:  # sin nota es lo normal; otro fallo, se propaga y no se guarda
            raise
        nota = ""
    llana = " ".join(_sin_acentos(nota).lower().split())
    for marca in ("norma derogada", "norma anulada"):
        if marca in llana:
            i = llana.find(marca)
            return f"{nota[i:i + 250].strip()} (nota del BOE)."
    if "entro en vigor el texto refundido" in llana:
        i = llana.find("con fecha") if "con fecha" in llana else llana.find("entro en vigor")
        return f"Sustituida: {nota[i:i + 250].strip()} (nota del BOE)."
    if nota:
        return None
    try:
        datos = json_(f"{API}/legislacion-consolidada/id/{ident}/analisis", timeout=15)
        derogaciones = [str(p.get("texto") or "")[:500] for d in _lista(datos.get("data"))
                        for r in _lista(d.get("referencias")) for g in _lista(r.get("posteriores"))
                        for p in _lista(g.get("posterior")) if (p.get("relacion") or {}).get("texto") == "SE DEROGA"]
    except FuenteError as e:
        if e.codigo not in (400, 404):
            raise
        # Sin texto consolidado (p. ej. la Ley 43/1995): el análisis viene en el XML del diario.
        raiz = analizar_xml(texto(f"{WEB}/diario_boe/xml.php?id={ident}", timeout=15))
        derogaciones = [(p.findtext("texto") or "")[:500] for p in raiz.iter("posterior")
                        if (p.findtext("palabra") or "").strip() == "SE DEROGA"]
    for texto_ in derogaciones:
        cabeza = _sin_acentos(texto_.lower()).partition(" por ")[0].lstrip(", ")
        # 'salvo las disposiciones...' es derogación total con excepciones (la Ley 43/1995 por el TRLIS).
        if cabeza.startswith("salvo") or not any(x in cabeza for x in _PARCIAL):
            return f"Derogada {texto_.lstrip(', ')[:200]} (según el análisis del BOE)."
    return None


def _resultados(params: list) -> list[dict]:
    pagina = texto(f"{WEB}/buscar/legislacion.php", params)
    if "No se han encontrado documentos" not in pagina and 'class="listadoResult' not in pagina:
        raise FuenteError("El buscador del BOE no devolvió la página de resultados (¿ha cambiado la web?); reintenta.")
    resultados = []
    for bloque in bloques(pagina, '<li class="resultado-busqueda">', 5000)[:200]:  # el BOE da 50 por página
        cabeza = bloque.split("</li>")[0]
        # 'id=BOE-A-...' o el de una autonómica consolidada ('id=BOCM-m-2010-90068')
        ident = id_norma(campo(r"id=([A-Za-z]{2,6}-[A-Za-z]-[0-9]{4}-[0-9]{1,6})", cabeza) or "")
        if ident:
            titulo = plano(cabeza).replace("\n", " ")
            corte = min((i for i in (titulo.find(m) for m in ("Ir al documento", "Ref. ", "Más...")) if i >= 0),
                        default=len(titulo))
            resultados.append({"id": ident, "titulo": titulo[:corte].strip(), "fuente": f"{WEB}/buscar/act.php?id={ident}"})
    return resultados


def buscar_legislacion(texto_busqueda: str, solo_vigente: bool = True, ambito: str = "estatal",
                       max_resultados: int = 10, consolidadas: bool = True, comprobar_derogadas: bool = True,
                       ampliar: bool = True) -> dict:
    """consolidadas=False busca también normas sin texto consolidado (p. ej. leyes que solo modifican otras)."""
    ambitos = {"todo": "", "estatal": "1", "autonomica": "2", "autonómica": "2"}
    if ambito.lower() in ("europea", "ue", "union europea"):
        raise ValueError("Las normas de la UE no están en el buscador del BOE: usa buscar_norma_ue (por palabras del "
                         "título) o articulo_ue (RGPD, 'Directiva 2006/112/CE'...).")
    if ambito.lower() not in ambitos:
        raise ValueError("ambito: estatal, autonomica o todo.")
    # El buscador del BOE falla con tildes en la URL; sin tildes busca igual (no distingue).
    consulta = " ".join(_sin_acentos(texto_busqueda).lower().split())
    if not consulta:
        raise ValueError("Indica qué buscar.")
    sigla = consulta.replace(".", "").replace(" ", "")
    if sigla in LEYES and len(consulta) <= 12:  # 'LIRPF', 'TRLRHL': la sigla resuelve sin buscar
        consulta = sigla
        ident = LEYES[sigla]
        datos = json_(f"{API}/legislacion-consolidada/id/{ident}/metadatos").get("data") or [{}]
        titulo = (datos[0] if isinstance(datos, list) else {}).get("titulo") or ident
        return {"busqueda": texto_busqueda, "total": 1, "resultados": [{
            "id": ident, "titulo": corto(titulo, 400), "fuente": f"{WEB}/buscar/act.php?id={ident}",
            **_marca_derogacion(ident)}], "fuente": f"{WEB}/buscar/legislacion.php",
            "nota": "Sigla reconocida: es esta norma."}
    # Por rango y número: 'LO 3/2018', 'RDL 2/2015', 'ley 58/2003'. Se busca el número y se elige el rango.
    consulta, ccaa = comunidad(consulta)
    if ccaa and ambito.lower() == "estatal":  # 'ley 5/2021 de andalucia', 'tributos cedidos madrid'
        ambito = "todo"
    por_numero = re.fullmatch(rf"(?:({_RANGO}) ?)?([0-9]{{1,4}}/[0-9]{{4}})", consulta)
    sustituida = None
    for antigua, (nueva, explicacion) in _SUSTITUIDAS.items():  # leyes que ya no existen: se busca la que las sustituye
        if antigua in consulta:
            consulta, sustituida = nueva, explicacion
    for sigla, nombre in _SIGLAS.items():  # 'reglamento del iva' -> '... del impuesto sobre el valor anadido'
        consulta = re.sub(rf"\b{sigla}\b", nombre, consulta)
    ampliada = False
    if por_numero:
        rango, consulta = por_numero.groups()
        rangos = _RANGOS.get(rango or "", ("",))

    def clave_numero(r):  # 'LO 3/2018': primero la de ese rango y número exactos
        cuerpo = _sin_acentos(r["titulo"]).lower().partition(")")[2].strip()
        return (not any(cuerpo.startswith(f"{x} {consulta}".lstrip()) or (not x and f" {consulta}," in cuerpo)
                        for x in rangos), len(cuerpo))

    params = [("campo[0]", "ID_SRC"), ("dato[0]", ambitos[ambito.lower()]), ("operador[0]", "and"),
              ("campo[1]", "NOVIGENTE"), ("dato[1]", "N" if solo_vigente else ""), ("operador[1]", "and"),
              ("campo[3]", "CONSO"), ("dato[3]", "(3 or 4)" if consolidadas else ""), ("operador[3]", "and"),
              ("campo[2]", "DOC"), ("dato[2]", consulta), ("operador[2]", "and"),
              ("checkbox_solo_tit", "S"), ("page_hits", "50"),
              ("sort_field[0]", "PESO"), ("sort_order[0]", "desc"),
              ("sort_field[1]", "REF"), ("sort_order[1]", "asc"), ("accion", "Buscar")]
    resultados = _resultados(params)
    if ccaa:  # de esa comunidad, si las hay (si no, las demás: el nombre puede no estar en el título)
        resultados = [r for r in resultados if _de_la_comunidad(r, ccaa)] or resultados
    if por_numero and not any(clave_numero(r)[0] is False for r in resultados) and ampliar and (solo_vigente or consolidadas):
        # Se pidió una norma concreta y no está entre las vigentes y consolidadas: puede estar derogada o no tener
        # texto consolidado (Ley 24/1988, RDLeg 1564/1989). Se busca otra vez sin esos filtros.
        params = [(k, "" if k in ("dato[1]", "dato[3]") else v) for k, v in params]
        otras = [r for r in _resultados(params) if clave_numero(r)[0] is False and (not ccaa or _de_la_comunidad(r, ccaa))]
        if otras:
            resultados = otras + resultados
            ampliada = True
    # El BOE pone delante normas que solo modifican o derogan partes de la buscada, y no marca bien las derogadas
    # (la Ley 22/2003 Concursal sale como vigente). Orden: primero las que traen la frase entera y no la modifican;
    # luego la norma principal ("Ley 37/1992, de 28 de diciembre, del <frase>", o la que aprueba su texto refundido
    # o, si se busca un reglamento, el reglamento); después la que no acota la materia tras la frase (Código Penal
    # antes que Código Penal Militar); la más reciente; y el título más corto. Las derogadas enteras, al final.
    reglamento = consulta.startswith("reglamento")
    frase = re.sub(r"^(ley organica|ley|reglamento)\s+((del?|de la|de los|de las)\s+)?", "", consulta)  # 'ley de la x' -> 'x'

    def clave(r):
        t = _sin_acentos(r["titulo"]).lower()
        cuerpo = t.partition(")")[2].strip().rstrip(".")  # quita "Departamento (BOE nnn de fecha)"
        antes, _, despues = cuerpo.partition(frase)  # antes: ahí se ve si es una norma que modifica otra
        resto = re.sub(r"^[^,]{1,60},\s*de\s+[0-9]{1,2}\s+de\s+[a-z]{4,10},?\s*", "", antes).strip()  # sin "Ley n, de fecha,"
        refundido = "se aprueba el texto refundido" in antes
        principal = refundido or (resto.startswith("por el que se aprueba el reglamento") if reglamento
                                  else resto in ("", "de", "del", "de la", "de los", "de las"))
        cola = despues.strip(" ,")  # tras la frase: 'Militar' o 'tratados para fines...' acotan la materia
        # 'y garantía de...', 'personales y garantía...' (suma materia) o 'por la que se...' no acotan
        general = not cola or cola.startswith(("por ", "y ", "e ")) or " y " in cola.split(",")[0][:40]
        # Entre leyes principales, la más reciente (una ley o texto refundido nuevo sustituye al anterior del mismo
        # nombre; las derogadas, además, se comprueban y bajan después); entre reglamentos, el de título más corto
        # (el general, no el que regula un aspecto: facturación antes que el sistema Verifactu).
        reciente = -int(anio(r["id"]) or 0) if principal and not reglamento else 0
        return (frase not in t, any(x in antes for x in ("modific", "deroga", "reforma", "medidas")),
                not principal, not general, reciente, len(cuerpo))

    resultados.sort(key=clave_numero if por_numero else clave)
    # Las primeras no pueden presentarse como vigentes si están derogadas: se comprueban las cinco primeras (una o
    # dos peticiones cada una) y las derogadas van al final, marcadas.
    revisadas = resultados[:5] if comprobar_derogadas else []
    for r in revisadas:
        r.update(_marca_derogacion(r["id"]))
    nota = ("Ordenado poniendo primero la norma principal vigente. Se comprueba la derogación de las cinco "
            "primeras; del resto, compruébala con articulo_vigente antes de usarla.")
    if por_numero:
        # Se pidió una norma concreta: si está, va primera aunque esté derogada (marcada); si no, se dice.
        exactas = [r for r in resultados if clave_numero(r)[0] is False]
        for r in exactas:
            r["exacta"] = True
        resto = [r for r in resultados if not r.get("exacta")]  # sin 'in' sobre listas: lineal
        resultados = exactas + [r for r in resto if "derogada" not in r] + [r for r in resto if "derogada" in r]
        if not exactas:
            nota = (f"No hay ninguna norma '{texto_busqueda.strip()[:40]}' entre las "
                    f"{'vigentes' if solo_vigente else 'consolidadas'} del BOE: puede estar derogada (prueba "
                    "solo_vigente=False) o no tener texto consolidado. Lo que sigue NO es la norma pedida: son las "
                    "que más se parecen.")
        elif "derogada" in exactas[0]:
            nota = f"La norma pedida está derogada o sustituida: {exactas[0]['derogada']}"
        elif ampliada:
            nota = ("La norma pedida no está entre las vigentes con texto consolidado: puede estar derogada (se dice "
                    "arriba si el BOE lo recoge) o no tener texto consolidado; léela con leer_boe por su id.")
    elif revisadas:
        resultados = ([r for r in revisadas if "derogada" not in r] + resultados[5:]
                      + [r for r in revisadas if "derogada" in r])
    if not resultados:
        nota = ("Sin resultados. Busca solo por el nombre de la ley o su sigla, sin artículo ni año ('estatuto de los "
                "trabajadores', 'LGT'); para un artículo, articulo_vigente; si puede estar derogada, solo_vigente=False.")
    if sustituida:
        nota = f"{sustituida} {nota}"
    return {"busqueda": texto_busqueda, "total": len(resultados), "resultados": resultados[:tope(max_resultados, 50)],
            "fuente": f"{WEB}/buscar/legislacion.php", "nota": nota}


# Siglas habituales -> id del texto consolidado (comprobados uno a uno en el BOE el 3-nov-2026). Es la forma en
# que se cita una ley en un despacho; resolverla aquí ahorra una búsqueda y no puede equivocarse de norma.
LEYES = {
    "cc": "BOE-A-1889-4763", "ce": "BOE-A-1978-31229", "cp": "BOE-A-1995-25444", "lec": "BOE-A-2000-323",
    "lecrim": "BOE-A-1882-6036", "et": "BOE-A-2015-11430", "lgss": "BOE-A-2015-11724", "lrjs": "BOE-A-2011-15936",
    "ljca": "BOE-A-1998-16718", "lpac": "BOE-A-2015-10565", "lrjsp": "BOE-A-2015-10566", "lgt": "BOE-A-2003-23186",
    "liva": "BOE-A-1992-28740", "lirpf": "BOE-A-2006-20764", "lis": "BOE-A-2014-12328", "lau": "BOE-A-1994-26003",
    "loreg": "BOE-A-1985-11672", "trlsru": "BOE-A-2015-11723", "trlitpajd": "BOE-A-1993-25359", "trlhl": "BOE-A-2004-4214",
    "litpajd": "BOE-A-1993-25359",
    "lph": "BOE-A-1960-10906", "lsc": "BOE-A-2010-10544", "lopdgdd": "BOE-A-2018-16673", "lopd": "BOE-A-2018-16673",
    "trlrhl": "BOE-A-2004-4214", "lrhl": "BOE-A-2004-4214", "lisd": "BOE-A-1987-28141",
    "litp": "BOE-A-1993-25359", "riva": "BOE-A-1992-28925", "rirpf": "BOE-A-2007-6820", "ris": "BOE-A-2015-7771",
    "lprl": "BOE-A-1995-24292", "lisos": "BOE-A-2000-15060", "leta": "BOE-A-2007-13409", "lcsp": "BOE-A-2017-12902",
    "trlgdcu": "BOE-A-2007-20555", "lgdcu": "BOE-A-2007-20555", "lopj": "BOE-A-1985-12666", "lh": "BOE-A-1946-2453",
    "ccom": "BOE-A-1885-6627", "trlc": "BOE-A-2020-4859", "lc": "BOE-A-2020-4859", "lssi": "BOE-A-2002-13758",
    "rgr": "BOE-A-2005-14803", "rgat": "BOE-A-2007-15984", "lirnr": "BOE-A-2004-4527", "trlirnr": "BOE-A-2004-4527",
    "lrbrl": "BOE-A-1985-5392", "lcgc": "BOE-A-1998-8789", "lcs": "BOE-A-1980-22501", "lpi": "BOE-A-1996-8930",
    "trlpi": "BOE-A-1996-8930", "lgp": "BOE-A-2003-21614", "lmv": "BOE-A-2023-7053", "trlgss": "BOE-A-2015-11724",
    "tret": "BOE-A-2015-11430", "trlsc": "BOE-A-2010-10544",
}
# Nombres habituales -> sigla (para citas escritas con el nombre: 'del Código Civil', 'de la Ley General Tributaria').
NOMBRES = {
    "ley del suelo": "trlsru", "ley de suelo": "trlsru", "ley organica del regimen electoral general": "loreg",
    "codigo civil": "cc", "constitucion": "ce", "codigo penal": "cp", "ley de enjuiciamiento civil": "lec",
    "ley de enjuiciamiento criminal": "lecrim", "estatuto de los trabajadores": "et",
    "ley general de la seguridad social": "lgss", "ley reguladora de la jurisdiccion social": "lrjs",
    "ley de la jurisdiccion contencioso-administrativa": "ljca", "ley del procedimiento administrativo comun": "lpac",
    "ley de regimen juridico del sector publico": "lrjsp", "ley general tributaria": "lgt",
    "ley del impuesto sobre el valor anadido": "liva", "ley del iva": "liva",
    "ley del impuesto sobre la renta de las personas fisicas": "lirpf", "ley del irpf": "lirpf",
    "ley del impuesto sobre sociedades": "lis", "ley de arrendamientos urbanos": "lau",
    "ley de propiedad horizontal": "lph", "ley de sociedades de capital": "lsc",
    "ley reguladora de las haciendas locales": "trlrhl", "ley del impuesto sobre sucesiones y donaciones": "lisd",
    "reglamento del impuesto sobre el valor anadido": "riva", "reglamento del iva": "riva",
    "reglamento del impuesto sobre la renta de las personas fisicas": "rirpf", "reglamento del irpf": "rirpf",
    "reglamento del impuesto sobre sociedades": "ris", "ley de prevencion de riesgos laborales": "lprl",
    "ley sobre infracciones y sanciones en el orden social": "lisos", "estatuto del trabajo autonomo": "leta",
    "ley de contratos del sector publico": "lcsp", "ley general para la defensa de los consumidores y usuarios": "trlgdcu",
    "ley organica del poder judicial": "lopj", "ley hipotecaria": "lh", "codigo de comercio": "ccom",
    "ley concursal": "trlc", "reglamento general de recaudacion": "rgr", "ley general presupuestaria": "lgp",
}


_RESUELTAS: dict[tuple[str, bool], tuple[str, str | None]] = {}  # caché de la sesión: una ley no cambia de id
_POR_NUMERO = re.compile(rf"({_RANGO})\s?([0-9]{{1,4}}/[0-9]{{4}})")


def resolver_ley(ley: str, consolidadas: bool = True) -> tuple[str, str | None]:
    """'LGT', 'Ley General Tributaria', 'Ley 58/2003' o 'BOE-A-2003-23186' -> (id BOE, cómo se resolvió).
    Primero el id, luego la sigla o el nombre conocidos. Por rango y número, SOLO la norma exacta (vigente o
    derogada; nunca 'la que más se parece'). Por nombre libre, la norma principal vigente que dé el buscador.
    consolidadas=False admite normas sin texto consolidado (leyes que solo modifican otras)."""
    clave = (" ".join((ley or "").split()), consolidadas)
    if clave not in _RESUELTAS:
        _RESUELTAS[clave] = _resolver_ley(*clave)
    return _RESUELTAS[clave]


def _resolver_ley(texto_: str, consolidadas: bool) -> tuple[str, str | None]:
    if (ident := id_norma(texto_)):
        return ident, None
    clave = _sin_acentos(texto_).lower().replace(".", "").replace(" ", "") if len(texto_) <= 12 else ""
    if clave in LEYES:
        return LEYES[clave], None
    nombre = re.sub(r"^(la|el|del|de la)\s+", "", " ".join(_sin_acentos(texto_).lower().split()))
    if nombre in NOMBRES:
        return LEYES[NOMBRES[nombre]], None
    if len(texto_) < 2 or len(texto_) > 200:
        raise ValueError("Indica la ley por su sigla (LGT), su nombre (Ley General Tributaria), su número "
                         "(Ley 58/2003) o su id BOE (BOE-A-2003-23186).")
    numero = _POR_NUMERO.fullmatch(comunidad(" ".join(_sin_acentos(texto_).lower().split()))[0])
    if numero:
        exactas = [r for r in buscar_legislacion(texto_, solo_vigente=False, max_resultados=5, consolidadas=consolidadas,
                                                 comprobar_derogadas=False, ampliar=False)["resultados"] if r.get("exacta")]
        if not exactas and consolidadas:  # ¿existe, aunque sin texto consolidado? Entonces se dice cuál y su estado
            otras = [r for r in buscar_legislacion(texto_, solo_vigente=False, max_resultados=5, consolidadas=False,
                                                   comprobar_derogadas=False, ampliar=False)["resultados"] if r.get("exacta")]
            if otras:
                motivo, comprobado = estado_derogacion(otras[0]["id"])
                estado = (f"ATENCIÓN: {motivo}" if motivo else
                          "no consta derogada" if comprobado else "no se pudo comprobar si sigue vigente")
                raise ValueError(f"{texto_[:60]} ({otras[0]['id']}) no tiene texto consolidado en el BOE; {estado}. "
                                 "Para el texto publicado, leer_boe con su id.")
        if not exactas:
            raise ValueError(f"No encuentro la norma {texto_[:60]!r} {'con texto consolidado ' if consolidadas else ''}"
                             "en el BOE (puede estar derogada sin consolidar, o el número no es ese). Para el texto "
                             "publicado, leer_boe con su id.")
        return exactas[0]["id"], None
    try:
        encontradas = buscar_legislacion(texto_, max_resultados=1, comprobar_derogadas=False)["resultados"]
    except ValueError:
        encontradas = []
    if not encontradas:
        raise ValueError(f"No identifico la ley {texto_[:60]!r}. Usa su sigla (LGT, ET, CC...), su número "
                         "('Ley 58/2003') o búscala con buscar_ley.")
    return encontradas[0]["id"], encontradas[0]["titulo"].partition(")")[2].strip() or encontradas[0]["titulo"]


def indice_ley(ley: str) -> dict:
    ident = resolver_ley(ley)[0]
    try:
        datos = json_(f"{API}/legislacion-consolidada/id/{ident}/texto/indice")
    except FuenteError as e:
        if e.codigo in (400, 404):
            raise FuenteError(f"{ident} no existe o no tiene texto consolidado en el BOE (solo lo tienen las normas "
                              "consolidadas; usa leer_boe para el texto tal como se publicó).", e.codigo) from None
        raise
    bloques = []
    for grupo in _lista(datos.get("data")):
        for b in _lista(grupo.get("bloque")):
            bloques.append({"bloque": b.get("id"), "titulo": b.get("titulo"),
                            "actualizado": b.get("fecha_actualizacion")})
    if not bloques:
        raise FuenteError(f"{ident} no tiene texto consolidado en el BOE.")
    return {"id": ident, "bloques": bloques, "fuente": f"{WEB}/buscar/act.php?id={ident}"}


_UNIDADES = ("primera", "segunda", "tercera", "cuarta", "quinta", "sexta", "septima", "octava", "novena")
_DECENAS = ("", "decima", "vigesima", "trigesima", "cuadragesima", "quincuagesima", "sexagesima", "septuagesima",
            "octogesima", "nonagesima")


def _ordinal(n: int) -> str:
    """1..99 como los escribe el BOE (sin espacios): 'primera', 'undecima', 'decimoctava', 'vigesimaprimera'."""
    if n in (11, 12):
        return ("undecima", "duodecima")[n - 11]
    if 13 <= n <= 19:
        return ("decimo" + _UNIDADES[n - 11]).replace("decimoo", "decimo")
    return _DECENAS[n // 10] + (_UNIDADES[n % 10 - 1] if n % 10 else "")


_ORDINALES = tuple(_ordinal(n) for n in range(1, 100))
_CARDINALES = ("cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciseis "
               "diecisiete dieciocho diecinueve veinte veintiuno veintidos veintitres veinticuatro veinticinco "
               "veintiseis veintisiete veintiocho veintinueve").split()
_DECENAS_CARD = ("", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa")
_ORDINALES_M = ("primero", "segundo", "tercero", "cuarto", "quinto", "sexto", "septimo", "octavo", "noveno", "decimo")


_CENTENAS = ("", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos", "setecientos",
             "ochocientos", "novecientos")


def _numero_en_letra(n: int) -> set[str]:
    """Cómo puede titular el BOE el artículo n en leyes que numeran en letra (LPH, LOPJ, LCS): 'diecisiete',
    'treintayuno', 'doscientostreintayocho', 'cien', 'primero'."""
    resto = n % 100
    decenas = "" if not resto else (_CARDINALES[resto] if resto < 30 else
                                    _DECENAS_CARD[resto // 10] + (f"y{_CARDINALES[resto % 10]}" if resto % 10 else ""))
    formas = {"cien" if n == 100 else _CENTENAS[n // 100] + decenas}
    if 1 <= n <= 10:
        formas.add(_ORDINALES_M[n - 1])
    return formas
_ABREVIATURAS = {"da": "disposicion adicional", "dt": "disposicion transitoria", "df": "disposicion final",
                 "dd": "disposicion derogatoria"}


def _norm_bloque(a: str) -> str:
    """'Artículo 20 bis.' / 'art. 20bis' -> '20bis'; 'Disposición adicional 1ª' / 'DA 1ª' / '...primera.' ->
    'disposicionadicionalprimera'; 'vigésima primera' y 'vigesimoprimera' cuentan igual."""
    a = re.sub(r"^(articulo|art\.?)\s*", "", " ".join(_sin_acentos(a).lower().split()))
    a = re.sub(r"^d\.? ?([atfd])\.? ", r"d\1 ", a)  # 'D.T. 1ª', 'D. T. 1ª' -> 'dt 1ª'
    primera, _, resto = a.partition(" ")
    a = f"{_ABREVIATURAS[primera]} {resto}" if primera in _ABREVIATURAS else a
    a = re.sub(r"\b(vigesim|trigesim|cuadragesim|quincuagesim|sexagesim|septuagesim|octogesim|nonagesim)o ?", r"\1a", a)
    if a.startswith("disposicion"):  # en disposiciones, '1ª' o '1.ª' es 'primera'
        a = re.sub(r"\b([0-9]{1,2}) ?\.? ?[ºªao]?(?=\W|$)",
                   lambda m: _ORDINALES[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(_ORDINALES) else m.group(1), a)
    return re.sub(r"[\s.ºª]+", "", a)


_MESES = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                       "septiembre", "octubre", "noviembre", "diciembre"), 1)}


def _efectos_futuros(texto_: str) -> list[str]:
    """Fechas 'con efectos (desde el) D de mes de AAAA' del texto que aún no han llegado."""
    hoy, futuras = date.today(), []
    for d, m, a in re.findall(r"efectos? (?:desde )?(?:el |del? )?([0-9]{1,2}) de ([a-z]{4,10}) de ([0-9]{4})",
                              " ".join(_sin_acentos(texto_).lower().split())):
        if m in _MESES:
            try:
                f = date(int(a), _MESES[m], int(d))
            except ValueError:
                continue
            if f > hoy:
                futuras.append(f.isoformat())
    return sorted(set(futuras))


def _parte_derogada(texto_: str, parte: str) -> bool:
    """Si la letra ('d') o el apartado ('2') figura como derogado o sin contenido: 'd) (Derogada)', '2. (Suprimido)'."""
    t = _sin_acentos(texto_[:300_000]).lower()
    marca = r"[ \t]*\(?(?:derogad|suprimid|sin contenido|anulad|sin efecto)"  # [ \t], no \s: lineal (ronda 13)
    if parte.isalpha():
        return bool(re.search(rf"(?m)^[ \t]*{parte}\){marca}", t) or f"se deroga la letra {parte})" in t)
    return bool(re.search(rf"(?m)^[ \t]*{parte}\.{marca}", t) or f"se deroga el apartado {parte} " in t)


def _sin_efecto(ident: str | None) -> bool:
    """Si la norma que dio una versión está derogada (p. ej. un RDL no convalidado): su versión no va a entrar."""
    if not ident or not re.fullmatch(r"BOE-[A-Z]-[0-9]{4}-[0-9]{1,6}", ident):
        return False
    motivo, comprobado = estado_derogacion(ident)
    return bool(comprobado and motivo)


def articulo(ley: str, articulo_: str, max_caracteres: int = 30000) -> dict:
    """Texto VIGENTE de un artículo o de cualquier bloque (disposiciones, anexos...). ley: sigla, nombre, número
    o id BOE."""
    ident, resuelta = resolver_ley(ley)
    indice = indice_ley(ident)["bloques"]
    avisos = ["Texto consolidado del BOE: tiene carácter informativo, no oficial."]
    if not (articulo_ or "").strip():
        raise ValueError("Indica el artículo o la disposición ('20', '20 bis', 'DA 1ª').")
    llano = " ".join(_sin_acentos(articulo_).lower().split())
    # 'art. 7 letra p' -> '7 p)'; '56, apartado 2' -> '56.2'
    llano = re.sub(r",? ?apartado ([0-9]{1,3})", r".\1", re.sub(r"\bletra ([a-zñ])\b\)?", r"\1)", llano))
    # Qué artículo se pide, ANTES de comparar: '1.902' (tres cifras tras el punto) es el 1902, como numera el
    # Código Civil; '14.2', '49.1.k)', '52 c)' son apartados del 14, 49, 52 (el BOE consolida por artículos, así que
    # va el artículo entero). Nunca '14.2' -> 142: sería otro artículo.
    # '1.968', '1.968.2', '1.902 CC': miles del Código Civil, aunque detrás venga un apartado o la sigla.
    miles = re.match(r"(?:art[a-z]*\.? ?)?([0-9])\.([0-9]{3})(?![0-9])(.*)", llano)
    apartado = re.match(r"(?:art[a-z]*\.? ?)?([0-9]{1,4}(?: ?(?:bis|ter|quater|quinquies|sexies))?)"
                        r"(?: ?[.,] ?[0-9a-z]| ?[a-z]\))", llano)
    sin_art = re.sub(r"^art[a-z]*\.? ?", "", llano)
    parte = re.search(r"(?:^|[ .,])([a-zñ])\)\s*$", sin_art) or re.match(
        r"[0-9]{1,4}(?: ?(?:bis|ter|quater))? ?[.,] ?([0-9]{1,3})(?![0-9])", sin_art)
    if miles:
        pedido = miles.group(1) + miles.group(2)
        parte = re.search(r"(?:^|[ .,])([a-zñ])\)\s*$", miles.group(3)) or re.match(r" ?[.,] ?([0-9]{1,3})(?![0-9])",
                                                                                 miles.group(3))
        if re.match(r" ?[.,] ?[0-9a-z]| ?[a-z]\)", miles.group(3)):
            avisos.append(f"El BOE consolida por artículos: va el artículo {pedido} entero; busca en él el apartado.")
    elif apartado:
        pedido = apartado.group(1)
        avisos.append(f"El BOE consolida por artículos: va el artículo {pedido} entero; busca en él el apartado.")
    else:
        pedido = articulo_
    # Por id de bloque ('a20', 'daprimera'), por número ('20', '20 bis'), por título ('Disposición adicional primera')
    # o, en leyes antiguas que numeran en letra (LPH: 'Artículo diecisiete', 'Artículo primero'), por su nombre.
    formas = {_norm_bloque(pedido)}
    numero = re.fullmatch(r"[0-9]{1,3}", _norm_bloque(pedido))
    if numero:
        formas |= _numero_en_letra(int(numero.group(0)))
    bloque = next((b for b in indice if b["bloque"] == pedido.strip()), None) or next(
        (b for b in indice if _norm_bloque(b["titulo"] or "") in formas), None)
    if not bloque or not re.fullmatch(r"[a-z0-9-]{1,40}", bloque["bloque"] or ""):
        raise FuenteError(f"No encuentro {articulo_[:60]!r} en {ident}. Usa indice_ley para ver los bloques y sus títulos.")
    motivo, comprobado = estado_derogacion(ident)
    if motivo:
        avisos.append(f"ATENCIÓN: {motivo} Comprueba si este precepto sigue aplicándose.")
    elif not comprobado:
        avisos.append("No se pudo comprobar si la ley está derogada (el BOE no respondió a esa consulta): compruébalo.")
    xml = texto(f"{API}/legislacion-consolidada/id/{ident}/texto/bloque/{bloque['bloque']}",
                cabeceras={"Accept": "application/xml"})
    raiz = analizar_xml(xml)
    versiones = raiz.findall(".//version")
    if not versiones:
        raise FuenteError("El BOE no devolvió el texto del bloque.")
    # Vigente = la de fecha de vigencia más reciente que ya ha llegado (el BOE no las ordena por vigencia).
    hoy = date.today().strftime("%Y%m%d")
    orden = sorted(enumerate(versiones), key=lambda iv: (iv[1].get("fecha_vigencia") or "", iv[0]))
    # Una versión sin fecha de vigencia es una ya publicada que el BOE aún no ha fechado (p. ej. un RDL de 2026 que
    # rige más adelante): no cuenta como vigente y se avisa de ella.
    ya = [v for _, v in orden if v.get("fecha_vigencia") and v.get("fecha_vigencia") <= hoy]
    vigente = ya[-1] if ya else orden[-1][1]
    if not ya:  # ninguna versión ha entrado en vigor (vacatio legis, o un artículo nuevo aún sin fecha)
        avisos.append("ATENCIÓN: ninguna versión de este precepto rige todavía; las publicadas aún no rigen (entra "
                      f"{vigente.get('fecha_vigencia') or 'sin fecha en el BOE'}, {vigente.get('id_norma')}). "
                      "No lo cites como vigente.")
    # Futura = publicada después que la vigente y que aún no rige (una versión vieja sin fecha, o la de una norma que
    # se derogó antes de entrar, no 'va a entrar': LGT 150, LIVA 20 con el RDL 26/2026).
    futuras = [{"vigencia": v.get("fecha_vigencia") or "sin fecha en el BOE", "norma": v.get("id_norma")}
               for _, v in orden if v is not vigente and (not v.get("fecha_vigencia") or v.get("fecha_vigencia") > hoy)
               and (v.get("fecha_publicacion") or "") >= (vigente.get("fecha_publicacion") or "")
               and not _sin_efecto(v.get("id_norma"))]
    # Las citas (blockquote) traen sus p; las tablas (escalas del IRPF, tipos) van fila a fila, con sus celdas aunque
    # no lleven p (las autonómicas no la llevan: salían vacías).
    lineas = (" | ".join(" ".join("".join(c.itertext()).split()) for c in e if c.tag in ("td", "th"))
              if e.tag == "tr" else "".join(e.itertext()).strip() for e in parrafos(vigente, ("p", "tr")))
    texto_ = "\n".join(p for p in lineas if p)
    if futuras:
        avisos.append(f"ATENCIÓN: hay versiones publicadas que aún no rigen o sin fecha de vigencia: {futuras}. "
                      "Esta es la vigente hoy; comprueba cuándo entra la nueva (norma indicada).")
    if parte and _parte_derogada(texto_, parte.group(1)):
        avisos.append(f"ATENCIÓN: {'la letra ' + parte.group(1) + ')' if parte.group(1).isalpha() else 'el apartado ' + parte.group(1)}"
                      " de este artículo figura como derogada o sin contenido en el texto vigente.")
    if re.search(r"\((derogad|suprimid|anulad|sin contenido|sin efecto)", _sin_acentos(texto_[:400]).lower()):
        avisos.append("ATENCIÓN: este precepto figura como derogado, suprimido o sin contenido en el texto vigente.")
    if (fechas := _efectos_futuros(texto_[:300_000])):  # un artículo real no llega; un texto inflado no se normaliza
        avisos.append(f"Parte de este texto dice producir efectos en fechas que aún no han llegado ({', '.join(fechas)}): "
                      "comprueba qué apartados rigen hoy.")
    if resuelta:
        avisos.append(f"Ley identificada por búsqueda: {resuelta[:200]}. Comprueba que es la que querías.")
    return {"id": ident, "bloque": bloque["bloque"], "titulo": bloque["titulo"],
            "version_vigente_desde": vigente.get("fecha_vigencia"), "norma_de_esta_version": vigente.get("id_norma"),
            "versiones_en_total": len(versiones),
            "normas_que_lo_han_modificado": sorted({v.get("id_norma") for v in versiones if v.get("id_norma")})[:60],
            "texto": recortar(texto_, max_caracteres),
            "fuente": f"{WEB}/buscar/act.php?id={ident}#{bloque['bloque']}", "avisos": avisos}


def leer_boe(identificador: str, max_caracteres: int = 15000, desde: int = 0) -> dict:
    """Un documento del BOE (BOE-A/B, disposiciones y anuncios) o del BORME (BORME-A/B/C)."""
    ident = identificador.strip().upper()
    if not re.fullmatch(r"(BOE-[ABS]|BORME-[ABCS])-[0-9]{4}-[0-9-]{1,12}", ident):
        raise ValueError(f"Identificador no válido: {ident[:40]!r} (BOE-A-AAAA-NNNNN o BORME-A-...). Si tienes el "
                         "nombre o el número de la norma, búscala antes con buscar_ley.")
    diario = "diario_borme" if ident.startswith("BORME") else "diario_boe"
    raiz = analizar_xml(texto(f"{WEB}/{diario}/xml.php?id={ident}"))
    meta = raiz.find("metadatos")
    if meta is None:
        raise FuenteError(f"{ident} no existe en el {diario.split('_')[1].upper()}.")
    campos = {c.tag: corto((c.text or "").strip(), 2000) for c in meta if (c.text or "").strip()}
    cuerpo = raiz.find("texto")
    contenido = "\n".join("".join(p.itertext()).strip()
                          for p in parrafos(cuerpo, ("p", "td"))) if cuerpo is not None else ""
    return {"id": ident, "metadatos": campos, "caracteres_en_total": len(contenido),
            "texto": recortar(contenido, max_caracteres, desde),
            "fuente": f"{WEB}/{diario}/txt.php?id={ident}",
            "aviso": "Texto tal como se publicó, sin las modificaciones posteriores. Para el texto vigente de una "
                     "ley, articulo_vigente."}


def sumario_borme(fecha: str = "hoy") -> dict:
    s = _sumario("borme", fecha)
    # Se recorta cada campo ANTES de formatearlo y la lista se corta mientras se construye (un sumario con nombres
    # de megas y millones de items no se copia entero).
    txt = lambda x, n: corto(x if isinstance(x, str) else "", n)  # noqa: E731
    secciones = []
    for diario in _lista(s.get("diario"))[:5]:
        for sec in _lista(diario.get("seccion"))[:10]:
            items = [{"id": txt(i.get("identificador"), 40), "titulo": txt(i.get("titulo"), 200)}
                     for i in _lista(sec.get("item"))[:300] if isinstance(i, dict)]
            for apartado in _lista(sec.get("apartado"))[:50]:
                nombre = txt(apartado.get("nombre"), 100) if isinstance(apartado, dict) else ""
                items += [{"id": txt(i.get("identificador"), 40), "titulo": f"{nombre}: {txt(i.get('titulo'), 200)}"}
                          for i in _lista(apartado.get("item") if isinstance(apartado, dict) else None)[:300 - len(items)]
                          if isinstance(i, dict)]
            secciones.append({"seccion": txt(sec.get("nombre"), 200), "items": items[:300]})
    f = fecha_aaaammdd(fecha)
    return {"fecha": f, "secciones": secciones, "fuente": f"{WEB}/borme/dias/{f[:4]}/{f[4:6]}/{f[6:]}/",
            "uso": "Sección A = actos inscritos por provincia. Para ver las empresas, borme_actos."}


# Nombre de uso en castellano -> como titula el BORME la provincia.
_PROVINCIAS = {"lerida": "lleida", "la coruna": "a coruna", "coruna": "a coruna", "orense": "ourense",
               "baleares": "illes balears", "islas baleares": "illes balears", "gerona": "girona",
               "mallorca": "illes balears", "palma": "illes balears", "palma de mallorca": "illes balears",
               "las palmas de gran canaria": "las palmas", "gran canaria": "las palmas", "tenerife": "santa cruz",
               "guipuzcoa": "gipuzkoa", "vizcaya": "bizkaia", "alava": "araba"}
_FORMAS = {"sl", "sa", "slu", "sau", "slp", "sll", "slne", "scoop", "sc", "srl", "sociedad", "limitada", "anonima",
           "unipersonal", "profesional", "cooperativa"}


def _nombre_sociedad(s: str) -> str:
    """'Ivory Opco 6, S.L.' -> 'ivory opco 6': sin tildes, puntuación ni forma jurídica final."""
    palabras = re.sub(r"[^a-z0-9]+", " ", _sin_acentos(s).lower().replace(".", "")).split()
    while palabras and palabras[-1] in _FORMAS:
        palabras.pop()
    return " ".join(palabras)


def borme_actos(fecha: str = "hoy", provincia: str | None = None, empresa: str | None = None,
                max_resultados: int = 50) -> dict:
    """Actos inscritos (Sección A) de un día en una provincia, filtrando si se quiere por nombre de empresa."""
    if not (provincia or "").strip():
        raise ValueError("Indica la provincia del Registro Mercantil (la del domicilio social): el BORME publica "
                         "cada día un boletín por provincia y leerlos todos sería una descarga masiva.")
    fecha_aaaammdd(fecha)  # fecha inválida: error antes de descargar nada
    sesion = Sesion()
    sec_a = next((x for x in sumario_borme(fecha)["secciones"] if x["seccion"].startswith("SECCIÓN PRIMERA")), None)
    if not sec_a:
        raise FuenteError("Ese día el BORME no trae Sección A.")
    sec_a = {**sec_a, "items": [i for i in sec_a["items"] if not _sin_acentos(i["titulo"] or "").upper().startswith("INDICE")]}
    if empresa and not _nombre_sociedad(empresa):
        raise ValueError("Indica el nombre de la sociedad, no solo su forma jurídica.")
    provincia = " ".join(_sin_acentos(provincia).lower().split())
    # Primero el nombre exacto del boletín; si no, el alias ('Palma' es Illes Balears, no LAS PALMAS, aunque
    # 'palma' esté dentro); y solo después, contenido en el título.
    if provincia in _PROVINCIAS and not any(_sin_acentos(i["titulo"]).lower() == provincia for i in sec_a["items"]):
        provincia = _PROVINCIAS[provincia]
    provincias = [i for i in sec_a["items"] if _contiene(i["titulo"], provincia)]
    exactas = [i for i in provincias if _contiene(provincia, i["titulo"])]  # 'Madrid' no es ambigua aunque haya otras
    provincias = exactas or provincias
    if not provincias:
        raise FuenteError(f"Ese día no hay boletín de {provincia[:40]!r} en el BORME (no hubo actos o se escribe de "
                          f"otra forma). Provincias con actos ese día: {', '.join(i['titulo'][:40] for i in sec_a['items'][:60])}")
    if len({i["titulo"] for i in provincias}) > 1:
        raise ValueError(f"Provincia ambigua: {', '.join(i['titulo'] for i in provincias)}. Escríbela entera.")
    actos, busca = [], _nombre_sociedad(empresa or "")
    for prov in provincias[:2]:
        if not re.fullmatch(r"BORME-A-[0-9]{4}-[0-9]{1,4}-[0-9]{1,3}", str(prov["id"])):
            raise FuenteError("El sumario del BORME trae un identificador de boletín inesperado; no se sigue.")
        raiz = analizar_xml(sesion.texto(f"{WEB}/diario_borme/xml.php?id={prov['id']}"))
        ps = [(p.get("class"), "".join(p.itertext()).strip()) for p in parrafos(raiz, ("p",))]
        for (clase, cab), (_, detalle) in zip(ps, ps[1:]):
            nombre = _nombre_sociedad(cab[:300])
            if clase == "articulo" and busca in nombre:
                actos.append({"provincia": prov["titulo"], "empresa": corto(cab, 300),
                              **({"coincidencia": "parcial: el nombre contiene lo buscado, no es igual"}
                                 if empresa and busca != re.sub(r"^[0-9]+ ", "", nombre) else {}),
                              "actos": corto(detalle),
                              "boletin": prov["id"],
                              "fuente": f"{WEB}/diario_borme/txt.php?id={prov['id']}"})
    f = fecha_aaaammdd(fecha)
    return {"fecha": f, "total": len(actos), "actos": actos[:tope(max_resultados, 100)],
            "fuente": f"{WEB}/borme/dias/{f[:4]}/{f[4:6]}/{f[6:]}/",
            "aviso": "El BORME no publica el CIF en los actos; identifica la sociedad por nombre y datos registrales."
                     + (" 0 actos: esa sociedad no tuvo actos publicados ese día en esa provincia (prueba otro día o "
                        "parte del nombre)." if empresa and not actos else "")}


# Buscadores web del BOE de anuncios (sección V, desde 1960), del Tablón Edictal Único (notificaciones, 3 meses) y
# del Tablón Edictal Judicial (4 meses): (página, índice del campo de texto, índice del campo de fecha).
_ANUNCIOS = {"anuncios": ("anboe", 2, 7), "notificaciones": ("notificaciones", 0, 4),
             "edictos": ("edictos_judiciales", 0, 4)}
# Regla 3 del conector: DNI (8 cifras y letra), NIE (X/Y/Z) y NIF de personas físicas (K, L, M), nunca.
_ID_PERSONA = re.compile(r"(?<![0-9A-Z])(?:[0-9]{8}[A-Z]?|[XYZKLM][0-9]{7}[A-Z]|[0-9]{7}[A-Z])(?![0-9A-Z])")
_NIF_EMPRESA = re.compile(r"[ABCDEFGHJNPQRSUVW][0-9]{7}[0-9A-J]")


def buscar_anuncios_boe(texto_: str, desde: str | None = None, hasta: str | None = None,
                        donde: str = "anuncios") -> dict:
    """Anuncios del BOE que nombran a una empresa (por su NIF o su nombre): licitaciones, subastas, notificaciones
    de Hacienda y la Seguridad Social, edictos de concurso. Solo empresas: un DNI o NIE se rechaza."""
    donde = _sin_acentos(donde.strip().lower())
    if donde not in _ANUNCIOS:
        raise ValueError(f"donde: {', '.join(_ANUNCIOS)}.")
    # Se mira EXACTAMENTE lo que se enviaría (ya limpio y cortado), con toda cifra Unicode pasada a 0-9 ('١٢٣', '𝟏𝟐',
    # '１２'). Si no es un NIF de empresa entero, 6 cifras o más en total (separadas como sea: '12 / 345 / 678 Z'), un
    # DNI enmascarado ('***4567**') o un número en letra con millones se rechazan: un nombre de empresa no lleva eso
    # (y si lo lleva, se busca por su NIF).
    normal = "".join(str(unicodedata.decimal(c)) if unicodedata.decimal(c, None) is not None else c
                     for c in unicodedata.normalize("NFKC", texto_[:2000]))
    limpio = " ".join(re.sub(r"[\"'«»“”()<>*?%&;=+]", " ", normal).split())[:150]
    compacto = re.sub(r"[^0-9A-Z]+", "", limpio.upper())
    nif = compacto if _NIF_EMPRESA.fullmatch(compacto) else ""
    if not nif and (sum(c.isdigit() for c in limpio) >= 6 or re.search(r"\*{2,}\s*[0-9]{2,}|[0-9]{2,}\s*\*{2,}", normal)
                    or "millon" in _sin_acentos(limpio.lower()) or _ID_PERSONA.search(compacto)):
        raise ValueError("Eso parece un DNI, NIE o NIF de persona física: el conector no busca personas (regla 3). "
                         "Solo el NIF de una empresa (empieza por letra: B12345678) o su nombre.")
    if not nif and len(limpio) < 3:
        raise ValueError("Indica el NIF de la empresa (B12345678) o su nombre (3 letras o más).")
    # En los tablones de notificaciones y edictos casi todo son personas: sin NIF, el nombre lleva su forma social.
    if not nif and donde != "anuncios" and not (set(_sin_acentos(limpio.lower()).replace(".", "").split()) & _FORMAS):
        raise ValueError(f"En '{donde}' busca por el NIF de la empresa o por su nombre con la forma social ('Ejemplo SL'): "
                         "el conector no busca personas (regla 3).")
    # El NIF se escribe con guion o sin él ('A-28017895'): las dos formas. El nombre, como frase exacta.
    consulta = f'{nif} or "{nif[0]}-{nif[1:]}"' if nif else (f'"{limpio}"' if " " in limpio else limpio)
    pagina_, i_texto, i_fecha = _ANUNCIOS[donde]
    fechas = [fecha_aaaammdd(v) if v else "" for v in (desde, hasta)]
    fechas = [f"{f[:4]}-{f[4:6]}-{f[6:]}" if f else "" for f in fechas]  # como lo manda el formulario
    if all(fechas) and fechas[0] > fechas[1]:
        raise ValueError("'desde' es posterior a 'hasta'.")
    url = f"{WEB}/buscar/{pagina_}.php"
    pagina = Sesion().texto(url, [
        (f"campo[{i_texto}]", "DOC"), (f"dato[{i_texto}]", consulta), (f"operador[{i_texto}]", "and"),
        (f"operador[{i_fecha}]", "and"), (f"campo[{i_fecha}]", "FPU"), (f"dato[{i_fecha}][0]", fechas[0]),
        (f"dato[{i_fecha}][1]", fechas[1]), ("page_hits", "50"), ("sort_field[0]", "FPU"), ("sort_order[0]", "desc"),
        ("accion", "Buscar")])
    ventana = {"notificaciones": "los últimos 3 meses", "edictos": "los últimos 4 meses"}.get(donde, "desde 1960")
    if "son incorrectos" in pagina:
        raise ValueError(f"El buscador del BOE rechaza esas fechas: en '{donde}' solo hay {ventana}.")
    base = {"consulta": consulta, "donde": donde, "periodo_disponible": ventana, "fuente": url}
    if "No se han encontrado documentos" in pagina:
        return {**base, "total": 0, "anuncios": [],
                "aviso": "No consta en el BOE con eso" + (" (búscalo también por el nombre)." if nif else
                         " (el nombre se busca como frase exacta: prueba sin la forma social o con el NIF).")}
    if 'class="listadoResult' not in pagina:
        raise FuenteError("El buscador del BOE no devolvió la página de resultados; reintenta.")
    anuncios = []
    for li in bloques(pagina, '<li class="resultado-busqueda">', 5000)[:50]:
        ident = campo(r"(BOE-[BNJ]-[0-9]{4}-[0-9]{1,7})", li)
        if not ident:
            continue
        pdf = campo(r'href="(/boe_n/dias/[0-9]{4}/[0-9]{2}/[0-9]{2}/not\.php\?id=BOE-N-[0-9]{4}-[0-9]{1,7})"', li)
        anuncios.append({"id": ident, "boletin": corto(plano(entre(li, '<p class="linea-dem">', "</p>")), 200),
                         "emisor": corto(plano(entre(li, '<p class="linea-pub">', "</p>")), 300) or None,
                         "titulo": corto(plano(entre(li, "<p>", "</p>")), 800),
                         "fuente": (f"{WEB}{pdf}" if pdf else None) if ident.startswith("BOE-N") else
                         f"{WEB}/buscar/doc.php?id={ident}" if ident.startswith("BOE-B") else
                         f"{WEB}/diario_boe/txt.php?id={ident}"})
    total = int(campo(r"Resultados [0-9]{1,6} a [0-9]{1,6} de ([0-9.]{1,9})", pagina).replace(".", "") or len(anuncios))
    return {**base, "total": total, "anuncios": anuncios, "orden": "Los más recientes primero (hasta 50).",
            "uso": "Texto de un anuncio BOE-B: leer_boe con su id. Las notificaciones (BOE-N) son PDF: enlace en 'fuente'.",
            "aviso": "Un anuncio que nombra a la empresa no dice que sea la parte afectada: léelo antes de concluir."}
