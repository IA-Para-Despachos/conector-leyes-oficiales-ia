# Fuentes oficiales (versión abierta) 0.3.1. Hecho por Jurium. Licencia MIT (LICENSE).
"""Convenios colectivos: REGCON (registro oficial del Ministerio de Trabajo) para localizarlos y saber su estado, y
su texto en el boletín donde se publicó (BOE, autonómico o BOP), leído en PDF o HTML.

La ficha de cada trámite en REGCON muestra también los datos de quien lo tramitó (nombre, correo, teléfono): de
ella solo se sacan el estado del convenio y el enlace al boletín; lo demás no sale nunca de aquí."""
from __future__ import annotations

import bisect
import datetime
import re
import time
import urllib.parse
from pathlib import Path

from boe import _sin_acentos, pasajes
import cache_textos
import rutas
from pdf import PdfError, texto_pdf_aislado
from red import BOLETINES, DOMINIOS, FuenteError, Sesion, comprobar_url, plano, queda_herramienta, recortar, tope

REGCON = "https://expinterweb.mites.gob.es/regcon/pub"
_CONSULTA = f"{REGCON}/consultaPublica"
_TEXTOS = f"{REGCON}/buscadorTextosEstatal"
# Convenios que el usuario guarda él mismo (PDF del boletín) para analizar_texto_convenio: fuera de git.
CARPETA = rutas.ruta("convenios")
MAX_PDF = 25_000_000
MAX_TEXTO = 400_000  # caracteres de texto pegado (un convenio largo ronda los 150.000-300.000)

# Autoridad laboral (id del formulario de REGCON) por nombre, sin tildes y en minúsculas.
_AUTORIDADES = {
    "alava": 1, "albacete": 2, "alicante": 3, "almeria": 4, "avila": 5, "badajoz": 6, "illes balears": 7,
    "barcelona": 8, "burgos": 9, "caceres": 10, "cadiz": 11, "castellon": 12, "ciudad real": 13, "cordoba": 14,
    "a coruna": 15, "cuenca": 16, "girona": 17, "granada": 18, "guadalajara": 19, "gipuzkoa": 20, "huelva": 21,
    "huesca": 22, "jaen": 23, "leon": 24, "lleida": 25, "la rioja": 26, "lugo": 27, "madrid": 28, "malaga": 29,
    "murcia": 30, "navarra": 31, "ourense": 32, "asturias": 33, "palencia": 34, "las palmas": 35, "pontevedra": 36,
    "salamanca": 37, "santa cruz de tenerife": 38, "cantabria": 39, "segovia": 40, "sevilla": 41, "soria": 42,
    "tarragona": 43, "teruel": 44, "toledo": 45, "valencia": 46, "valladolid": 47, "bizkaia": 48, "zamora": 49,
    "zaragoza": 50, "ceuta": 51, "melilla": 52, "andalucia": 53, "aragon": 54, "canarias": 55, "castilla y leon": 56,
    "castilla-la mancha": 57, "cataluna": 58, "comunitat valenciana": 59, "extremadura": 60, "galicia": 61,
    "pais vasco": 62, "estatal": 63, "terres de l'ebre": 65,
}
_ALIAS = {
    "araba": "alava", "vitoria": "alava", "alacant": "alicante", "elche": "alicante", "baleares": "illes balears",
    "islas baleares": "illes balears", "mallorca": "illes balears", "palma de mallorca": "illes balears",
    "castello": "castellon", "la coruna": "a coruna", "coruna": "a coruna", "santiago de compostela": "a coruna",
    "gerona": "girona", "guipuzcoa": "gipuzkoa", "san sebastian": "gipuzkoa", "donostia": "gipuzkoa",
    "lerida": "lleida", "rioja": "la rioja", "logrono": "la rioja", "region de murcia": "murcia",
    "cartagena": "murcia", "pamplona": "navarra", "orense": "ourense", "principado de asturias": "asturias",
    "oviedo": "asturias", "gijon": "asturias", "gran canaria": "las palmas", "tenerife": "santa cruz de tenerife",
    "santander": "cantabria", "vigo": "pontevedra", "vizcaya": "bizkaia", "bilbao": "bizkaia",
    "comunidad de madrid": "madrid", "jerez": "cadiz", "marbella": "malaga", "comunidad valenciana": "comunitat valenciana",
    "comunitat": "comunitat valenciana", "catalunya": "cataluna", "euskadi": "pais vasco", "castilla la mancha":
    "castilla-la mancha", "nacional": "estatal", "espana": "estatal", "todo el estado": "estatal",
    "tierras del ebro": "terres de l'ebre", "palma": "illes balears", "ibiza": "illes balears",
    "eivissa": "illes balears", "menorca": "illes balears", "santiago": "a coruna", "lanzarote": "las palmas",
    "fuerteventura": "las palmas", "las palmas de gran canaria": "las palmas", "la palma": "santa cruz de tenerife",
    "la gomera": "santa cruz de tenerife", "el hierro": "santa cruz de tenerife", "alcala de henares": "madrid",
    "san sebastian de los reyes": "madrid", "vitoria-gasteiz": "alava", "gasteiz": "alava",
    "comunidad foral de navarra": "navarra", "islas canarias": "canarias", "galiza": "galicia",
    "comunidad autonoma de euskadi": "pais vasco",
}
# Palabras de nombres de territorio y de relleno de las denominaciones: no cuentan para el parecido del nombre.
_PALABRAS_TERRITORIO = {w for n in [*_AUTORIDADES, *_ALIAS] for w in re.findall(r"[a-z]+", n)} | {
    "conveni", "col", "lectiu", "provincial", "provincia", "principado", "comunidad", "comunitat", "regional",
    "autonomica", "autonomic", "interprovincial", "estatal", "convenio", "colectivo", "sector", "acuerdo",
    "laboral", "ambito", "trabajo", "treball", "general", "traballo", "colectivo"}
# Comunidad autónoma de cada provincia (las uniprovinciales tienen una sola autoridad).
_CCAA = {53: (4, 11, 14, 18, 21, 23, 29, 41), 54: (22, 44, 50), 55: (35, 38), 56: (5, 9, 24, 34, 37, 40, 42, 47, 49),
         57: (2, 13, 16, 19, 45), 58: (8, 17, 25, 43, 65), 59: (3, 12, 46), 60: (6, 10), 61: (15, 27, 32, 36),
         62: (1, 20, 48)}
_CCAA_DE = {p: c for c, ps in _CCAA.items() for p in ps}
_AMBITOS = {"sector": ("5", "6"), "empresa": ("2", "3", "4"), "todos": ()}
_VACIAS = {"convenio", "convenios", "colectivo", "colectivos", "de", "del", "la", "las", "el", "los", "y", "e", "en",
           "para", "sector", "provincia", "provincial", "comunidad", "autonoma", "autonomico", "a", "al", "que",
           "cual", "es", "aplica", "aplicable", "se", "le", "trabajadores", "empresas", "actividad", "actividades"}
_ESTADOS = {"1": "no denunciado", "2": "denunciado"}
_PALABRAS_ESTADO = {"PUBLICADO", "REGISTRADO", "DEPOSITADO", "INSCRITO", "TRAMITADO", "NO", "DENUNCIADO", "TEXTO",
                    "DEROGADO", "POR", "OTRO", "POSTERIOR", "ANULADO", "RESOLUCIÓN", "JUDICIAL", "PLAN", "DE",
                    "IGUALDAD", "VIGENTE", "FINALIZADO"}


def _sin(texto_: str) -> str:
    return " ".join(_sin_acentos(texto_ or "").lower().split())


def _id_autoridad(nombre: str) -> int:
    """Id de la autoridad tal como la escribe REGCON en sus resultados ('Vizcaya', 'Balears (Illes)',
    'Alicante/Alacant'); 0 si no se reconoce."""
    n = _sin(nombre).partition("/")[0].strip()
    n = re.sub(r"^(.*) \((.*)\)$", r"\2 \1", n)
    return _AUTORIDADES.get(_ALIAS.get(n, n), 0)


def _territorio(texto_: str) -> tuple[list[int], str]:
    """Autoridades laborales a consultar para un territorio, y el nombre que se ha entendido. Una provincia suma su
    comunidad y el estatal (si no tiene convenio propio, se aplica el de ámbito superior); una comunidad, sus
    provincias."""
    nombre = _sin(texto_)
    nombre = _ALIAS.get(nombre, nombre)
    if nombre not in _AUTORIDADES and "/" in nombre:  # 'Araba/Álava', 'Alicante/Alacant'
        nombre = next((x for x in (_ALIAS.get(t.strip(), t.strip()) for t in nombre.split("/")) if x in _AUTORIDADES),
                      nombre)
    if nombre not in _AUTORIDADES:
        raise ValueError(f"No reconozco el territorio {texto_[:60]!r}: usa una provincia ('Bizkaia', 'Alicante'), una "
                         "comunidad ('Andalucía', 'Comunitat Valenciana') o 'estatal'.")
    ident = _AUTORIDADES[nombre]
    if ident == 63:
        return [63], "estatal"
    if ident in _CCAA:
        return [ident, *_CCAA[ident], 63], nombre
    return [ident, *([_CCAA_DE[ident]] if ident in _CCAA_DE else []), 63], nombre


def _territorio_en(consulta: str) -> tuple[str, str]:
    """Si la pregunta nombra un territorio ('limpieza de la Comunidad de Madrid'), lo separa: (sector, territorio)."""
    llano = _sin(consulta)
    for nombre in sorted([*_AUTORIDADES, *_ALIAS], key=len, reverse=True):
        m = re.search(rf"(?<![a-z]){re.escape(nombre)}(?![a-z])(?! del )", llano)  # 'Palma del Río' no es Palma
        if m:
            return (llano[:m.start()] + llano[m.end():]).strip(), nombre
    return llano, ""


# Palabras de sector frecuentes en catalán y gallego: REGCON guarda el nombre en la lengua en que se registró
# ('Neteja d'edificis i locals'). En el País Vasco y Navarra se registran en castellano.
_LENGUAS = {
    "ca": {"limpieza": "neteja", "edificios": "edificis", "locales": "locals", "hosteleria": "hostaleria",
           "comercio": "comerç", "metal": "metall", "construccion": "construccio", "oficinas": "oficines",
           "despachos": "despatxos", "transporte": "transport", "transportes": "transports", "mercancias": "mercaderies",
           "sanidad": "sanitat", "alimentacion": "alimentacio", "industrias": "industries", "servicios": "serveis",
           "seguridad": "seguretat", "residencias": "residencies", "ensenanza": "ensenyament", "panaderia": "fleca",
           "peluqueria": "perruqueria", "carpinteria": "fusteria", "madera": "fusta", "textil": "textil"},
    "gl": {"limpieza": "limpeza", "locales": "locais", "hosteleria": "hostalaria", "construccion": "construcion",
           "mercancias": "mercadorias", "sanidad": "sanidade", "servicios": "servizos", "panaderia": "panadaria",
           "ensenanza": "ensino", "madera": "madeira", "peluqueria": "perruqueria"},
}
_LENGUA_DE = {**{a: "ca" for a in (7, 8, 17, 25, 43, 65, 58, 3, 12, 46, 59)}, **{a: "gl" for a in (15, 27, 32, 36, 61)}}


