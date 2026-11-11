# Fuentes oficiales (versión abierta) 0.3.0. Hecho por Jurium. Licencia MIT (LICENSE).
"""Verificación de las citas de un escrito: artículos y disposiciones de ley (contra el BOE consolidado), consultas
de la DGT, resoluciones del TEAC, sentencias del TC, asuntos del TJUE y artículos de normas de la UE (contra su versión consolidada
en CELLAR). Principio: nunca dar por erróneo ni por correcto lo que no se ha podido comprobar con seguridad. Si la ley de una cita no se identifica sin dudas, la cita va a "no comprobadas"."""
from __future__ import annotations

import bisect
import re
from collections import Counter

import boe
import normas_ue
import perfil
import relaciones
from red import FuenteError

BASICO = perfil.LIGHT  # versión light: solo leyes del BOE y de la UE ("existe y está vigente"); sin doctrina ni alertas del TC
if not BASICO:
    import hacienda
    import tc
    import tjue

_MAX_CITAS = 15  # artículos y disposiciones; el resto de identificadores, _MAX_OTRAS cada tipo
_MAX_OTRAS = 6
_ART = re.compile(r"\bart(?:[ií]culos?|s?\.)\s*(?=[0-9])", re.I)
# Piezas del número de un artículo: '52', '52.c)', '20.Uno.9º', '1.968', 'bis', 'c)', '(2)'.
_PIEZA = re.compile(r"[0-9][0-9.,ºª]*(?:\.[A-Za-z]{2,7}(?:\.[0-9]{1,3}º?)*)?(?:\.?[a-zñ]\))?,?|"
                    r"(?:bis|ter|quater|quinquies|sexies),?|\(?[a-zñ]\),?|\([0-9]{1,2}\),?", re.I)
_ORDINAL = (r"(?:unica|primera|segunda|tercera|cuarta|quinta|sexta|septima|octava|novena|decima|undecima|duodecima|"
            r"decimo[a-z]{4,9}|(?:vigesim|trigesim|cuadragesim|quincuagesim|sexagesim)[ao](?: ?(?:primera|segunda|"
            r"tercera|cuarta|quinta|sexta|septima|octava|novena))?|[0-9]{1,2} ?\.? ?[ªºa])")
# Sobre el texto sin tildes y en minúsculas (misma longitud que el original): 'disposición transitoria cuarta'.
_DISP = re.compile(rf"\bdisposicion (?:adicional|transitoria|final|derogatoria) {_ORDINAL}\b")
_DISP_SIGLA = re.compile(r"\bD\.? ?[ATF]\.? [0-9]{1,2} ?\.? ?[ªº]")  # 'DA 21ª', 'D.T. 4ª' (en mayúsculas: 'da' es un verbo)
_NUMERO_LEY = re.compile(r"\b(ley org[aá]nica|real decreto legislativo|real decreto-ley|real decreto ley|real decreto|"
                         r"ley|lo|rdleg|rdl|rd)\s+([0-9]{1,4}/[0-9]{4})", re.I)
_FECHA_LEY = re.compile(r",? de [0-9]{1,2} de (?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|"
                        r"octubre|noviembre|diciembre)")
_AUTONOMICA = re.compile(r"\b(?:andalucia|aragon|asturias|illes balears|baleares|canarias|cantabria|castilla[- ]la mancha|"
                         r"castilla y leon|cataluna|catalunya|comunitat valenciana|comunidad valenciana|extremadura|"
                         r"galicia|comunidad de madrid|region de murcia|murcia|navarra|pais vasco|euskadi|la rioja|"
                         r"ceuta|melilla|autonomica|parlamento de|cortes de|generalitat|junta de|xunta)\b")
_REDACCION = re.compile(r"redacci[oó]n (?:dada|introducida|vigente dada)? ?por (?:el |la |los )?(?:art[ií]culo [^,;]{1,20} de "
                        r"(?:la |el )?)?((?:ley org[aá]nica|real decreto legislativo|real decreto-ley|real decreto|ley|"
                        r"lo|rdleg|rdl|rd)\s+[0-9]{1,4}/[0-9]{4})", re.I)
# Normas de la UE (sobre el texto sin tildes y en minúsculas): por número ('Directiva 2006/112/CE', 'Reglamento (UE)
# 2016/679'; un reglamento o una decisión, solo con su (UE)/(CE): 'Reglamento 439/2007' puede ser el RD español), por
# sigla o nombre (RGPD, TFUE, Carta...) o sin número ('la Directiva'), que no se puede comprobar. Su 'CE' no es la
# Constitución.
_MARCA_UE = r"(?:\((?:ue|ce|cee)(?:, euratom)?\)|ue|ce|cee)"
_NUM_UE = r"(?: n\.? ?[oº°]\.?)? ?[0-9]{2,4}/[0-9]{1,4}(?:/(?:ue|ce|cee|euratom))?\b"
# Primero las siglas y nombres de normas_ue ('Roma I', 'Directiva de morosidad'...; no 'carta', palabra corriente),
# para que 'directiva' sola no se quede con 'Directiva de morosidad'.
_SIGLAS_UE = "|".join(re.escape(s) for s in sorted(normas_ue.SIGLAS, key=len, reverse=True) if s != "carta")
_UE = re.compile(rf"\b(?:(?:{_SIGLAS_UE})\b|directiva(?: de ejecucion| delegada)?(?: {_MARCA_UE})?{_NUM_UE}|(?:reglamento|decision)"
                 rf"(?: de ejecucion| delegad[oa])? {_MARCA_UE}{_NUM_UE}|decision [0-9]{{2,4}}/[0-9]{{1,4}}/(?:ue|ce|cee)\b|"
                 r"directiva\b|reglamento \((?:ue|ce|cee)\)|"
                 r"reglamento (?:ue|ce|cee) )")