def _variantes(palabras: list[str], autoridades: list[int]) -> list[list[str]]:
    """El nombre buscado en castellano y en la lengua cooficial del territorio (en toda España, en las dos)."""
    lenguas = {_LENGUA_DE[a] for a in autoridades if a in _LENGUA_DE} if autoridades else set(_LENGUAS)
    variantes = [palabras]
    castellano = [_INVERSA.get(p, p) for p in palabras]
    if castellano != palabras:
        variantes.append(castellano)
    for lengua in sorted(lenguas):
        otra, traducidas = [], 0
        for p in palabras:
            t = _traducir(_LENGUAS[lengua], p)
            traducidas += t != p
            if t != p or not autoridades:
                otra.append(t)
        if traducidas and otra != palabras:
            variantes.append(otra)
    return variantes


_INVERSA = {_sin(v).rstrip("s"): k.rstrip("s") for t in _LENGUAS.values() for k, v in t.items()}


def _traducir(tabla: dict, palabra: str) -> str:
    """La palabra en la otra lengua; en plural, su raíz ('peluquerias' -> 'perruqueri', que REGCON casa por prefijo
    con 'PERRUQUERIES')."""
    clave = next((k for k in (palabra, palabra + "s", palabra + "es") if k in tabla), None)
    if clave:
        t = tabla[clave]
        return t[:-1] if t[-1] in "aeo" and len(t) > 6 else t  # raíz: 'perruqueri' casa con 'PERRUQUERIES'
    for fin in ("es", "s"):
        if palabra.endswith(fin) and palabra[:-len(fin)] in tabla:
            t = tabla[palabra[:-len(fin)]]
            return t[:-1] if t[-1] in "aeo" and len(t) > 5 else t
    return palabra


# Sectores afines: si con las palabras del usuario salen pocos convenios ('bares', 'gestorías', 'camioneros'), se buscan
# también los del sector vecino, marcados y siempre detrás. (nombre, palabras que lo activan, palabras a buscar en OR;
# REGCON casa por el principio de la palabra: 'sanitari' encuentra 'SANITARIOS'; nada corto como 'bar', que casaría
# con 'BARCELONA'.)
_AFINES = (
    ("hostelería, restauración, bares, cafeterías y alojamiento",
     {"hosteleria", "hostaleria", "hostalaria", "restauracion", "restaurante", "bar", "bare", "cafeteria", "cafe",
      "hotel", "hotele", "hostal", "hostale", "alojamiento", "hospedaje", "camarero"},
     ["hosteleria", "restauracion", "cafeteria", "hotel", "hospedaje", "alojamiento"]),
    ("oficinas y despachos, gestorías y asesorías",
     {"oficina", "despacho", "gestoria", "asesoria", "asesor", "abogado", "procurador", "consultoria", "administrativo"},
     ["oficina", "despacho", "gestoria", "asesor", "consultoria"]),
    ("comercio", {"comercio", "tienda", "comerciante", "dependiente", "supermercado", "hipermercado", "autoservicio",
                  "minorista", "mayorista"}, ["comercio", "supermercado", "autoservicio", "minorista"]),
    ("limpieza", {"limpieza", "limpiador", "limpiadora", "limpiadore"}, ["limpieza"]),
    ("transporte y logística", {"transporte", "transportista", "camion", "camionero", "mercancia", "logistica",
                                "mensajeria", "paqueteria", "conductor"},
     ["mercancia", "transporte", "logistica", "mensajeria"]),
    ("metal", {"metal", "siderometalurgia", "siderometalurgica", "metalurgia", "metalurgica", "taller", "mecanico",
               "fontaneria"}, ["metal", "siderometal"]),
    ("construcción", {"construccion", "obra", "albanil", "albanile", "reforma", "edificacion", "constructora"},
     ["construccion", "obra"]),
    ("sanidad", {"sanidad", "sanitario", "sanitaria", "clinica", "hospital", "hospitale", "dental", "enfermeria",
                 "medico", "fisioterapia"}, ["sanidad", "sanitari", "hospital", "clinica"]),
    ("enseñanza", {"ensenanza", "educacion", "colegio", "academia", "escuela", "docente", "profesor", "profesore",
                   "guarderia"}, ["ensenanza", "educacion", "educativ", "escuela", "academia"]),
    ("dependencia y residencias", {"residencia", "geriatrico", "dependencia", "cuidador", "cuidadora", "asistencial"},
     ["dependencia", "residencia", "geriatric", "asistencial"]),
    ("seguridad privada", {"vigilante", "vigilancia", "escolta", "seguridad"}, ["seguridad", "vigilancia"]),
    ("peluquería y estética", {"peluqueria", "estetica", "barberia", "belleza"}, ["peluqueria", "estetica", "belleza"]),
)


def _afines(palabras: list[str]) -> list[tuple[str, list[str]]]:
    """(etiqueta, palabras a buscar) de los sectores afines a lo buscado, sin las que ya se buscaron (dos como mucho)."""
    propias = set(palabras) | {_INVERSA.get(p, p) for p in palabras}
    salida = []
    for nombre, activan, buscar in _AFINES:
        otras = [w for w in buscar if w not in propias]
        if propias & activan and otras:
            salida.append((f"afín (sinónimo de {nombre})", otras))
    return salida[:2]


def _palabras(sector: str) -> list[str]:
    """Palabras del nombre, en singular: REGCON casa por el principio de la palabra ('ambulancia' encuentra
    'AMBULANCIAS'; 'ambulancias' no encuentra 'AMBULANCIA')."""
    return [_singular(p) for p in re.findall(r"[a-z0-9ñç·]+", _sin(sector)) if p not in _VACIAS and len(p) > 1][:8]


def _singular(p: str) -> str:
    return p[:-1] if len(p) > 4 and p.endswith("s") and not p.endswith("ss") else p


def _consulta(s: Sesion, campos: list, pagina: int = 1) -> str:
    """Una búsqueda en la consulta pública de REGCON (formulario con sesión) y la página pedida de resultados."""
    base = [("tipoBusquedaDenominacion", "AND"), ("_idTipoTramiteConsPublica", "1"), ("_idEstadoVigencia", "1"),
            ("_idNaturalezaConsPublica", "1"), ("_idAmbFuncionalConsPublica", "1"), ("_autoridadLaboral", "1"),
            ("_idsOrgSindicales", "1"), ("_buscar", ""), ("_esNuevaBusqueda", "1"), ("consulta_token_value_id", "")]
    propios = {k for k, _ in campos}  # lo que se pasa manda sobre lo de por defecto (el servidor toma el primero)
    pagina_ = s.texto(_CONSULTA, datos=[c for c in base if c[0] not in propios] + campos, timeout=40)
    if pagina > 1:
        pagina_ = s.texto(_CONSULTA, {"pagina": pagina}, timeout=40)
    if "Consulta de Tr" not in pagina_:  # 'Consulta de Trámites' encabeza la página, con resultados o sin ellos
        raise FuenteError("REGCON ha cambiado o no respondió como se esperaba; avisa para revisarlo.")
    return pagina_


def _total(pagina: str) -> int:
    m = re.search(r"Resultados\s{0,20}\d{1,6}\s{0,20}-\s{0,20}\d{1,6}&nbsp;de&nbsp;(\d{1,7})", pagina)
    return int(m.group(1)) if m else 0


def _celdas(tr: str, n: int) -> list[str]:
    """Texto de las n primeras celdas de una fila de tabla."""
    return [" ".join(plano(c.partition(">")[2].partition("</td>")[0][:3000]).split()) for c in tr.split("<td")[1:n + 1]]


def _filas(pagina: str) -> list[dict]:
    """Filas de la tabla de trámites: código, nombre, trámite, autoridad, fechas y el botón de su ficha."""
    cuerpo = pagina.partition("<tbody>")[2].partition("</tbody>")[0]
    filas = []
    for tr in cuerpo.split("<tr>")[1:101]:
        celdas = _celdas(tr, 8)
        boton = re.search(r'name="(_ver(?:Expediente|Apunte)[0-9]{1,9})"', tr)
        if len(celdas) >= 7 and re.fullmatch(r"[0-9]{14}", celdas[0]):
            filas.append({"codigo": celdas[0], "denominacion": celdas[1][:300], "tramite": celdas[2][:120],
                          "autoridad": celdas[3][:80], "fecha": celdas[4][:10], "vigencia_desde": celdas[5][:10],
                          "vigencia_hasta": celdas[6][:10], "_boton": boton.group(1) if boton else ""})
    return filas


def _fecha(ddmmaaaa: str) -> datetime.date | None:
    try:
        return datetime.datetime.strptime(ddmmaaaa, "%d/%m/%Y").date()
    except ValueError:
        return None