_NOMBRES = sorted(boe.NOMBRES, key=len, reverse=True)

# Números en letra -> cifra, para comparar '20 días' del escrito con 'veinte días' del artículo.
_UNIDADES = {"un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
             "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16,
             "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiun": 21, "veintiuno": 21,
             "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
             "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30, "cuarenta": 40, "cincuenta": 50,
             "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100, "doscientos": 200,
             "trescientos": 300, "cuatrocientos": 400, "quinientos": 500, "seiscientos": 600, "setecientos": 700,
             "ochocientos": 800, "novecientos": 900, "mil": 1000}
_PALABRA = "|".join(sorted(_UNIDADES, key=len, reverse=True))
_EN_LETRA = re.compile(rf"\b(?:{_PALABRA})(?:(?: y | )(?:{_PALABRA}))*\b")
# Una cifra con su unidad, sobre el texto original sin tildes (misma longitud que el original): su posición dice a
# qué cita pertenece.
_CIFRA_POS = re.compile(rf"\b(?:(?:{_PALABRA})(?:(?: y | )(?:{_PALABRA})){{0,6}}|[0-9]{{1,3}}(?:\.[0-9]{{3}})+|"
                        r"[0-9]{1,4}(?:,[0-9]{1,3})?) ?(?:anos?|mes(?:es)?|semanas?|horas?|dias(?: habiles| naturales)?|por ciento|por 100|%|euros?"
                        r"|€)")  # {0,6}: lineal


def _llano(texto: str) -> str:
    """Sin tildes, en minúsculas, '%' como 'por ciento' y los números en letra como cifras."""
    t = " ".join(boe._sin_acentos(texto).lower().replace("%", " por ciento").replace("€", " euros").split())
    t = re.sub(r"(?<=[0-9])\.(?=[0-9]{3}(?![0-9]))", "", t)  # '120.000' -> '120000'
    t = re.sub(r"\beuro\b", "euros", t)
    return _EN_LETRA.sub(lambda m: str(_valor(m.group(0))), t)


def _valor(palabras: str) -> int:
    """'ciento veinte mil' -> 120000; 'treinta y siete' -> 37."""
    total = actual = 0
    for p in palabras.split():
        if p == "mil":
            total, actual = total + (actual or 1) * 1000, 0
        elif p in _UNIDADES:
            actual += _UNIDADES[p]
    return total + actual


def _numeros(texto: str, desde: int) -> tuple[list[str], int]:
    """Los artículos citados a partir de 'desde' ('14 y 15' -> ['14', '15']) y dónde acaba la cita."""
    actuales, numeros, pos = [], [], desde
    for palabra in texto[desde:desde + 60].split(" "):
        if palabra in ("y", "e") and actuales:  # 'artículos 14 y 15'
            numeros.append(" ".join(actuales))
            actuales = []
        elif not _PIEZA.fullmatch(palabra):  # 'del', 'CC', 'de la LGT'...: acaba el número
            break
        else:
            if palabra[0].isdigit() and actuales and actuales[-1].endswith(","):  # 'artículos 14, 15'
                numeros.append(" ".join(actuales))
                actuales = []
            actuales.append(palabra)
        pos += len(palabra) + 1
    if actuales:
        numeros.append(" ".join(actuales))
    return [n.strip(" ,") for n in numeros if n.strip(" ,")], pos