def buscar_convenio(consulta: str, territorio: str = "", ambito: str = "sector", en_texto: str = "",
                    max_resultados: int = 10) -> dict:
    ambito = (ambito or "sector").strip().lower()
    if ambito not in _AMBITOS:
        raise ValueError("ambito: sector, empresa o todos.")
    if not (consulta or "").strip() and not (en_texto or "").strip():
        raise ValueError("Indica el sector ('hostelería', 'oficinas y despachos', 'metal'...) o en_texto.")
    sector, detectado = _territorio_en(consulta or "")
    if territorio.strip() or detectado:
        autoridades, entendido = _territorio(territorio.strip() or detectado)
    else:
        autoridades, entendido = [], ""
    palabras = _palabras(sector)
    if en_texto.strip():
        originales = [w for w in re.findall(r"[^\W_]+", (consulta or "").lower()) if _sin(w) in palabras]
        return _buscar_en_textos(en_texto, palabras, list(dict.fromkeys(originales)), autoridades, entendido, ambito,
                                 tope(max_resultados, 25))
    if not palabras:
        raise ValueError("Indica el sector con alguna palabra de su nombre ('hostelería', 'limpieza', 'metal').")
    s = Sesion()
    # Trámites 1 y 2: el texto de un convenio se inscribe como 'nuevo acuerdo' la primera vez y como 'texto nuevo'
    # en cada renovación. Naturaleza 1, convenio; 6, extensión de convenio (la norma aplicable donde no hay convenio
    # propio: oficinas y despachos de Sevilla, por ejemplo).
    filtros = [("idNaturalezaConsPublica", "1"), ("idNaturalezaConsPublica", "6"), ("idTipoTramiteConsPublica", "1"),
               ("idTipoTramiteConsPublica", "2"),
               *[("idAmbFuncionalConsPublica", a) for a in _AMBITOS[ambito]],
               *[("autoridadLaboral", str(a)) for a in autoridades]]
    maximo = tope(max_resultados, 25)
    vistos: dict[str, dict] = {}
    incompleta: list[int] = []  # consultas con más filas de las 30 que se leen

    def consultar(denominacion: str, modo: str, parcial: bool, textos: bool = True, afin: str = "") -> None:
        # Una consulta por estado (así se sabe cuáles están denunciados) y otra para las extensiones de convenio, a las
        # que REGCON no da estado. REGCON filtra el estado por TRÁMITE: el texto de 2012 sale como 'no denunciado' y
        # el de 2023 del mismo convenio como 'denunciado'. Por eso de cada código manda la fila más reciente.
        # textos=False: sin filtro de trámite, para los convenios cuyo texto se registró antes de REGCON.
        for estado in ((*_ESTADOS, None) if textos else tuple(_ESTADOS)):
            campos = [("denominacion", denominacion), ("tipoBusquedaDenominacion", modo),
                      *([("idEstadoVigencia", estado)] if estado else []),
                      *[f for f in filtros if f != ("idNaturalezaConsPublica", "1" if estado is None else "6")
                        and (textos or f[0] != "idTipoTramiteConsPublica")]]
            pagina = _consulta(s, campos)
            filas = _filas(pagina)
            if _total(pagina) > 15:
                filas += _filas(_consulta(s, campos, 2))
            if _total(pagina) > 30 and not afin:  # los afines solo rellenan: no hacen la lista incompleta
                incompleta.append(_total(pagina))
            for f in filas:
                previo = vistos.get(f["codigo"])
                if previo and (not textos or (afin and not previo.get("afin"))):
                    continue  # ya salió con su texto, o por lo que buscó el usuario
                if previo and (_fecha(f["fecha"]) or datetime.date.min) <= (_fecha(previo["fecha"]) or datetime.date.min):
                    continue
                vistos[f["codigo"]] = {**f, "estado": _ESTADOS.get(estado, "sin estado en REGCON"),
                                       "parcial": parcial and (not previo or previo["parcial"]),
                                       "sin_texto": not textos, "afin": afin,
                                       # entre los afines, antes el que lleva la primera palabra del grupo
                                       "rango": next((i for i, w in enumerate(denominacion.split())
                                                      if w in _sin(f["denominacion"])), 99) if afin else 0}

    for variante in _variantes(palabras, autoridades):  # el nombre en castellano y, si toca, en la lengua cooficial
        consultar(" ".join(variante), "AND", False)
    if autoridades:  # con territorio: también los vigentes cuyo texto es anterior a REGCON (solo sus modificaciones)
        for variante in _variantes(palabras, autoridades):
            consultar(" ".join(variante), "AND", False, textos=False)
    if len(palabras) > 1 and len(vistos) < maximo:  # y los que llevan solo alguna palabra, marcados
        for variante in _variantes(palabras, autoridades):
            if len(variante) > 1 or variante is palabras:
                consultar(" ".join(variante), "OR", True)
    # Sectores afines, solo si hacen falta: menos de 3 con las palabras del usuario y sitio en la lista. Van detrás.
    if sum(not g["parcial"] for g in vistos.values()) < 3 and len(vistos) < maximo:
        for etiqueta, otras in _afines(palabras):
            for variante in _variantes(otras, autoridades)[:2]:
                consultar(" ".join(variante), "OR", False, afin=etiqueta)
    hoy = datetime.date.today()
    orden = {a: i for i, a in enumerate(autoridades)}
    resultados = []
    # Primero los que llevan todas las palabras (los parciales, por cuántas llevan); luego lo más cercano (provincia,
    # comunidad, estatal) y lo más reciente.
    buscadas = {_sin(w) for v in _variantes(palabras, autoridades) for w in v}  # 'comerç' -> 'comerc', como el nombre
    nivel = {c: orden.get(_id_autoridad(g["autoridad"]), -1) for c, g in vistos.items()}  # una vez por código
    candidatos_sustitucion = [g for g in vistos.values() if not g["parcial"] and not g["afin"]][:200]

    def parecido(nombre: str) -> float:  # parte del nombre que son palabras buscadas: 'EMPRESAS DE SEGURIDAD' antes
        # que 'SEGUROS…'. Sin contar el territorio ni el relleno ('… del Principado de Asturias', 'Conveni col·lectiu').
        propias = [w for w in re.findall(r"[a-z0-9ñç]+", _sin(nombre))
                   if w not in _VACIAS and w not in _PALABRAS_TERRITORIO and len(w) > 2] or [""]
        valor = round(sum(any(p in w for p in buscadas) for w in propias) / len(propias), 1)
        return max(valor, 0.1) if "[..]" in nombre else valor  # REGCON corta el nombre: lo buscado puede ir detrás

    # Entre los que de verdad llevan la palabra en el nombre, lo más cercano primero (el de la provincia antes que el
    # estatal); el parecido solo desempata dentro del mismo territorio.
    for f in sorted(vistos.values(), key=lambda f: (bool(f["afin"]), f["parcial"], parecido(f["denominacion"]) == 0,
                                                       orden.get(_id_autoridad(f["autoridad"]), 99), f["rango"],
                                                       -parecido(f["denominacion"]),
                                                       -(_fecha(f["fecha"]) or datetime.date.min).toordinal())):
        hasta = _fecha(f["vigencia_hasta"])
        r = {"codigo": f["codigo"], "denominacion": f["denominacion"], "autoridad_laboral": f["autoridad"],
             "estado": f["estado"], "ultimo_texto_publicado": f["fecha"], "vigencia": _vigencia(f)}
        if f["parcial"]:
            r["coincidencia"] = "parcial (no lleva todas las palabras)"
        if f["afin"]:
            r["coincidencia"] = f["afin"]
        if f.get("sin_texto"):
            r["ultimo_texto_publicado"] = None
            r["ultimo_tramite"] = f"{f['tramite']} ({f['fecha']})"
            r["texto"] = ("anterior a REGCON: allí solo constan sus modificaciones y tablas; el estado es el del último "
                          "trámite. leer_convenio lee el último trámite publicado.")
        if "EXTENSI" in f["tramite"]:
            r["tipo"] = "extensión de convenio: aplica a este ámbito el convenio de otro (art. 92.2 ET)"
        if hasta and hasta < hoy:
            r["vigencia_vencida"] = ("Su vigencia pactada terminó: si no está denunciado se prorroga; si lo está, "
                                     "sigue en ultraactividad mientras se negocia, salvo que lo haya sustituido otro "
                                     "convenio. Compruébalo con vigencia_convenio.")
            posterior = next((g for g in candidatos_sustitucion if g["codigo"] != f["codigo"]
                              and nivel[g["codigo"]] > nivel.get(f["codigo"], 99)  # comunidad o estatal sobre provincia
                              and (_fecha(g["vigencia_desde"]) or datetime.date.min) > hasta
                              and parecido(g["denominacion"]) >= max(0.5, parecido(f["denominacion"]) - 0.2)), None)
            if posterior:
                r["posible_sustitucion"] = (f"Hay un convenio posterior de otro ámbito ({posterior['codigo']}, "
                                            f"{posterior['autoridad']}, desde {posterior['vigencia_desde']}) que puede "
                                            "haberlo sustituido (p. ej. uno autonómico que unifica los provinciales): "
                                            "léelo antes de aplicar este.")
        resultados.append(r)
    # Los vencidos que otro posterior puede haber sustituido, detrás; los afines, al final.
    resultados.sort(key=lambda r: (r.get("coincidencia", "").startswith("afín"), "posible_sustitucion" in r))
    respuesta = {"consulta": " ".join(palabras), "territorio": entendido or "toda España",
                 "total": len(resultados), "resultados": resultados[:maximo],
                 "fuente": f"{REGCON}/consultaPublica",
                 "uso": "Texto o un artículo: leer_convenio(codigo, articulo= o buscar_en=). Estado y trámites "
                        "(revisiones salariales, prórrogas, denuncia): vigencia_convenio(codigo)."}
    if not resultados:
        respuesta["aviso"] = ("REGCON no tiene un convenio vigente con ese nombre en ese territorio. Prueba otras "
                              "palabras del nombre (en Cataluña, Baleares, la Comunitat Valenciana o Galicia se busca también en su lengua, pero puede estar con otras palabras), "
                              "otro ámbito o en_texto para buscar dentro de los textos.")
    elif entendido and entendido != "estatal":
        respuesta["nota"] = ("Se buscan también el convenio autonómico y el estatal (se aplican si no hay uno propio de "
                             "la provincia o en lo que este no regule); si no sale uno autonómico, puede estar "
                             "registrado con otras palabras o en la lengua cooficial: prueba otras.")
    if incompleta:
        respuesta["aviso_lista"] = (f"REGCON tiene más trámites con esas palabras ({max(incompleta)}) de los que se leen "
                                    "(30 por consulta): la lista puede no estar completa. Indica el territorio o más "
                                    "palabras del nombre.")
    if resultados and len(palabras) > 1 and all("coincidencia" in r for r in resultados):
        sueltas = [p for p in palabras if not any(p in _sin(r["denominacion"]) for r in resultados)]
        respuesta["aviso"] = ("Ningún convenio lleva todas las palabras" + (
            f"; '{', '.join(sueltas)}' no sale en ninguno: prueba otras palabras del nombre o, si es un municipio o "
            f"una comarca, indica su provincia en territorio=" if sueltas else "") + (". Se ha buscado en toda España." if not entendido else "."))
    if resultados and all(r.get("coincidencia", "").startswith("afín") for r in resultados):
        respuesta["aviso"] = ("Ningún convenio lleva esas palabras en su nombre: salen los de sectores afines (marcados). "
                              "Comprueba en su ámbito funcional (primeros artículos) que cubren la actividad.")
    return respuesta


def _vigencia(f: dict) -> str:
    return (f"{f['vigencia_desde']} a {f['vigencia_hasta']}" if f["vigencia_desde"] else
            f"hasta {f['vigencia_hasta']}" if f["vigencia_hasta"] else "no consta en REGCON")


def _buscar_en_textos(texto_: str, palabras: list[str], originales: list[str], autoridades: list[int], entendido: str,
                      ambito: str, maximo: int) -> dict:
    """Busca DENTRO del texto de los convenios con el buscador de textos de REGCON. Ese buscador distingue tildes
    ('hostelería' sí, 'hosteleria' no): las palabras van tal como las escribió el usuario. El sector, si se dio, va
    también en la búsqueda (su nombre sale en el propio texto), para que los suyos no se pierdan entre cientos; si así
    no sale nada, se busca sin él y se filtra por nombre."""
    if len(texto_) > 200:
        raise ValueError("en_texto: unas pocas palabras.")
    s = Sesion()
    s.texto(_TEXTOS, timeout=30)

    def buscar(consulta: str) -> tuple[int, list[dict]]:
        # REGCON exige dos palabras para 'todas en cualquier orden'; con una, frase exacta.
        datos = [("texto", consulta), ("coincidencia", "2" if len(consulta.split()) > 1 else "1"),
                 ("_idEstadoVigencia", "1"), ("idEstadoVigencia", "1"), ("idEstadoVigencia", "2"), ("idNaturaleza", "1"),
                 ("_idNaturaleza", "1"), *[("idAmbitoFuncional", a) for a in _AMBITOS[ambito]],
                 ("_idAmbitoFuncional", "1"), *[("idAutoridadLaboral", str(a)) for a in autoridades],
                 ("_idAutoridadLaboral", "1"), ("_buscar", ""), ("_esNuevaBusqueda", "1")]
        pagina = s.texto(_TEXTOS, datos=datos, timeout=60)
        if "debe informar" in pagina:
            raise ValueError("REGCON no admite esa búsqueda en el texto: usa dos o más palabras ('plus nocturnidad').")
        total, resultados = _total(pagina), []
        for n in range(1, 4):  # 10 por página; hasta 3 páginas
            if n > 1:
                if len(resultados) >= maximo or total <= (n - 1) * 10:
                    break
                pagina = s.texto(_TEXTOS, {"pagina": n}, timeout=60)
            for tr in pagina.partition("<tbody>")[2].partition("</tbody>")[0].split("<tr")[1:101]:
                celdas = _celdas(tr, 7)
                enlace = re.search(r'href="(https?://[^"\s]{1,500})"', tr)
                if len(celdas) >= 4 and re.fullmatch(r"[0-9]{14}", celdas[0]):
                    if palabras and not any(all(p in _sin(celdas[1]) for p in v)
                                            for v in _variantes(palabras, autoridades)):
                        continue  # si además se dio un sector, solo los de ese sector
                    resultados.append({"codigo": celdas[0], "denominacion": celdas[1][:300],
                                       "autoridad_laboral": celdas[3][:80],
                                       "publicacion": _enlace(enlace.group(1)) if enlace else None})
        return total, resultados

    base = " ".join(texto_.split())
    total, resultados = buscar(" ".join([base, *originales])) if originales else (0, [])
    if not resultados:
        total, resultados = buscar(base)
    orden = {a: i for i, a in enumerate(autoridades)}  # lo más cercano primero
    resultados.sort(key=lambda r: orden.get(_id_autoridad(r["autoridad_laboral"]), 99))
    respuesta = {"en_texto": texto_, "territorio": entendido or "toda España", "total_en_regcon": total,
                 "resultados": resultados[:maximo], "fuente": _TEXTOS,
                 "uso": "Para ver el pasaje: leer_convenio(codigo, buscar_en=...)."}
    if not resultados and total > 30:
        respuesta["aviso"] = (f"REGCON tiene {total} convenios con esas palabras y en los 30 primeros no hay ninguno del "
                              "sector: acota con más palabras o con el territorio; si el convenio está en catalán o gallego, su texto lo "
                              "dirá en esa lengua (vacances, vacacións): búscalo así.")
    elif not resultados:
        respuesta["aviso"] = ("Ningún convenio vigente de ese ámbito lleva esas palabras en su texto según REGCON (su "
                              "buscador distingue tildes: escríbelas como en el convenio).")
    return respuesta


def _enlace(url: str) -> str | None:
    """Enlace de REGCON a un boletín (lo escribe quien tramita: puede venir mal). Solo si es de un boletín de la
    lista; un http de esos dominios se pide por https."""
    url = url.strip().replace("&amp;", "&")
    if url.startswith("http://"):
        url = "https://" + url[7:]
    try:  # urlsplit lanza ValueError (con el host dentro) ante caracteres raros: un enlace así no vale
        partes = urllib.parse.urlsplit(url)
        if partes.netloc not in DOMINIOS and "www." + partes.netloc in DOMINIOS:  # 'boe.es' -> 'www.boe.es'
            url = partes._replace(netloc="www." + partes.netloc).geturl()
        comprobar_url(url)
        partes = urllib.parse.urlsplit(url)
    except (FuenteError, ValueError):
        return None
    if partes.netloc not in _PUBLICACIONES or not _forma_de_boletin(partes):
        return None  # REGCON no; y un enlace con forma rara (o con algo que parece un contacto) no se da
    return url


_PUBLICACIONES = BOLETINES | {"www.boe.es"}  # donde se publica un convenio: el BOE y los boletines; no otras fuentes
_CLAVES_ENLACE = {"id", "documentid", "fecha", "edicto", "control", "hash", "anuncio", "numero", "ano", "num", "anuncionumreg", "lang"}
_TELEFONO = re.compile(r"(?<![0-9])(?:\+?34)?[6789][0-9]{8}(?![0-9])")
# El BOP de Zaragoza enlaza el PDF de cada edicto así: UploadServlet?ruta=Boletines\2025\133\Edictos\bop_5032_2025.pdf
_RUTA_BOPZ = re.compile(r"Boletines\\[0-9]{4}\\[0-9]{1,4}\\Edictos\\bop_[0-9]{1,6}_[0-9]{4}\.pdf")


# Trozos de ruta reales de boletines hechos solo de palabras (los demás llevan cifras: fechas, números, ids).
_TROZOS_CONOCIDOS = {"documentos-anuncios-en-pdf", "buscador-anuncios", "document-del-dogc", "cm_orden_bocm", "bao_bob",
                     "gao-bog", "diario_boe", ".galleries"}
_EXTENSIONES = (".pdf", ".html", ".htm", ".php", ".aspx", ".xml", ".jsp", ".do")


def _trozo_seguro(trozo: str) -> bool:
    """Un trozo de ruta o un valor de parámetro que no puede ser un dato de contacto: sin teléfonos (también con
    guiones o puntos: '600-123-456'), sin nada con forma de dominio o correo ('maria.lopez.ejemplo.es') y sin dos o
    más palabras sin cifras ('Maria-Lopez-Garcia'), salvo los trozos conocidos de los boletines."""
    t = trozo.lower()
    if not t or t in _TROZOS_CONOCIDOS:
        return True
    if _TELEFONO.search(re.sub(r"[-._ ]", "", t)):
        return False
    base = t[:-len(next(e for e in _EXTENSIONES if t.endswith(e)))] if t.endswith(_EXTENSIONES) else t
    if "." in base.strip("."):  # un punto que no es el de la extensión: dominio, correo o nombre con puntos
        return bool(re.fullmatch(r"[0-9.]+", base))
    return any(c.isdigit() for c in base) or len(re.findall(r"[a-z]+", base)) < 2


def _forma_de_boletin(partes) -> bool:
    """Los enlaces reales a boletines son rutas de cifras, fechas y nombres de fichero, con algún parámetro conocido
    (id, documentId, edicto...). Quien tramita escribe el enlace: sin '@', sin '%', sin teléfonos, sin nombres ni
    dominios en la ruta y sin parámetros desconocidos, para que un dato suyo (o texto dirigido a Claude) no salga como
    'enlace'. Queda un riesgo: un nombre dentro de un trozo con cifras ('Acuerdo-...-2025') no se distingue."""
    if partes.fragment or partes.username or len(partes.path) > 300 or "@" in partes.geturl():
        return False
    if partes.netloc == "bop.dpz.es" and partes.path == "/BOPZ/UploadServlet":  # BOP de Zaragoza (examen L06, 5-nov)
        clave, _, valor = partes.query.partition("=")
        return clave == "ruta" and _RUTA_BOPZ.fullmatch(valor) is not None
    if not re.fullmatch(r"[A-Za-z0-9/._-]*", partes.path) or not all(map(_trozo_seguro, partes.path.split("/"))):
        return False
    for clave, valor in urllib.parse.parse_qsl(partes.query, keep_blank_values=True):
        if clave.lower() == "anuncionumreg":  # BOP de Valencia: '2025/08044' (año y número de registro)
            if not re.fullmatch(r"20[0-9]{2}/[0-9]{4,6}", valor):
                return False
        elif clave.lower() not in _CLAVES_ENLACE or not re.fullmatch(r"[A-Za-z0-9._-]{0,64}", valor) \
                or not _trozo_seguro(valor):
            return False
    return re.fullmatch(r"(?:[A-Za-z0-9]+=[A-Za-z0-9._/-]{0,64}&?)*", partes.query) is not None


# --- Qué enlace se MUESTRA a Claude (ronda 19, decidido por Jurium). Los enlaces de REGCON los escribe quien tramita y
# podrían llevar su nombre, su teléfono o texto dirigido a Claude: se usan por dentro para leer el texto (pasan por la
# lista blanca de red.py y _forma_de_boletin), pero NO se muestran. Se muestra el boletín y, aparte, la fecha del
# trámite. Solo salen enteros los que no puede escribir nadie de fuera: los de REGCON (los arma el conector) y los del
# BOE con forma de id de publicación.
_BOE_PUBLICADO = re.compile(r"https://www\.boe\.es/(?:boe/dias/20[0-9]{2}/[0-9]{2}/[0-9]{2}/pdfs/|diario_boe/txt\.php\?id=|"
                            r"buscar/doc\.php\?id=)BOE-[AB]-[0-9]{4}-[0-9]{1,7}(?:\.pdf)?")


def _mostrable(url: str) -> str:
    """El enlace tal cual si es de REGCON o del BOE con forma de id; si no, solo el nombre del boletín."""
    if _BOE_PUBLICADO.fullmatch(url) or (url.startswith(REGCON + "/") and re.fullmatch(r"[A-Za-z0-9/:._?=&-]{1,300}", url)):
        return url
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        host = ""
    if host not in DOMINIOS:
        return "enlace fuera de la lista (no se muestra)"
    return (f"{_NOMBRES.get(host) or f'boletín oficial ({host})'} (enlace no mostrado: lo escribió quien tramitó en "
            "REGCON; el texto se lee con leer_convenio, también un trámite con tramite='dd/mm/aaaa')")


def con_enlaces_mostrables(x):
    """Recorre la salida de una herramienta de convenios y deja solo enlaces mostrables (en cualquier campo o texto)."""
    if isinstance(x, str):
        return re.sub(r"https?://[^\s\"'<>(),]{1,500}", lambda m: _mostrable(m.group(0)), x) if "http" in x else x
    if isinstance(x, list):
        return [con_enlaces_mostrables(i) for i in x]
    if isinstance(x, dict):
        return {k: con_enlaces_mostrables(v) for k, v in x.items()}
    return x


# Boletines oficiales que REGCON enlaza y el conector no lee (certificado o TLS): se nombran, sin la URL.
_BOLETINES_SIN_LECTURA = {"bop.dipucr.es", "se1.dipucr.es", "bopbur.diputaciondeburgos.es", "portaldogc.gencat.cat"}
# Enlaces de forma conocida (solo cifras) que dicen el número de boletín y de anuncio: con ellos se encuentra antes.
_NUMEROS = {"bopbur.diputaciondeburgos.es": re.compile(r"/bopbur-(20[0-9]{2})-([0-9]{1,4})"),
            "www.diputaciondezamora.es": re.compile(r"/recursos/BOP/anuncios/(20[0-9]{2})/([0-9]{1,4})/(20[0-9]{6,8})\.pdf")}