def _ley_cerca(texto: str, ini: int, fin: int) -> tuple[str, str] | None:
    """La ley de una cita: la referencia más próxima DETRÁS del número, sin pasar del final de la frase; si no hay,
    la más próxima DELANTE dentro de la misma frase ('el Código Civil, en su artículo 1902'). Devuelve (id BOE o
    'Ley 58/2003', cómo aparece), ('UE', ...) si es una norma de la UE, o None si no hay ninguna clara."""
    detras = texto[fin:fin + 140]
    corte = re.search(r"[;:]|\.\s|\.$|\)\.", detras)
    detras = detras[:corte.start()] if corte else detras
    siguiente = re.search(r"\bart(?:[ií]culos?|s?\.)\s*[0-9]", detras)  # la ley de la cita siguiente no es la suya
    detras = detras[:siguiente.start()] if siguiente else detras
    delante = texto[max(0, ini - 90):ini]
    delante = delante[max(delante.rfind(". "), delante.rfind(".\n"), delante.rfind(";"), delante.rfind(":")) + 1:]
    for trozo, mas_cerca in ((detras, min), (delante, max)):
        llano = boe._sin_acentos(trozo).lower()
        ue = [(m.start(), m.end()) for m in _UE.finditer(llano)]
        candidatos = [(a, "UE", trozo[a:b].strip(), b) for a, b in ue]  # (inicio, ley, cómo aparece, fin)
        for nombre in _NOMBRES:
            i = llano.find(nombre)
            if i >= 0:
                candidatos.append((i, boe.LEYES[boe.NOMBRES[nombre]], trozo[i:i + len(nombre)], i + len(nombre)))
        for m in re.finditer(r"\b([A-Z][A-Za-z]{1,7})\b", trozo):  # siglas en mayúscula, como se citan: LGT, ET, CC
            sigla = m.group(1)
            if sigla.lower() in boe.LEYES and sigla != sigla.lower() and trozo[max(0, m.start() - 1):m.start()] != "/":
                candidatos.append((m.start(), boe.LEYES[sigla.lower()], sigla, m.end()))  # no la 'CE' de '2006/112/CE'
        for m in _NUMERO_LEY.finditer(trozo):
            resto = trozo[m.end():m.end() + 160]
            resto = boe._sin_acentos(resto[:min((i for i in (resto.find(";"), resto.find(". "), resto.find("(")) if i >= 0),
                                                default=len(resto))]).lower()
            fecha = _FECHA_LEY.match(resto)
            if _AUTONOMICA.search(resto):  # 'Ley 7/2021, ..., de Andalucía': no es la estatal del mismo número
                candidatos.append((m.start(), "AUTONOMICA", m.group(0), m.end()))
            else:
                candidatos.append((m.start(), f"{m.group(1)} {m.group(2)}", m.group(0) + (fecha.group(0) if fecha else ""),
                                   m.end()))
        # 'redacción dada por la Ley X' no es la ley de la cita sino su reforma: no cuenta.
        candidatos = [c for c in candidatos
                      if not re.search(r"redacci[oó]n[^.;]{0,30}$", boe._sin_acentos(trozo[:c[0]]).lower())
                      and (c[1] == "UE" or not any(a <= c[0] < b for a, b in ue))]  # el 'CE' de 'Reglamento (CE)'
        # En la duda, None ("no comprobada"): una cita de otra norma dada por "existe y está vigente" es lo peor que puede pasar.
        if trozo is detras:
            # Detrás solo vale la ley pegada al número ('art. 66 LGT', 'del Código Civil', ', apartado 2, de la LIVA').
            # 'del V Convenio...', 'de los Estatutos...', 'de la citada Ordenanza...': la cita nombra su propia norma.
            enlace = _ENLACE.match(llano)
            pegados = [c for c in candidatos if c[0] <= enlace.end()]
            if not pegados:
                if enlace.group("de"):
                    return None
                continue  # 'el artículo 5 establece...': se mira delante
            elegido = min(pegados, key=lambda c: c[0])
        elif candidatos:
            elegido = max(candidatos, key=lambda c: c[0])
            if _NORMA_ENTRE.search(llano[elegido[3]:]):  # 'Tanto la LGT como la Ordenanza 3, en su artículo 5'
                return None
        else:
            continue
        if _REGION.match(llano[elegido[3]:elegido[3] + 60]):  # 'Código Civil de Cataluña', 'LIS del País Vasco'
            return None
        return elegido[1], elegido[2]
    return None


# La cita que remite a la ley de la anterior: 'del mismo texto legal', 'de la misma ley', 'del citado texto', 'ibídem'.
_MISMA = re.compile(r"\s*,?\s*(?:(?:apartados?|parrafos?|letras?|numeros?)\s+[^\s,]{1,12}\s*,?\s*){0,2}(?:(?:de la|del|de)\s+"
                    r"(?:mism[oa]|citad[oa]|referid[oa]|precitad[oa]|antedich[oa])\s+(?:texto(?: legal| refundido)?|ley|"
                    r"norma|cuerpo legal|codigo|real decreto(?: legislativo)?|estatuto|reglamento)\b|\(?\s*(?:ibidem|ibid\.|id\.)"
                    r"(?![a-z]))")


# Lo que puede ir entre el número y su ley: 'artículo 20, apartado uno, de la citada Ley...', 'del Reglamento Roma I'.
_ENLACE = re.compile(r"\s*,?\s*(?:(?:apartados?|parrafos?|letras?|numeros?|reglas?|incisos?|puntos?)\s+[^\s,]{1,12}"
                     r"\s*,?\s*){0,3}(?P<de>(?:de la|de los|de las|del|de)\s+)?"
                     r"(?:(?:citad[oa]|referid[oa]|mencionad[oa]|vigente)\s+)?(?:(?:reglamento|directiva|ley|codigo)\s+)?")
_REGION = re.compile(r"\s*,?\s*(?:foral\b|catalan|vasc[oa]\b|(?:de |del |de la |de les )?(?:andalucia|aragon|asturias|"
                     r"illes balears|baleares|canarias|cantabria|castilla[- ]la mancha|castilla y leon|cataluna|catalunya|"
                     r"comunitat valenciana|comunidad valenciana|extremadura|galicia|comunidad de madrid|region de murcia|"
                     r"navarra|pais vasco|euskadi|la rioja|bizkaia|gipuzkoa|alava|araba)\b)")