# Nombre de cada boletín por su host, para la pista del navegador (skill convenios-boletines).
_NOMBRES = {
    "www.boe.es": "BOE", "236ws.dpteruel.es": "BOP de Teruel", "aplicacions.dipta.cat": "BOP de Tarragona",
    "www.dipta.cat": "BOP de Tarragona", "app.dipalme.org": "BOP de Almería", "boc.cantabria.es": "BOC (Cantabria)",
    "bocyl.jcyl.es": "BOCYL (Castilla y León)", "boletin.dguadalajara.es": "BOP de Guadalajara",
    "bomemelilla.es": "BOME (Melilla)", "bon.navarra.es": "BON (Navarra)", "www.navarra.es": "BON (Navarra)",
    "administracionelectronica.navarra.es": "BON (Navarra)", "bop.dacoruna.gal": "BOP de A Coruña",
    "bop.depourense.es": "BOP de Ourense", "bop.diba.cat": "BOP de Barcelona", "bop.dipcas.es": "BOP de Castellón",
    "bop.dipgra.es": "BOP de Granada", "bop.dipsoria.es": "BOP de Soria", "bop.dipualba.es": "BOP de Albacete",
    "bop.dipucordoba.es": "BOP de Córdoba", "bop.dipujaen.es": "BOP de Jaén", "bop.dipuleon.es": "BOP de León",
    "bop.diputoledo.es": "BOP de Toledo", "bop.dival.es": "BOP de Valencia", "bop.dphuesca.es": "BOP de Huesca",
    "bop.dpz.es": "BOP de Zaragoza", "bop.sede.diputaciondevalladolid.es": "BOP de Valladolid",
    "boppo.depo.gal": "BOP de Pontevedra", "bopsevilla.dipusevilla.es": "BOP de Sevilla",
    "sedeelectronicadipusevilla.es": "BOP de Sevilla", "deputacionlugo.gal": "BOP de Lugo",
    "docm.jccm.es": "DOCM (Castilla-La Mancha)", "doe.juntaex.es": "DOE (Extremadura)",
    "dogc.gencat.cat": "DOGC (Cataluña)", "portaldogc.gencat.cat": "DOGC (Cataluña), portal de PDF",
    "dogv.gva.es": "DOGV (Comunitat Valenciana)", "ebop.diputaciolleida.cat": "BOP de Lleida",
    "egoitza.gipuzkoa.eus": "BOG (Gipuzkoa)", "ias1.larioja.org": "BOR (La Rioja)",
    "juntadeandalucia.es": "BOJA (Andalucía)", "miprincipado.asturias.es": "BOPA (Asturias)",
    "sede.asturias.es": "BOPA (Asturias)", "s2.diphuelva.es": "BOP de Huelva",
    "sede.diputaciondesalamanca.gob.es": "BOP de Salamanca", "ssl4.ddgi.cat": "BOP de Girona",
    "www.araba.eus": "BOTHA (Álava)", "www.bizkaia.eus": "BOB (Bizkaia)", "www.boa.aragon.es": "BOA (Aragón)",
    "www.bocm.es": "BOCM (Comunidad de Madrid)", "www.bopcadiz.es": "BOP de Cádiz",
    "www.boplaspalmas.net": "BOP de Las Palmas", "www.bopmalaga.es": "BOP de Málaga",
    "www.bopsantacruzdetenerife.es": "BOP de Santa Cruz de Tenerife", "www.borm.es": "BORM (Región de Murcia)",
    "www.caib.es": "BOIB (Illes Balears)", "www.dip-alicante.es": "BOP de Alicante",
    "www.dipsegovia.es": "BOP de Segovia", "www.dipucuenca.es": "BOP de Cuenca", "www.diputacionavila.es": "BOP de Ávila",
    "www.diputaciondepalencia.es": "BOP de Palencia", "www.diputaciondezamora.es": "BOP de Zamora",
    "www.euskadi.eus": "BOPV (País Vasco)", "www.gobiernodecanarias.org": "BOC (Canarias)", "www.xunta.gal": "DOG (Galicia)",
    "bopbur.diputaciondeburgos.es": "BOP de Burgos", "bop.dipucr.es": "BOP de Ciudad Real",
    "se1.dipucr.es": "BOP de Ciudad Real"}
_SKILL = ("Usa la skill convenios-boletines: abre el boletín en el navegador, busca el anuncio por la fecha (y el "
          "código o la denominación), saca el texto y pásalo a analizar_texto_convenio(texto=..., codigo=...); si es un "
          "PDF que el navegador no deja leer, pide al usuario que lo guarde en la carpeta convenios/ y usa archivo=.")


def _pista(url: str | None, fila: dict | None, motivo: str, codigo: str = "") -> dict:
    """Lo que necesita la skill convenios-boletines para encontrar el texto en el navegador. Del enlace que escribió
    quien tramitó solo sale el boletín (si es uno oficial conocido) y el enlace entero solo si _mostrable lo deja."""
    try:
        partes = urllib.parse.urlsplit(url or "")
        host = partes.hostname or ""
    except ValueError:
        partes, host = None, ""
    oficial = host in _PUBLICACIONES or host in _BOLETINES_SIN_LECTURA
    pista = {"boletin": _NOMBRES.get(host) or (f"boletín oficial ({host})" if oficial else
                                                "no consta" if not url else "no se reconoce (el enlace no se muestra)"),
             "host": host if oficial else None, "fecha_publicacion": fila["fecha"] if fila else None,
             "tramite": fila["tramite"] if fila else None, "codigo": codigo or None, "motivo": motivo,
             "que_hacer": _SKILL}
    m = _NUMEROS[host].fullmatch(partes.path) if host in _NUMEROS and not partes.query else None
    if m:
        pista["boletin_numero"] = f"{int(m.group(2))}/{m.group(1)}"
        if m.lastindex == 3:
            pista["anuncio"] = m.group(3)
    if url and oficial and _mostrable(url) == url:
        pista["enlace"] = url
    return pista


def _motivo_sin_enlace(url: str | None) -> str:
    try:
        host = (urllib.parse.urlsplit(url).hostname or "") if url else ""
    except ValueError:
        host = ""
    if not url:
        return "REGCON no registra el enlace de la publicación."
    if host in _BOLETINES_SIN_LECTURA:
        return "El conector no puede conectar con este boletín (TLS antiguo, certificado no válido o puerto propio)."
    return "REGCON registró el enlace con una forma no válida o fuera de los boletines oficiales."


def _dominio(url: str) -> str:
    """Qué boletín es un enlace que no se puede leer, sin la URL (la escribe quien tramita: podría llevar texto
    dirigido a Claude o datos suyos). Solo se nombra el host si es un boletín oficial conocido o de la lista."""
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        host = ""
    if host in _BOLETINES_SIN_LECTURA:
        return f"en {host}, boletín oficial que el conector no puede leer (certificado o TLS); no se da el enlace"
    if host in _PUBLICACIONES:
        return f"en {host}, con un enlace de forma no válida (no se muestra)"
    return "enlace no válido o fuera de los boletines oficiales (no se muestra)"


def _es_texto(f: dict) -> bool:
    """El trámite que publica el texto del convenio: 'CONVENIO COLECTIVO (TEXTO NUEVO)' en cada renovación y
    'CONVENIO COLECTIVO' a secas la primera vez que se inscribe."""
    return "TEXTO NUEVO" in f["tramite"] or f["tramite"] in ("CONVENIO COLECTIVO", "EXTENSIÓN DE CONVENIO")


_FICHAS: dict[str, dict] = {}  # botón (id del trámite en REGCON) -> estado y enlace: no cambian una vez publicados
_TRAMITES: dict[str, tuple[float, list]] = {}  # código -> (cuándo, trámites)
_TEXTOS_LEIDOS: dict[str, str] = {}  # enlace del boletín -> texto ya extraído (los 6 últimos)


def _ficha(s: Sesion, codigo: str, boton: str) -> dict:
    """Estado del convenio y enlace al boletín de un trámite. La ficha trae datos de quien lo tramitó: no se tocan."""
    if boton in _FICHAS:
        return _FICHAS[boton]
    if getattr(s, "regcon", None) != codigo:  # la ficha solo se abre desde una búsqueda de ese convenio
        _consulta(s, [("codigoConvenio", codigo)])
        s.regcon = codigo
    pagina = s.texto(_CONSULTA, datos={boton: ""}, timeout=40)
    texto_ = " ".join(plano(pagina[:400_000]).split())
    # Solo palabras del vocabulario de estados de REGCON: una ficha manipulada no puede colar un nombre como estado.
    m = re.search(rf"{codigo} Copiar Código Copiar Denominación (?:Exportar Acuerdo )?", texto_)
    palabras = []
    for p in (texto_[m.end():m.end() + 120].split() if m else []):
        if p not in _PALABRAS_ESTADO:
            break
        palabras.append(p)
    while palabras and palabras[-1] in ("DE", "POR", "NO"):  # 'PUBLICADO ... Hoja': no acaba en preposición
        palabras.pop()
    estado = " ".join(palabras) if any(p in ("PUBLICADO", "DENUNCIADO", "REGISTRADO", "DEPOSITADO", "INSCRITO",
                                             "TRAMITADO", "DEROGADO", "ANULADO", "VIGENTE", "FINALIZADO")
                                       for p in palabras) else None
    # Cada enlace va detrás de su rótulo: 'El expediente está publicado con fecha...' (el texto) o 'ha sido objeto de
    # una corrección de errores...' (la corrección, aparte).
    def enlace_tras(rotulo: str) -> str | None:
        i = pagina.find(rotulo)
        m = re.search(r'href="(https?://[^"\s]{1,500})"', pagina[i:i + 1000]) if i >= 0 else None
        return m.group(1).replace("&amp;", "&") if m and "mites.gob.es" not in m.group(1) else None

    original = enlace_tras("está publicado con fecha")
    correccion = enlace_tras("corrección de errores")
    ficha = {"estado": estado.lower() if estado else None, "publicacion": _enlace(original) if original
             else None, "publicacion_no_legible": _dominio(original) if original and not _enlace(original) else None,
             "correccion_de_errores": (_enlace(correccion) or _dominio(correccion)) if correccion else None,
             "_original": original}  # solo para la pista del navegador (_pista); lo que empieza por '_' no sale
    if ficha["estado"]:  # solo lo que llegó bien
        if len(_FICHAS) > 2000:
            _FICHAS.clear()
        _FICHAS[boton] = ficha
    return ficha