_NORMA_ENTRE = re.compile(r"\b(?:convenio|ordenanza|decreto|norma|pliego|estatutos?|contrato|anexo|reglamento|orden|acuerdo|"
                          r"resolucion|circular|instruccion|ley|codigo|tratado|directiva|decision)\b")


# Abreviaturas cuyo punto no acaba la frase ('el art. 66 LGT fija...').
_ABREVIATURAS = {"art", "arts", "núm", "num", "apdo", "apdos", "ap", "aptdo", "pág", "pag", "págs", "párr", "parr",
                 "ss", "cfr", "vid", "sr", "sra", "d", "dña", "etc", "disp", "adic", "trans", "fj", "rd", "rdl", "lo",
                 "l", "s", "sts", "stc", "stsj", "ctra", "avda"}


def _cortes(texto: str, a: int, b: int) -> list[int]:
    """Posiciones de fin de frase entre a y b: '. ' que no sigue a una abreviatura, o un salto de línea."""
    cortes = []
    for m in re.finditer(r"\. |\n", texto[a:b]):
        i = a + m.start()
        if m.group(0) == ". ":
            palabra = re.search(r"(?<![^\W\d_])([^\W\d_]{1,5})$", texto[max(a, i - 6):i])
            if palabra and palabra.group(1).lower() in _ABREVIATURAS:
                continue
        cortes.append(i)
    return cortes


_FECHAS_COMPROBADAS: dict[tuple, str | None] = {}


def _fecha_distinta(ref: str, como: str) -> str | None:
    """Si la cita trae fecha ('Ley 2/2006, de 30 de junio') y la norma estatal con ese número es de otra fecha, es que
    se cita otra (autonómica, casi siempre): se dice en vez de comprobar la que no es."""
    fecha = _FECHA_LEY.search(boe._sin_acentos(como).lower())
    if not fecha or not re.match(r"(ley|real|lo|rd)", ref.lower()):
        return None
    clave = (ref, fecha.group(0))
    if clave not in _FECHAS_COMPROBADAS:
        try:
            exactas = [r for r in boe.buscar_legislacion(ref, solo_vigente=False, max_resultados=5,
                                                          comprobar_derogadas=False, ampliar=False)["resultados"] if r.get("exacta")]
        except (ValueError, FuenteError):
            exactas = []
        dia_mes = fecha.group(0).lstrip(", ").replace("de ", "", 1).strip()  # '30 de junio'
        _FECHAS_COMPROBADAS[clave] = None if not exactas or any(
            f"de {dia_mes}" in boe._sin_acentos(r["titulo"]).lower() for r in exactas) else (
            f"la {ref} estatal no es de esa fecha ({fecha.group(0).lstrip(', ')}): la cita es de otra norma "
            "(probablemente autonómica). Búscala con buscar_ley(ambito='autonomica') y compruébala con su id BOE")
    return _FECHAS_COMPROBADAS[clave]


def _frase(texto: str, ini: int, fin: int) -> tuple[int, int]:
    """Inicio y fin de la frase de la cita, buscando los límites solo en una ventana (sin recorrer el texto entero en
    cada cita). Un punto dentro de un número ('1.968', '52.c)') o tras una abreviatura ('art. ') no corta."""
    a0 = max(0, ini - 500)
    antes = _cortes(texto, a0, ini)
    a = antes[-1] + 1 if antes else a0
    despues = _cortes(texto, fin, min(len(texto), fin + 500))
    b = despues[0] if despues else min(len(texto), fin + 500)
    return a, b + 1


def verificar_escrito(texto: str) -> dict:
    if not texto or len(texto.strip()) < 20:
        raise ValueError("Pega el texto del escrito (o el fragmento con las citas).")
    avisos = []
    if BASICO:
        avisos.append("Versión light: solo se comprueban leyes del BOE y de la UE. Las citas de doctrina y jurisprudencia "
                      "van a 'no comprobadas'; el TC no se consulta.")
    if len(texto) > 200_000:
        avisos.append(f"El escrito tiene {len(texto)} caracteres: solo se revisan los 200.000 primeros.")
        texto = texto[:200_000]
    llano = boe._sin_acentos(texto).lower()  # misma longitud que el original: las posiciones valen para los dos
    # Todas las citas en orden: (inicio, fin del número, [números], es_disposicion)
    citas_texto = [(m.start(), *_numeros(texto, m.end())[::-1], False) for m in _ART.finditer(texto)]
    citas_texto = [(i, f, n, d) for i, f, n, d in citas_texto if n]
    citas_texto += [(m.start(), m.end(), [texto[m.start():m.end()]], True) for m in _DISP.finditer(llano)]
    citas_texto += [(m.start(), m.end(), [m.group(0)], True) for m in _DISP_SIGLA.finditer(texto)]
    citas_texto.sort()
    inicios = [c[0] for c in citas_texto]
    # Cada cifra ('tres años', '20 días') es de la cita más cercana de su frase: así no se atribuye a un artículo lo
    # que el escrito dice de otro ('52 c) ET ... 20 días por año (art. 53 ET)': los 20 días son del 53).
    cifras_de: dict[int, list[tuple[str, str]]] = {}  # (como la escribe el escrito, en cifras)
    for m in _CIFRA_POS.finditer(llano):
        a, b = _frase(texto, m.start(), m.end())
        en_frase = [(c[0], c[1]) for c in citas_texto[bisect.bisect_left(inicios, a):bisect.bisect_left(inicios, b)]]
        detras = [i for i, _ in en_frase if m.end() <= i <= m.end() + 40 and "(" in texto[m.end():i]]
        antes = [i for i, f in en_frase if f <= m.start()]
        cerca = [(min(abs(m.start() - i), abs(m.start() - f)), i) for i, f in en_frase]
        dueno = detras[0] if detras else antes[-1] if antes else min(cerca)[1] if cerca else None
        if dueno is not None:
            cifras_de.setdefault(dueno, []).append((texto[m.start():m.end()], _llano(m.group(0))))
    citas, no_comprobadas, vistas, comprobadas = [], [], set(), 0
    pendientes, cifras_de_clave, ultima = [], {}, None
    for ini, fin, numeros, disposicion in citas_texto:
        ley = _ley_cerca(texto, ini, fin)
        if not ley and ultima and _MISMA.match(boe._sin_acentos(texto[fin:fin + 90]).lower()):
            ley = ultima  # 'artículo 55.1 del mismo texto legal': la ley de la cita anterior (examen L10, 5-nov)
        a, b = _frase(texto, ini, fin)
        frase = texto[a:b].strip()
        if not ley:
            no_comprobadas.append({"cita": frase[:160], "motivo": "no se identifica con seguridad a qué ley se refiere "
                                   "(cítala con su sigla o su nombre: 'art. 10 LGT', 'artículo 1902 del Código Civil')"})
            continue
        if ley[0] == "AUTONOMICA":
            no_comprobadas.append({"cita": frase[:160], "motivo": f"ley autonómica ({ley[1]}): no se compara con la estatal "
                                   "del mismo número. Búscala con buscar_ley(ambito='autonomica') y compruébala con "
                                   "articulo_vigente con su id BOE"})
            continue
        if ley[0] == "UE":
            try:
                ley = (f"UE:{normas_ue.resolver(ley[1])}", ley[1]) if not disposicion else None
            except (ValueError, FuenteError):
                ley = None
            if not ley:
                no_comprobadas.append({"cita": frase[:160], "motivo": "norma de la UE que no se identifica con seguridad "
                                       "(cítala por su número, 'Directiva 2006/112/CE', o su sigla: RGPD, TFUE...); "
                                       "compruébala con articulo_ue"})
                continue
        elif (otra_fecha := _fecha_distinta(*ley)):
            no_comprobadas.append({"cita": frase[:160], "motivo": otra_fecha})
            continue
        ultima = ley
        # Desde la cita hasta la siguiente cita o el final de su frase: ahí va SU 'redacción dada por' (en 'arts. 14 LGT
        # y 20 LIVA, en la redacción dada por...', la mención es del último).
        k = bisect.bisect_left(inicios, fin)  # la siguiente cita, sin recorrerlas todas (lineal)
        siguiente = inicios[k] if k < len(inicios) and inicios[k] < b else b
        tramo = texto[ini:siguiente]
        no_comprobadas += [{"cita": f"art. {n} {ley[1]}", "motivo": "solo se comprueban los 3 primeros artículos de "
                            "una misma cita ('arts. 14, 15, 16 y 17'): revisa este aparte"} for n in numeros[3:]]
        for numero in numeros[:3]:
            clave = (ley[0], numero.lower(), frase)
            if clave in vistas:  # la misma cita repetida en la frase: sus cifras van con la primera
                cifras_de_clave[clave] += cifras_de.get(ini, [])
                continue
            vistas.add(clave)
            cifras_de_clave[clave] = list(cifras_de.get(ini, []))
            if comprobadas >= _MAX_CITAS:
                no_comprobadas.append({"cita": f"art. {numero} {ley[1]}", "motivo": f"solo se comprueban las "
                                       f"{_MAX_CITAS} primeras citas de artículos y disposiciones"})
                continue
            comprobadas += 1
            pendientes.append((ley, numero, frase, tramo, disposicion, clave))
    citas += [(_comprobar_ue if ley[0].startswith("UE:") else _comprobar_articulo)(
        ley, numero, frase, tramo, disposicion, cifras_de_clave[clave])
        for ley, numero, frase, tramo, disposicion, clave in pendientes]
    for patron, leer in _OTRAS:
        refs = list(dict.fromkeys(m.group(m.lastindex or 0) for m in re.finditer(patron, texto)))
        if BASICO:  # se dice que no se comprueba, nunca se calla
            no_comprobadas += [{"cita": ref, "motivo": "doctrina o jurisprudencia: esta versión solo comprueba leyes del BOE "
                                "y de la UE; léela en su fuente oficial"} for ref in refs[:_MAX_OTRAS]]
            continue
        citas += [_otra(ref, leer) for ref in refs[:_MAX_OTRAS]]
        no_comprobadas += [{"cita": ref, "motivo": f"solo se comprueban {_MAX_OTRAS} de cada tipo"} for ref in refs[_MAX_OTRAS:]]
    # Jurisprudencia ordinaria por ECLI, ROJ ('STS 1234/2023', 'SAN', 'STSJ', 'SAP', 'ATS') o por tribunal y fecha
    # ('sentencia del Tribunal Supremo de 5 de mayo de 2021'): se dice que no se comprueba, nunca se calla.
    eclis = list(dict.fromkeys(
        [m.group(0) for m in re.finditer(r"ECLI:ES:(?!TC)[A-Z]{2,6}:[0-9]{4}:[0-9A-Z.]{1,12}", texto)]
        + [" ".join(m.group(0).split()) for m in re.finditer(
            r"\b(?:STS|SSTS|ATS|SAN|STSJ|SAP|SJ[A-Z]{1,3})\s{1,3}[0-9]{1,5}/[0-9]{4}\b|(?i:\b(?:sentencia|auto)s?\s{1,3}"
            r"(?:del?|de\s{1,3}la)\s{1,3}(?:tribunal\s{1,3}supremo|audiencia\s{1,3}(?:nacional|provincial)|tribunal"
            r"\s{1,3}superior\s{1,3}de\s{1,3}justicia|juzgado)[^.;\n]{0,60})", texto)]))
    no_comprobadas += [{"cita": e, "motivo": "jurisprudencia del CENDOJ: compruébala con la skill jurisprudencia-cendoj"}
                       for e in eclis[:10]]
    if len(eclis) > 10:
        no_comprobadas.append({"cita": "…", "motivo": f"y {len(eclis) - 10} ECLI más del CENDOJ"})
    total_no_comprobadas = len(no_comprobadas)
    fuera_por_tope = sum("primeras citas" in c["motivo"] or "3 primeros" in c["motivo"] or "de cada tipo" in c["motivo"]
                         for c in no_comprobadas)
    if total_no_comprobadas > 30:
        no_comprobadas = no_comprobadas[:30] + [{"cita": "…", "motivo": f"y {total_no_comprobadas - 30} más"}]
    n = Counter(c["resultado"] for c in citas)
    return {"resumen": f"{len(citas)} citas comprobadas: {n['error']} con error, {n['a revisar']} a revisar, "
                       f"{n['existe y está vigente']} existen y están vigentes, {n['existe']} existen (doctrina), "
                       f"{n['no comprobada']} sin poder comprobar; "
                       f"{fuera_por_tope} fuera por los topes ({_MAX_CITAS} artículos, 3 por cita, {_MAX_OTRAS} por tipo: divide el "
                       "escrito); "
                       f"{total_no_comprobadas - fuera_por_tope} "
                       "no comprobadas por su forma.",
            **({"avisos": avisos} if avisos else {}),
            "citas": citas, "no_comprobadas": no_comprobadas,
            "nota": "'existe y está vigente' significa que el artículo existe en esa ley, está vigente y contiene las cifras "
                    "que el escrito le atribuye; NO que diga lo que el escrito afirma de él (eso exige leerlo). En DGT, "
                    "TEAC, TC y TJUE, 'existe' solo dice que la resolución existe. "
                    "'error': lo que la fuente oficial contradice (no existe, derogada, otra reforma, o el TC anuló el "
                    "artículo o parte de él después de su redacción vigente: mira qué inciso). 'a revisar': lo "
                    "que exige leer el texto (cifras del escrito que no están en el artículo, versiones que aún no "
                    "rigen, una reforma que no se pudo identificar, una sentencia del TC anterior a la redacción vigente o una "
                    "cuestión admitida sobre el artículo). Lo no comprobado NO es un error ni un acierto."}