def _tramites(s: Sesion, codigo: str) -> list[dict]:
    codigo = (codigo or "").strip()
    if not re.fullmatch(r"[0-9]{14}", codigo):
        raise ValueError("El código de convenio tiene 14 cifras (lo da buscar_convenio), p. ej. '28003005011981'.")
    guardado = _TRAMITES.get(codigo)
    if guardado and time.monotonic() - guardado[0] < 600:  # 10 minutos: leer y revisar el mismo convenio va rápido
        return guardado[1]
    pagina = _consulta(s, [("codigoConvenio", codigo)])
    filas = _filas(pagina)
    for n in range(2, min(4, (_total(pagina) + 14) // 15 + 1)):  # hasta 45 trámites: de sobra para el estado actual
        filas += _filas(_consulta(s, [("codigoConvenio", codigo)], n))
    if not filas:
        raise FuenteError(f"REGCON no tiene el convenio {codigo}.", 404)
    s.regcon = codigo  # la sesión ya tiene esta búsqueda: sus fichas se pueden abrir
    if len(_TRAMITES) > 50:
        _TRAMITES.clear()
    _TRAMITES[codigo] = (time.monotonic(), filas)
    return filas


def vigencia_convenio(codigo: str) -> dict:
    s = Sesion()
    filas = _tramites(s, codigo)
    textos = [f for f in filas if _es_texto(f)]
    actual = textos[0] if textos else filas[0]
    k = filas.index(actual)
    # El texto vigente y lo posterior (modificaciones, tablas, prórrogas, denuncia), con su ficha (estado y enlace):
    # el texto y los 9 más recientes; si hay más posteriores, se listan sin ficha. Lo anterior al texto, aparte.
    posteriores = filas[:k]
    con_ficha = posteriores[:9] + [actual]
    tramites = []
    estado = None
    for f in con_ficha:
        ficha = _ficha(s, f["codigo"], f["_boton"]) if f["_boton"] else {}
        estado = estado or ficha.get("estado")
        tramites.append({k_: v for k_, v in {**f, **ficha}.items() if not k_.startswith("_") and k_ not in
                         ("codigo", "denominacion", "autoridad", "estado")})
    r = {"codigo": actual["codigo"], "denominacion": actual["denominacion"], "autoridad_laboral": actual["autoridad"],
         "estado": estado, "vigencia": _vigencia(actual),
         "texto_vigente_y_posteriores": tramites, "fuente": _CONSULTA}
    if posteriores[9:]:
        r["mas_posteriores_sin_enlace"] = [{"tramite": f["tramite"], "fecha": f["fecha"]} for f in posteriores[9:]][:30]
    if filas[k + 1:]:
        r["anteriores_al_texto"] = [{"tramite": f["tramite"], "fecha": f["fecha"]} for f in filas[k + 1:]][:30]
    if not textos:
        r["nota_texto"] = ("REGCON no tiene el texto de este convenio (se registró antes de REGCON): solo sus trámites "
                           "posteriores.")
    hasta = _fecha(actual["vigencia_hasta"])
    if hasta and hasta < datetime.date.today():
        r["nota"] = ("Su vigencia pactada ya terminó. " + (
            "Es una extensión de convenio (art. 92.2 ET): un acto de la administración que aplica a este ámbito el "
            "convenio de otro; no se denuncia ni se prorroga como un convenio, y su alcance depende del convenio "
            "extendido y de que no haya ya uno propio. Compruébalo con buscar_convenio." if "EXTENSI" in actual["tramite"]
            else "Está denunciado: en principio sigue aplicándose (ultraactividad) mientras se negocia uno nuevo, "
            "salvo pacto en contrario (art. 86 ET) o que lo haya sustituido otro convenio (p. ej. uno autonómico que "
            "unifica los provinciales): compruébalo con buscar_convenio." if estado and "denunciado" in estado and
            "no denunciado" not in estado else
            "Sin denuncia registrada, se prorroga de año en año (art. 86.2 ET), salvo pacto en contrario o que lo "
            "haya sustituido otro convenio: compruébalo con buscar_convenio."))
    if any(t.get("publicacion_no_legible") for t in tramites):  # noqa: SIM102
        r["aviso"] = ("Alguna publicación está en un boletín que el conector no puede leer (o REGCON registró un "
                      "enlace con forma no válida): no se muestra el enlace. Búscala en ese boletín por la fecha del "
                      "trámite.")
    return r


def _texto_publicacion(s: Sesion, url: str) -> tuple[str, str, list[str]]:
    """(texto, enlace del que salió, avisos), guardando los 6 últimos."""
    if url not in _TEXTOS_LEIDOS:
        if len(_TEXTOS_LEIDOS) >= 6:
            _TEXTOS_LEIDOS.pop(next(iter(_TEXTOS_LEIDOS)))
        # Del disco si ya se leyó otro día (solo el texto extraído; un trámite nuevo es otro enlace y se descarga).
        guardado = cache_textos.leer("convenios", url)
        if (guardado and isinstance(guardado.get("texto"), str) and isinstance(guardado.get("url"), str)
                and isinstance(guardado.get("avisos"), list) and all(isinstance(a, str) for a in guardado["avisos"])):
            _TEXTOS_LEIDOS[url] = (guardado["texto"], guardado["url"], guardado["avisos"] + [
                f"Texto de la copia local del conector (descargado el {str(guardado.get('leido', ''))[:10]})."])
        else:
            texto_, de, avisos = _TEXTOS_LEIDOS[url] = _leer_publicacion(s, url)
            if not any("no se pudo leer" in a for a in avisos):  # un fallo pasajero no se guarda
                cache_textos.guardar("convenios", url, {"texto": texto_, "url": de, "avisos": avisos,
                                                        "leido": time.strftime("%Y-%m-%d")})
    return _TEXTOS_LEIDOS[url]


def _sin_tabla(texto_: str) -> bool:
    """Texto de un PDF con fuentes sin tabla de caracteres: sale en el área privada de Unicode."""
    muestra = [ch for ch in texto_[:200_000] if not ch.isspace()]
    return bool(muestra) and sum(0xE000 <= ord(ch) <= 0xF8FF for ch in muestra) > len(muestra) // 5


def _leer_publicacion(s: Sesion, url: str, seguir: bool = True) -> tuple[str, str, list[str]]:
    comprobar_url(url)
    datos, tipo = s.binario(url)
    if datos.startswith(b"%PDF-"):
        try:
            texto_ = texto_pdf_aislado(datos, queda_herramienta())  # en un proceso aparte, dentro del plazo de la herramienta
        except PdfError as e:
            raise FuenteError(f"No se pudo leer el PDF del boletín ({e}). Ábrelo con su enlace: {url}") from None
        # Fuentes sin tabla de caracteres (el texto sale en el área privada de Unicode): no se puede leer, y buscar en
        # él daría un 'no aparece' falso (BOPA de 2020).
        if _sin_tabla(texto_):
            raise FuenteError("El PDF del boletín usa fuentes sin tabla de caracteres: su texto no se puede extraer "
                              f"(no es que no esté). Ábrelo con su enlace: {url}")
        # Páginas casi sin texto en un PDF con imágenes: tablas o páginas escaneadas que no se pueden leer.
        vacias = [str(k + 1) for k, p in enumerate(texto_.split("\f")) if len(p.strip()) < 200]
        imagen = re.search(rb"/Subtype\s*/Image", datos)
        return texto_, url, ([f"Las páginas {', '.join(vacias[:20])} del PDF casi no tienen texto y el PDF lleva imágenes: "
                              "pueden ser tablas o páginas escaneadas que el conector no lee. Míralas en el PDF."]
                             if vacias and imagen else [])
    if "html" not in tipo and not datos.lstrip()[:200].lower().startswith((b"<!doctype", b"<html", b"<?xml")):
        raise FuenteError(f"El boletín devolvió un formato que no se lee ({tipo[:60]}). Ábrelo con su enlace: {url}")
    pagina = datos[:8_000_000].decode("utf-8", "replace")
    texto_ = plano(pagina)
    if seguir and not _articulos(texto_):  # la página del anuncio a veces solo enlaza el PDF del convenio (BON)
        for href in re.findall(r'href="([^"\s]{1,500}\.pdf[^"\s]{0,200})"', pagina, re.I)[:20]:
            pdf = _enlace(urllib.parse.urljoin(url, href.replace("&amp;", "&")))
            if pdf:
                try:
                    texto_pdf_, url_pdf, avisos = _leer_publicacion(s, pdf, seguir=False)
                except FuenteError:
                    texto_pdf_ = ""
                if not _articulos(texto_pdf_):  # p. ej. una descarga que solo funciona con JavaScript
                    return texto_, url, [f"El anuncio enlaza el texto en PDF y no se pudo leer desde aquí: {pdf}"]
                return texto_pdf_, url_pdf, avisos + [f"El anuncio enlazaba el texto en PDF: se ha leído {url_pdf}."]
    return texto_, url, []


# Encabezado de artículo al principio de línea: 'Artículo 15.—', 'Articulo 43º.-', 'Art. 30º.-', 'ARTÍCULO 7 bis',
# 'Article 61' (catalán), 'Artigo 11' o 'Art.º 13º' (gallego). No lo es una cita que empieza línea ('artículo 48 del
# Estatuto', 'Artículo 91, apartado'): tras el número no puede seguir una minúscula ni una coma. ('º' cuenta como letra
# para \b: por eso se mira que no siga otra cifra, y no \b.)
_ARTICULO = re.compile(r"(?m)^[ \t\f]*((?i:art[íi]culo|article|artigo|art\.?º|art\.|cl[áa]usula))[ \t]*([0-9]{1,3}(?: [0-9]{1,2}(?=[ \t]*\.?[ \t]*[—–.-]))?)(?![0-9])"
                       r"(?:[ \t.º\-–]{0,12}((?i:bis|ter))(?![a-zA-Z]))?(?![.,][0-9])(?![ \t]{0,40}[a-záéíóúñç,;(])")
_FUERA = "fuera del articulado (índice, preámbulo, anexo o texto posterior del boletín)"


def _articulos(texto_: str) -> list[tuple[str, int, int]]:
    """(número, inicio, fin) de cada artículo del texto. Si un número sale varias veces (índice y cuerpo, o el mismo
    anuncio en dos lenguas), se queda con el del cuerpo en castellano: el más largo, y el castellano antes que el
    catalán o el gallego. El último artículo no pasa de 20.000 caracteres: detrás suele haber anexos o, en un boletín
    entero, otros anuncios."""
    marcas = _marcas(texto_)
    cortes = [m.start() for m in _FIN_ARTICULADO.finditer(texto_)]

    def fin(k: int, a: int) -> int:  # hasta el siguiente artículo o, antes, unas disposiciones o un anexo
        b = marcas[k + 1][1] if k + 1 < len(marcas) else min(len(texto_), a + 20_000)
        i = bisect.bisect_right(cortes, a)
        return min(b, cortes[i]) if i < len(cortes) else b
    tramos = [(n, a, fin(k, a), p not in ("article", "artigo") and not p.endswith("º"))
              for k, (n, a, p) in enumerate(marcas)]
    # El articulado principal: la serie correlativa (1, 2, 3...) más larga en artículos y, a igualdad, con más texto;
    # el castellano antes. Así no ganan ni el índice (correlativo pero corto) ni el reglamento de un anexo que vuelve
    # a empezar en 1.
    cadena: dict[int, tuple] = {}  # posición en tramos -> (castellano, artículos, longitud acumulada, anterior)
    ultimo: dict[tuple, int] = {}  # (número, castellano) -> mejor posición que acaba en ese número
    for k, (n, a, b, es) in enumerate(tramos):
        if not n.isdigit():
            continue
        prev = ultimo.get((int(n) - 1, es))
        if prev is None and (int(n) - 2, es) in ultimo and int(n) > 2:  # un hueco en la numeración no rompe la serie
            prev = ultimo[(int(n) - 2, es)]
        cadena[k] = (es, (cadena[prev][1] if prev is not None else 0) + 1,
                     (cadena[prev][2] if prev is not None else 0) + b - a, prev)
        ultimo[(int(n), es)] = k  # el más cercano: el artículo 2 del cuerpo sigue al 1 del cuerpo, no al del índice
    mejor: dict[str, tuple] = {}
    if cadena:
        k = max(cadena, key=lambda x: cadena[x][:3])
        while k is not None:
            n, a, b, _ = tramos[k]
            mejor[n] = ((True, True, b - a), (n, a, b))
            k = cadena[k][3]
    for n, a, b, es in tramos:  # los que no están en la serie ('7 bis', o solo en un anexo): el más largo
        clave = (False, es, b - a)
        if n not in mejor or clave > mejor[n][0]:
            mejor[n] = (clave, (n, a, b))
    return sorted((t for _, t in mejor.values()), key=lambda t: t[1])


_FIN_ARTICULADO = re.compile(r"(?m)^[ \t\f]*(?:Disposici[oó]n (?:adicional|transitoria|final|derogatoria)|"
                             r"DISPOSICI[OÓ]N(?:ES)? (?:ADICIONAL|TRANSITORIA|FINAL|DEROGATORIA)|ANEXO|Anexo)\b")
_INDICE = re.compile(r"\.{4,}|…{2,}|_{4,}")  # 'Artículo 1. Ámbito ......... 4': línea de índice


def _marcas(texto_: str) -> list[tuple[str, int, str]]:
    """(número, posición, palabra) de cada encabezado de artículo, en orden (sin las líneas del índice)."""
    salida = []
    for m in _ARTICULO.finditer(texto_):
        if not m.group(1)[0].isupper():
            continue
        fin = texto_.find("\n", m.start(), m.start() + 300)
        if _INDICE.search(texto_, m.start(), fin if fin >= 0 else m.start() + 300):
            continue
        salida.append((m.group(2).replace(" ", "") + (" " + m.group(3).lower() if m.group(3) else ""), m.start(), m.group(1).lower()))
    if not salida:  # algunos PDF (BOPA) pasan a minúscula el principio de línea: 'artículo 23.—Descansos'
        salida = [(m.group(2).replace(" ", "") + (" " + m.group(3).lower() if m.group(3) else ""), m.start(), m.group(1).lower())
                  for m in _ARTICULO.finditer(texto_) if re.match(r"[ \t]*\.?[ \t]*[—–-]", texto_[m.end():m.end() + 6])]
    return salida


def leer_convenio(codigo: str = "", articulo: str = "", buscar_en: str = "", publicacion: str = "",
                  max_caracteres: int = 20000, desde: int = 0, tramite: str = "") -> dict:
    s = Sesion()
    r: dict = {}
    texto_nuevo = None  # la fila de REGCON del trámite que se lee (para la pista del navegador)
    if publicacion.strip():
        url = _enlace(publicacion)
        if not url:
            raise ValueError("publicacion: el enlace de un boletín que dé vigencia_convenio (de la lista de boletines "
                             "oficiales que el conector puede leer).")
        if re.fullmatch(r"[0-9]{14}", (codigo or "").strip()):  # en un boletín entero, se empieza en este convenio
            r["codigo"] = codigo.strip()
    else:
        filas = _tramites(s, codigo)
        if tramite.strip():  # un trámite concreto (tablas, modificación...) por su fecha, como lo da vigencia_convenio
            texto_nuevo = next((f for f in filas if f["fecha"] == tramite.strip() and f["_boton"]), None)
            if not texto_nuevo:
                raise ValueError(f"No hay un trámite del {tramite.strip()[:12]} en este convenio: mira las fechas en "
                                 "vigencia_convenio.")
        else:
            texto_nuevo = next((f for f in filas if _es_texto(f) and f["_boton"]), None)
        sin_texto = texto_nuevo is None
        if sin_texto:  # texto anterior a REGCON: se lee el último trámite publicado (modificación, tablas...)
            texto_nuevo = next((f for f in filas if f["_boton"]), None)
            if not texto_nuevo:
                raise FuenteError("REGCON no tiene ningún trámite de este convenio con su ficha; mira vigencia_convenio.")
        ficha = _ficha(s, texto_nuevo["codigo"], texto_nuevo["_boton"])
        r = {"codigo": texto_nuevo["codigo"], "denominacion": texto_nuevo["denominacion"], "estado": ficha["estado"],
             "vigencia": _vigencia(texto_nuevo), "texto_publicado": texto_nuevo["fecha"]}
        if tramite.strip():
            del r["texto_publicado"]
            r["tramite_leido"] = f"{texto_nuevo['tramite']} ({texto_nuevo['fecha']})"
            if sum(1 for f in filas if f["fecha"] == tramite.strip() and f["_boton"]) > 1:
                r["aviso_tramite"] = (f"Hay varios trámites del {tramite.strip()}: se lee el más reciente de la lista "
                                      "(mira vigencia_convenio).")
        if sin_texto:
            r["texto_publicado"] = None
            r["aviso_texto"] = (f"El texto de este convenio es anterior a REGCON y no está en él. Se lee el último "
                                f"trámite publicado: {texto_nuevo['tramite']} ({texto_nuevo['fecha']}). El texto "
                                "completo, en el boletín de la provincia (búscalo por su código o fecha).")
            r["pista_navegador"] = _pista(ficha.get("_original"), texto_nuevo, (
                "Texto anterior a REGCON: la fecha y el trámite de la pista son los del último trámite que REGCON "
                "enlaza, no los del texto. Busca el texto en la hemeroteca de ese boletín por la denominación o el "
                "código (los convenios antiguos se publicaban en el boletín de la provincia)."), texto_nuevo["codigo"])
        if ficha.get("correccion_de_errores"):
            r["correccion_de_errores"] = ficha["correccion_de_errores"]  # léela con publicacion=: corrige este texto
        posteriores = [f"{f['tramite']} ({f['fecha']})" for f in filas[:filas.index(texto_nuevo)]][:10]
        if posteriores:
            r["posteriores_al_texto"] = posteriores
            r["aviso_posteriores"] = ("Después de este texto hay trámites que pueden cambiarlo (tablas salariales, "
                                      "modificaciones): sus fechas, en vigencia_convenio; se leen con "
                                      "leer_convenio(codigo, tramite='dd/mm/aaaa').")
        url = ficha["publicacion"]
        if not url:
            return {**r, "publicacion": ficha["publicacion_no_legible"],
                    "aviso": "El texto está en un boletín que el conector no puede leer (o REGCON registró un enlace "
                             "con forma no válida): no se muestra el enlace. Búscalo en ese boletín por la fecha de "
                             "publicación.",
                    "pista_navegador": _pista(ficha.get("_original"), texto_nuevo,
                                              _motivo_sin_enlace(ficha.get("_original")), texto_nuevo["codigo"])}
    codigo_ = r.get("codigo", "")
    try:
        texto_, url, avisos = _texto_publicacion(Sesion(), url)
    except FuenteError as e:
        if e.codigo == 404:
            return {**r, "publicacion": url, "aviso": "El boletín ya no sirve el documento en el enlace que registró "
                                                      "REGCON (404). Búscalo en ese boletín por la fecha de publicación.",
                    "pista_navegador": _pista(url, texto_nuevo, "Enlace roto (404): busca el anuncio en la hemeroteca "
                                                                "del boletín por la fecha.", codigo_)}
        # PDF ilegible o con fuentes sin tabla, formato raro, web caída: el navegador puede llegar (si fue un fallo de
        # red pasajero, basta con repetir leer_convenio).
        return {**r, "publicacion": url,
                "aviso": f"No se pudo leer el texto desde el conector: {con_enlaces_mostrables(str(e))[:600]}",
                "pista_navegador": _pista(url, texto_nuevo, "No se pudo leer desde el conector (PDF ilegible, fuentes "
                                                            "sin tabla de caracteres o fallo de la web).", codigo_)}
    arts = _articulos(texto_)
    if not arts and (tramite.strip() or publicacion.strip()) and len(texto_.strip()) > 300:
        # Un trámite (tablas salariales, una modificación) no tiene artículos: se da entero.
        return {**r, "publicacion": url, **({"avisos_lectura": avisos} if avisos else {}),
                "nota": "Trámite sin articulado (tablas, modificación o acuerdo): se da el texto entero.",
                "texto": recortar(texto_, max_caracteres, desde)}
    if not arts and len(texto_) < 20_000:  # una portada, un buscador o una web que carga el texto con JavaScript
        return {**r, "publicacion": url, **({"avisos_lectura": avisos} if avisos else {}),
                "aviso": "En ese enlace no está el texto del convenio (portada, buscador o página que lo carga aparte): "
                         "ábrelo en el navegador.",
                "pista_navegador": r.get("pista_navegador") or _pista(
                    url, texto_nuevo, "El enlace lleva a una portada, un buscador o una página que carga el texto "
                                      "aparte (JavaScript).", codigo_)}
    if not arts and "pista_navegador" not in r:
        r["pista_navegador"] = _pista(url, texto_nuevo, "No se reconocen artículos en lo leído: puede ser un boletín "
                                                        "entero o un formato raro.", codigo_)
    return _analizar(r, texto_, arts, avisos, {"publicacion": url}, articulo, buscar_en, max_caracteres, desde)


def _analizar(r: dict, texto_: str, arts: list, avisos: list, fuente: dict, articulo: str, buscar_en: str,
              max_caracteres: int, desde: int) -> dict:
    """Lo común a leer_convenio y analizar_texto_convenio: un artículo, pasajes de una materia o el texto por partes."""
    avisos = list(avisos)  # copia: la lista guardada en la caché no se toca
    # Un boletín entero en un PDF: el código del convenio (en su resolución) sale lejos del principio porque antes van
    # otros anuncios. Se empieza en el de este convenio.
    if r.get("codigo") and (i := texto_.find(r["codigo"])) > 15_000 and len(texto_) - i > 20_000:
        texto_ = texto_[texto_.rfind("\n", 0, i - 3000) + 1:]
        arts = _articulos(texto_)
        avisos.append(("El enlace" if fuente else "El texto") + " es un boletín con varios anuncios: el texto empieza en "
                      "el de este convenio y el final puede incluir anuncios posteriores.")
    if avisos:
        r["avisos_lectura"] = avisos
    r |= {**fuente, "caracteres_en_total": len(texto_)}
    if articulo.strip():
        pedido = re.sub(r"(?i)^\s*(art[íi]culo|art\.?|cl[áa]usula)\s*", "", articulo[:40]).lower().replace(".º", "").replace(
            "º", "").replace("ª", "")
        m = re.fullmatch(r"\s*([0-9]{1,3})\s*(bis|ter)?\s*((?:[.,]\s*[0-9]{1,3}|\s*[a-z]\)|\s*apartado.*)?)\s*", pedido)
        n = f"{m.group(1)} {m.group(2)}" if m and m.group(2) else m.group(1) if m else " ".join(pedido.split())
        tramo = next((t for t in arts if t[0] == n), None)
        if not tramo:
            return {**r, "aviso": f"No encuentro el artículo {articulo[:20]} en el texto publicado.",
                    "articulos": [t[0] for t in arts][:300]}
        salida = {**r, "articulo": n, "texto": recortar(texto_[tramo[1]:tramo[2]].strip(), max_caracteres)}
        posiciones = {t[0]: t[1] for t in arts}
        if n.isdigit() and str(int(n) - 1) in posiciones and str(int(n) + 1) in posiciones and not (
                posiciones[str(int(n) - 1)] < tramo[1] < posiciones[str(int(n) + 1)]):
            salida["aviso_fuera_de_orden"] = (f"Este 'artículo {n}' está fuera del orden del articulado (el principal "
                                              f"pasa del {int(n) - 1} al {int(n) + 1}): probablemente es de un anexo o "
                                              "una tabla. Compruébalo en el boletín.")
        if m and m.group(3).strip():
            salida["nota_apartado"] = f"Se da el artículo {n} entero: busca en él el apartado {m.group(3).strip(' .,')}."
        if sum(1 for t in _marcas(texto_) if t[0] == n) > 1 + sum(1 for t in _marcas(texto_[:tramo[1]]) if t[0] == n):
            salida["aviso_repetido"] = (f"Más adelante hay otro 'artículo {n}' (de un anexo o reglamento incluido en el "
                                        "convenio): este es el del articulado principal.")
        return salida
    if buscar_en.strip():
        return {**r, "buscar_en": buscar_en, **_pasajes(texto_, arts, buscar_en)}
    return {**r, "texto": recortar(texto_, max_caracteres, desde),
            "articulos": [t[0] for t in arts][:300]}


def _archivo(nombre: str) -> Path:
    """Solo un PDF de la carpeta convenios/, por su nombre (sin rutas: nada fuera de esa carpeta)."""
    nombre = (nombre or "").strip()
    if not re.fullmatch(r"[^\\/:*?\"<>|\x00-\x1f]{1,150}\.pdf", nombre, re.I) or nombre.startswith("."):
        raise ValueError("archivo: el nombre de un PDF de la carpeta convenios/ (sin ruta), p. ej. 'BOPBU_2024_123.pdf'.")
    ruta = (CARPETA / nombre).resolve()
    if ruta.parent != CARPETA or not ruta.is_file() or ruta.stat().st_nlink > 1:  # sin enlaces duros a otro sitio
        raise ValueError(f"No está {nombre[:80]!r} en la carpeta {CARPETA}: guárdalo ahí desde el boletín "
                         "o mira los que hay con analizar_texto_convenio() sin argumentos.")
    return ruta


def analizar_texto_convenio(texto: str = "", archivo: str = "", articulo: str = "", buscar_en: str = "",
                            codigo: str = "", max_caracteres: int = 20000, desde: int = 0) -> dict:
    """El texto de un convenio que el conector no pudo leer de su boletín: pegado (lo sacó Claude con el navegador) o
    en un PDF que el usuario guardó en convenios/. Sin red: se analiza igual que en leer_convenio."""
    codigo = (codigo or "").strip()
    if codigo and not re.fullmatch(r"[0-9]{14}", codigo):
        raise ValueError("codigo: el de 14 cifras del convenio (lo da buscar_convenio), o vacío.")
    if texto.strip() and archivo.strip():
        raise ValueError("Pasa texto o archivo, no los dos.")
    if archivo.strip():
        ruta = _archivo(archivo)
        if ruta.stat().st_size > MAX_PDF:
            raise ValueError("El PDF pasa de 25 MB: guarda solo el anuncio del convenio.")
        datos = ruta.read_bytes()
        if not datos.startswith(b"%PDF-"):
            raise ValueError("Ese archivo no es un PDF.")
        try:
            texto_ = texto_pdf_aislado(datos, queda_herramienta())  # en un proceso aparte, con topes
        except PdfError as e:
            raise FuenteError(f"No se pudo leer el PDF ({e}).") from None
        r: dict = {"archivo": ruta.name}
    elif texto.strip():
        if len(texto) > MAX_TEXTO:
            raise ValueError(f"texto: como mucho {MAX_TEXTO} caracteres. Pasa solo el anuncio del convenio o guarda el "
                             "PDF en la carpeta convenios/ y usa archivo=.")
        # Lo que copia el navegador: saltos de Windows y espacios duros, que no dejarían ver los encabezados.
        texto_ = texto.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ").lstrip("﻿")
        r = {}
    else:
        CARPETA.mkdir(parents=True, exist_ok=True)
        archivos = sorted(CARPETA.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        return {"carpeta": str(CARPETA), "archivos": [p.name for p in archivos[:100]],
                "uso": "analizar_texto_convenio(texto=...) con el texto sacado del boletín, o archivo= con un PDF de "
                       "esa carpeta (skill convenios-boletines)."}
    if _sin_tabla(texto_):
        raise FuenteError("El PDF usa fuentes sin tabla de caracteres: su texto no se puede extraer (no es que no esté). "
                          "Prueba a abrirlo en el visor de PDF del navegador y copiar el texto, o léelo allí.")
    r = {**({"codigo": codigo} if codigo else {}), **r,
         "origen": "texto aportado por el usuario o el navegador: cita el boletín"}
    arts = _articulos(texto_)
    avisos = []
    if not arts:
        avisos.append("El texto no tiene artículos reconocibles (tablas, una modificación o un formato raro): se da "
                      "entero, por partes con desde, o por pasajes con buscar_en.")
    if codigo and codigo not in texto_:
        avisos.append("El código del convenio no aparece en el texto: comprueba que es su anuncio (los textos antiguos "
                      "no siempre lo llevan).")
    return _analizar(r, texto_, arts, avisos, {}, articulo, buscar_en, max_caracteres, desde)


# Materias frecuentes en catalán y gallego, para buscar pasajes en convenios publicados en esas lenguas.
_MATERIAS = {"vacaciones": ("vacances", "vacacions"), "nocturnidad": ("nocturnitat", "nocturnidade"),
             "antiguedad": ("antiguitat", "antiguidade"), "jornada": ("xornada",), "salario": ("salari",),
             "despido": ("acomiadament", "despedimento"), "festivos": ("festius",), "dietas": ("dietes", "axudas"),
             "permisos": ("permisos retribuits", "licencias"), "prueba": ("prova", "proba"),
             "extraordinarias": ("extraordinaries",), "horas": ("hores",),
             "incapacidad": ("incapacitat",), "transporte": ("transport",)}


def _pasajes(texto_: str, arts: list, buscar_en: str, traduciendo: bool = False) -> dict:
    """Los trozos del convenio donde aparece la materia, literales y con su artículo. Primero los artículos cuyo
    título es la materia ('Art. 31º.- VACACIONES'), desde su encabezado; luego el resto, en orden."""
    terminos = [t for t in re.findall(r"[a-z0-9ñç]{3,}", _sin(buscar_en)) if t not in _VACIAS][:6]
    if not terminos:
        raise ValueError("buscar_en: la materia en una o dos palabras ('nocturnidad', 'vacaciones').")
    llano = _sin_acentos(texto_).lower()  # misma longitud que el texto: las posiciones valen para los dos
    pasajes, usados = [], []

    def linea(i: int) -> str:  # la línea de la posición i, mirando como mucho 2.000 caracteres a cada lado
        ini = llano.rfind("\n", max(0, i - 2000), i) + 1 or max(0, i - 2000)
        fin = llano.find("\n", i, i + 2000)
        return llano[ini:fin if fin >= 0 else min(len(llano), i + 2000)]

    inicios = [t[1] for t in arts]

    # 1) Los artículos cuyo título es la materia ('Art. 31º.- VACACIONES'), enteros desde su encabezado.
    for n, a, b in arts:
        if all(re.search(rf"(?<![a-z0-9ñç]){t}", linea(a)) for t in terminos):
            usados.append((a, min(b, a + 1500)))
            pasajes.append({"articulo": n, "texto": texto_[a:min(b, a + 1500)].strip() + (
                f"\n[... el artículo sigue: léelo entero con articulo='{n}']" if b > a + 1500 else "")})
    # 2) Donde más se menciona, con el artículo en que cae (sin repetir lo ya dado ni las líneas del índice).
    otros = 0
    # Ventanas acotadas (una línea de megas sin saltos no hace recorrer el texto entero en cada aparición) y como
    # mucho 5.000 apariciones miradas.
    for vuelta, m in enumerate(re.finditer(rf"(?<![a-z0-9ñç]){re.escape(terminos[0])}", llano)):
        if vuelta == 5000:
            break
        ini_linea = llano.rfind("\n", max(0, m.start() - 2000), m.start()) + 1
        if ini_linea and _ARTICULO.match(texto_, ini_linea):
            continue  # línea de encabezado o de índice: o ya salió en 1), o es el índice
        a = llano.rfind("\n", max(0, m.start() - 2000), max(0, m.start() - 300)) + 1 or max(0, m.start() - 300)
        b = llano.find("\n", m.end() + 500, m.end() + 2000)
        b = min(len(llano), m.end() + 1000) if b < 0 else b
        k = bisect.bisect_right(inicios, m.start()) - 1
        art = arts[k] if k >= 0 and m.start() < arts[k][2] else None
        if art:  # el pasaje no se sale del artículo en que cae (no mezcla el final del anterior)
            a, b = max(a, art[1]), min(b, art[2])
        elif k + 1 < len(arts):  # ni se mete en el siguiente
            b = min(b, arts[k + 1][1])
        if any(a < u2 and b > u1 for u1, u2 in usados) or not all(
                re.search(rf"(?<![a-z0-9ñç]){re.escape(t)}", llano[a:b]) for t in terminos[1:]):
            continue
        usados.append((a, b))
        otros += 1
        if len(pasajes) < 8:
            pasajes.append({"articulo": art[0] if art else _FUERA, "texto": texto_[a:min(b, a + 1500)].strip() + (
                "\n[... sigue]" if b > a + 1500 else "")})
        if otros == 40:
            break
    if not pasajes and not traduciendo:
        for otra in _MATERIAS.get(terminos[0], ()):  # el convenio puede estar en catalán o gallego
            salida = _pasajes(texto_, arts, " ".join([otra, *terminos[1:]]), True)
            if salida["pasajes"]:
                return {**salida, "nota_lengua": f"No sale '{terminos[0]}'; sí '{otra}' (texto en catalán o gallego)."}
    salida = {"pasajes": pasajes[:8]}
    if len(usados) > 8:
        salida["nota"] = f"Aparece en más sitios ({len(usados)}{'+' if otros == 40 else ''}); estos son los 8 primeros."
    if not pasajes:
        salida["aviso"] = ("No aparece en el texto publicado con esas palabras. Prueba un sinónimo; si el convenio está "
                           "en catalán, gallego o euskera, búscalo en esa lengua (vacances, vacacións, oporrak).")
    return salida


def leer_documento_oficial(url: str, buscar_en: str = "", max_caracteres: int = 20000, desde: int = 0) -> dict:
    """Un PDF o una página del BOE o de un boletín oficial de la lista (diarios autonómicos y BOP), leído con el lector
    propio y aislado (pdf.py): para que nadie instale nada para leer un PDF oficial (examen F05, 5-nov). Solo esos
    dominios: ni REGCON ni la AEAT (tienen su propia confianza) ni nada de fuera."""
    url = (url or "").strip()
    try:
        host = urllib.parse.urlsplit(url).netloc
    except ValueError:
        host = ""
    if not url.startswith("https://") or host not in _PUBLICACIONES:
        raise ValueError("url: el enlace https de un documento del BOE o de un boletín oficial (BOJA, DOGC, BOCM, BOP...)."
                         " De otras webs, ábrelo en el navegador o da el enlace al usuario; no instales nada para leerlo.")
    texto_, leida, avisos = _leer_publicacion(Sesion(), url)
    r = {"fuente": leida, "caracteres_en_total": len(texto_), **({"avisos": avisos} if avisos else {})}
    if not buscar_en.strip():
        return {**r, "texto": recortar(texto_, max_caracteres, desde)}
    parrafos, actual = [], ""  # el PDF trae líneas: se juntan en párrafos para dar pasajes enteros
    for linea in texto_.split("\n"):
        actual = f"{actual} {linea.strip()}".strip()
        if actual and (linea.rstrip().endswith((".", ":", ";")) or len(actual) > 1200):
            parrafos.append(actual)
            actual = ""
    return {**r, "buscar_en": buscar_en, **pasajes([("documento", parrafos + [actual] if actual else parrafos)],
                                                   buscar_en)}