# Siglas que hoy resuelven a una ley distinta de la que nombraban antes (LMV: Ley 24/1988 -> Ley 6/2023; LOPD: LO
# 15/1999 -> LO 3/2018; LC: Ley 22/2003 -> TRLC 2020).
_SIGLAS_CAMBIADAS = {"lmv", "lopd", "lc"}


def _comprobar_articulo(ley: tuple[str, str], numero: str, frase: str, tramo: str, disposicion: bool,
                        cifras: list[tuple[str, str]]) -> dict:
    ref, como = ley
    r = {"cita": numero if disposicion else f"art. {numero} {como}", **({"ley_citada": como} if disposicion else {}),
         "frase": frase[:300]}
    try:
        a = boe.articulo(ref, numero, 100_000)
    except ValueError as e:
        if "ATENCIÓN" in str(e):  # existe, sin texto consolidado, y el BOE la da por derogada
            return {**r, "resultado": "error", "problemas": [str(e)]}
        return {**r, "resultado": "no comprobada", "problemas": [f"no se identifica la ley: {e}"]}
    except FuenteError as e:
        if "No encuentro" in str(e):
            if disposicion:  # las disposiciones se escriben de muchas formas: no se da por inexistente
                return {**r, "resultado": "a revisar", "problemas": ["No se localiza esa disposición en esa ley tal "
                                                                     "como está escrita: compruébala con indice_ley."]}
            return {**r, "resultado": "error", "problemas": [f"No existe el artículo {numero} en esa ley (o está "
                                                             "numerado de otra forma): revísalo."]}
        motivo = "tope de la consulta" if "peticiones" in str(e) or "tiempo total" in str(e) else "la fuente no respondió"
        return {**r, "resultado": "no comprobada", "problemas": [f"{motivo}: {e}"]}
    problemas = []  # (nivel, texto); el resultado es el nivel más grave
    for aviso in a["avisos"][1:]:
        if "derogad" in aviso.lower() or "sustituida" in aviso.lower():
            problemas.append((2, aviso))
        elif "aún no rigen" in aviso or "efectos en fechas" in aviso or "identificada por búsqueda" in aviso \
                or "No se pudo comprobar" in aviso:
            problemas.append((1, aviso))
    reforma = _REDACCION.search(tramo)
    if reforma:
        try:
            citada = boe.resolver_ley(reforma.group(1), consolidadas=False)[0]
        except (ValueError, FuenteError):
            citada = None
            problemas.append((1, f"No se pudo identificar «{reforma.group(1)}» en el BOE para comprobar si dio esta "
                                 "redacción: compruébalo."))
        if citada and citada not in a["normas_que_lo_han_modificado"] and boe.anio(citada) < boe.anio(a["id"]):
            # La reforma es anterior a la propia norma (p. ej. Ley 3/2012 y el ET de 2015, texto refundido): reformó
            # la ley anterior y su contenido pasó al texto actual, que hoy se cita por sí mismo.
            problemas.append((1, f"«{reforma.group(1)}» ({citada}) es anterior a esta norma ({a['id']}): reformó la ley "
                                 f"anterior; hoy el artículo se cita por la norma vigente, cuya redacción actual dio "
                                 f"{a['norma_de_esta_version']}. Revisa la mención."))
        elif citada and citada not in a["normas_que_lo_han_modificado"]:
            problemas.append((2, f"El escrito atribuye la redacción a «{reforma.group(1)}» ({citada}), que no figura "
                                 f"entre las normas que han dado redacción a este artículo; la vigente la dio "
                                 f"{a['norma_de_esta_version']}."))
        elif citada and citada != a["norma_de_esta_version"]:
            problemas.append((1, f"«{reforma.group(1)}» sí modificó este artículo, pero la redacción vigente la dio "
                                 f"después {a['norma_de_esta_version']}."))
    if re.sub(r"[^a-z]", "", como.lower()) in _SIGLAS_CAMBIADAS:  # la sigla nombró antes a otra ley
        problemas.append((1, f"La sigla {como} se ha tomado como la ley vigente ({a['id']}); si el escrito se refiere a "
                             "la anterior que se citaba igual, cítala por su número y año."))
    problemas += _cifras_ausentes(cifras, a["texto"])
    if not BASICO:
        problemas += relaciones.avisos_tc(a["id"], a["titulo"], a["version_vigente_desde"])  # sentencias del TC sobre él
    resultado = ("existe y está vigente", "a revisar", "error")[max((n for n, _ in problemas), default=0)]
    return {**r, "resultado": resultado, "problemas": [t for _, t in problemas], "articulo": a["titulo"], "ley": a["id"],
            "vigente_desde": a["version_vigente_desde"], "redaccion_vigente_dada_por": a["norma_de_esta_version"],
            "extracto": a["texto"][:500], "fuente": a["fuente"]}


def _cifras_ausentes(cifras: list[tuple[str, str]], texto_: str) -> list[tuple[int, str]]:
    texto_art = _llano(texto_)
    return [(1, f"El escrito dice «{c}» y el texto vigente del artículo no lo contiene: comprueba la cifra.")
            for c, llana in dict.fromkeys(cifras)
            if not re.search(rf"(?<![0-9]){re.escape(re.sub(r' (habiles|naturales)$', '', llana))}(?![0-9])",
                             texto_art)]  # '8 meses' no vale por '18 meses'


def _comprobar_ue(ley: tuple[str, str], numero: str, frase: str, tramo: str, disposicion: bool,
                  cifras: list[tuple[str, str]]) -> dict:
    """Artículo de una norma de la UE: que exista en la versión consolidada que rige hoy, que la norma siga en vigor y
    que estén las cifras. La 'redacción dada por' no se comprueba en la UE."""
    celex, como = ley[0][3:], ley[1]
    r = {"cita": f"art. {numero} {como}", "frase": frase[:300]}
    try:
        a = normas_ue.articulo_ue(celex, numero, 100_000)
    except ValueError as e:
        return {**r, "resultado": "no comprobada", "problemas": [f"no se identifica el artículo: {e}"]}
    except FuenteError as e:
        if "no vigente desde" in str(e):  # derogada: no es que el artículo no exista
            return {**r, "resultado": "error", "problemas": [str(e)]}
        if "No encuentro" in str(e):
            return {**r, "resultado": "error", "problemas": [f"No existe el artículo {numero} en la versión vigente de "
                                                             f"{como} ({celex}), o está numerado de otra forma: revísalo."]}
        motivo = "tope de la consulta" if "peticiones" in str(e) or "tiempo total" in str(e) else "la fuente no respondió"
        return {**r, "resultado": "no comprobada", "problemas": [f"{motivo}: {e}"]}
    problemas = [(2 if "no vigente" in x or "suprimido" in x else 0 if x.startswith("No hay versión") else 1, x)
                 for x in a["avisos"]
                 if x.startswith(("ATENCIÓN", "No hay versión consolidada"))]
    # El DOUE escribe '2 000 000 EUR': como el escrito ('2.000.000 euros') para comparar.
    texto_ = re.sub(r"\bEUR\b", "euros", re.sub(r"(?<=[0-9]) (?=[0-9]{3}(?![0-9]))", "", a["texto"]))
    problemas += _cifras_ausentes(cifras, texto_)
    resultado = ("existe y está vigente", "a revisar", "error")[max((n for n, _ in problemas), default=0)]
    return {**r, "resultado": resultado, "problemas": [t for _, t in problemas], "articulo": a["articulo"],
            "ley": a["norma"], "version_consolidada": a["version"], "vigente_desde": a["version_de"],
            "extracto": a["texto"][:500], "fuente": a["fuente"]}


def _otra(cita: str, leer) -> dict:
    try:
        return {"cita": cita, **leer(cita)}
    except ValueError as e:
        return {"cita": cita, "resultado": "no comprobada", "problemas": [str(e)]}
    except FuenteError as e:
        texto_ = str(e)
        if "La DGT no tiene" in texto_:
            return {"cita": cita, "resultado": "error", "problemas": [texto_]}
        if "TEAC no tiene" in texto_:  # DYCTEA solo recoge las resoluciones que fijan criterio
            return {"cita": cita, "resultado": "no comprobada", "problemas": [
                "No está en la base de doctrina del TEAC (DYCTEA), que solo recoge las resoluciones que fijan "
                "criterio: puede existir igualmente; compruébala por otra vía."]}
        return {"cita": cita, "resultado": "no comprobada", "problemas": [f"la fuente no respondió: {texto_}"]}


def _encontrada(d: dict, *campos: str) -> dict:
    return {"resultado": "existe", "problemas": [], **{c: str(d.get(c) or "")[:300] for c in campos}}


def _tjue(cita: str) -> dict:
    """'asunto C-311/19' o 'ECLI:EU:C:2020:981': debe constar en el repositorio de la UE (con versión en español)."""
    r = tjue.buscar_tjue(asunto=re.sub(r"(?i)^asuntos? ", "", cita), tipo="todos")["resultados"]
    if not r and not cita.upper().startswith("ECLI"):
        r = tjue.acumulado(re.sub(r"(?i)^asuntos? ", "", cita))
    if not r:
        return {"resultado": "a revisar", "problemas": [f"No consta {cita} en el repositorio de la UE con versión en "
                                                        "español: comprueba el número del asunto."]}
    # La sentencia antes que el auto (de rectificación, por ejemplo) y que las conclusiones del mismo asunto.
    return _encontrada(min(r, key=lambda x: "JOC".index(x["celex"][6])), "titulo", "fuente")


def _stc(cita: str) -> dict:
    """'STC 137/2025' o 'ECLI:ES:TC:2025:137': debe existir y ser del tipo citado (sentencia o auto)."""
    r = tc.buscar_tc(numero=cita)["resultados"]
    auto = cita.upper().startswith("ATC") or cita.upper().endswith("A")
    tipo = "AUTO" if auto else "SENTENCIA"
    del_tipo = [x for x in r if tipo in (x.get("titulo") or "").upper()]
    if not del_tipo:
        otro = f" (con ese número hay: {r[0]['titulo'][:80]})" if r else ""
        return {"resultado": "error", "problemas": [f"El TC no tiene {'el auto' if auto else 'la sentencia'} {cita}{otro}."]}
    return _encontrada(del_tipo[0], "titulo", "fuente")


# Otras citas que se comprueban: patrón (el último grupo, si lo hay, es la referencia) -> cómo se lee.
_OTRAS = ((r"\bV[0-9]{4}-[0-9]{2}\b", lambda n: _encontrada(hacienda.leer_consulta_dgt(n, 500), "fecha", "cuestion", "fuente")),
          (r"\bconsulta(?:s)?(?: general(?:es)?)?(?: de la DGT)?(?: n\.?º)? ([0-9]{4}-[0-9]{2})\b",
           lambda n: _encontrada(hacienda.leer_consulta_dgt(n, 500), "fecha", "cuestion", "fuente")),
          (r"\b[0-9]{2}/[0-9]{5}/[0-9]{4}\b", lambda rg: _encontrada(hacienda.leer_criterio_teac(rg, 500), "fecha", "asunto", "fuente")),
          (r"\b[SA]TC\s+[0-9]{1,4}/[0-9]{4}\b|\bECLI:ES:TC:[0-9]{4}:[0-9]{1,5}A?\b", _stc),
          (r"\b(?:asuntos? )?[CT][-\u2011\u2013][0-9]{1,4}/[0-9]{2}\b|\bECLI:EU:[CT]:[0-9]{4}:[0-9]{1,6}\b", lambda c: _tjue(c)))
