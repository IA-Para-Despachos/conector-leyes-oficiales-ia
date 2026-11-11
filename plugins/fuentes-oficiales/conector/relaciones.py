# Fuentes oficiales (versión abierta) 0.3.1. Hecho por Jurium. Licencia MIT (LICENSE).
"""Grafo normativo del BOE: qué normas modifican, derogan, desarrollan o declaran inconstitucional una norma (y a
cuáles afecta ella), a partir del "análisis" de la API de datos abiertos; y, por artículo, qué norma dio cada versión
(el bloque del texto consolidado). El análisis se pide en XML: en JSON el BOE solo devuelve una materia de varias."""
from __future__ import annotations

import re
from datetime import date

import boe
from red import FuenteError, analizar_xml, corto, texto, tope

TIPOS = ("todas", "modificaciones", "derogaciones", "desarrollo", "jurisprudencia")
_ANALISIS: dict[str, dict] = {}  # caché de la sesión, solo con respuestas que llegaron bien
_MAX_REL = 2000  # relaciones por lado que se procesan (la LGT tiene unas 130 posteriores)


def _analisis(ident: str) -> dict:
    """{'materias', 'notas', 'anteriores', 'posteriores'} con cada relación como (código, palabra, id, texto)."""
    if ident in _ANALISIS:
        return _ANALISIS[ident]
    try:
        raiz = analizar_xml(texto(f"{boe.API}/legislacion-consolidada/id/{ident}/analisis",
                                  cabeceras={"Accept": "application/xml"}, timeout=20))
        consolidada = True
    except FuenteError as e:
        if e.codigo not in (400, 404):
            raise
        # Sin texto consolidado (leyes que solo modifican otras, sentencias): el análisis va en el XML del diario.
        try:
            raiz = analizar_xml(texto(f"{boe.WEB}/diario_boe/xml.php?id={ident}", timeout=20))
        except FuenteError as e2:
            if e2.codigo in (400, 404):
                raise FuenteError(f"{ident} no existe en el BOE.", e2.codigo) from None
            raise
        consolidada = False

    def lado(nombre: str) -> list[tuple]:
        filas = []
        for r in list(raiz.iter(nombre))[:_MAX_REL]:
            rel = r.find("relacion") if r.find("relacion") is not None else r.find("palabra")
            ident_r = (r.findtext("id_norma") or r.get("referencia") or "").strip()
            filas.append((((rel.get("codigo") if rel is not None else "") or "")[:6],
                          " ".join(("".join(rel.itertext()) if rel is not None else "").split())[:60],
                          ident_r if re.fullmatch(r"BOE-[A-Z]-[0-9]{4}-[0-9]{1,6}", ident_r) else "",
                          " ".join((r.findtext("texto") or "").split())[:1500]))
        return filas

    datos = {"materias": [" ".join("".join(m.itertext()).split())[:120] for m in raiz.iter("materia")][:100],
             "notas": [corto(" ".join("".join(n.itertext()).split()), 500) for n in raiz.iter("nota")][:30],
             "anteriores": lado("anterior"), "posteriores": lado("posterior"), "consolidada": consolidada}
    if len(_ANALISIS) > 50:  # hasta ~6 MB por norma: que una sesión larga no llene la memoria
        _ANALISIS.clear()
    _ANALISIS[ident] = datos
    return datos


def _llano(s: str) -> str:
    return " ".join(boe._sin_acentos(s).lower().split())


def _tipos(codigo: str, palabra: str, texto_: str) -> list[str]:
    r, t = _llano(palabra), _llano(texto_)
    judicial = codigo in ("470", "530", "552") or bool(re.search(r"\b(sentencia|auto|cuestion|recurso)\b", t)) \
        and ("declara" in r or "anula" in r or "interpreta" in r)
    tipos = []
    if "deroga" in r or "se deroga" in t or "anula" in r:
        tipos.append("derogaciones")
    if re.search(r"modifica|anade|suprime|sustituye|deja sin efecto|suspende|actualiza|amplia|prorroga|correc|corrige",
                 r) or re.search(r"\bse (modifica|anade|suprime|sustituye)\b", t):
        tipos.append("modificaciones")
    if not judicial and re.search(r"conformidad|desarrolla|se dicta|en relacion|interpreta|reglament", r):
        tipos.append("desarrollo")
    if judicial:
        tipos.append("jurisprudencia")
    return tipos


def _fecha(texto_: str) -> str | None:
    """Fecha de la norma relacionada según la cita del BOE: la última 'N/AAAA, de D de mes' o 'de D de mes de AAAA'."""
    hallados = re.findall(r"(?:[0-9]{1,5}/([0-9]{4}),? )?de ([0-9]{1,2}) de ([a-z]{4,10})(?: de ([0-9]{4}))?",
                          _llano(texto_))
    for anio, dia, mes, anio2 in reversed(hallados):
        if mes in boe._MESES and (anio2 or anio):
            try:
                return date(int(anio2 or anio), boe._MESES[mes], int(dia)).isoformat()
            except ValueError:
                return None
    return None


_RANGO = re.compile(r"(?:\bpor |: ?)(?=(?:el |la )?(?:Real Decreto|Decreto|Ley|Orden|Resoluci|Sentencia|Auto\b|"
                    r"Reglamento|Acuerdo|Instrucci|Circular|Texto refundido))", re.I)


def _cita(palabra: str, texto_: str) -> str | None:
    """Cómo cita el BOE la norma relacionada ('Ley 9/2025, de 3 de diciembre'): lo que va tras el último 'por'."""
    ultimo = None
    for ultimo in _RANGO.finditer(texto_):
        pass
    if ultimo:
        return texto_[ultimo.end():][:200].strip(" .,")
    numero = re.match(r"[0-9]{1,5}/[0-9]{4}", texto_)  # 'Cuestión' + '1254/2025, promovida...'
    return f"{palabra} {numero.group(0)}" if numero and palabra in ("Cuestión", "Recurso") else None


_INICIO = re.compile(r"\b(arts?\.?|articulos?|adicional(?:es)?|transitorias?|final(?:es)?|derogatorias?)\s+"
                     r"([0-9][0-9a-z.,()ºª ]{0,200}|unico[0-9a-z.,() ]{0,200}|[a-z][0-9a-z.,()ºª ]{0,200})")
_ITEM = re.compile(r"(unico|[0-9]{1,4})(?:\.? ?(bis|ter|quater|quinquies|sexies|septies)\b)?")
_ORDINALES_LARGOS = sorted(boe._ORDINALES, key=len, reverse=True)  # 'vigesima primera' antes que 'vigesima'
_AJENA = ("por el ", "por los ", "por la ", "por las ", "dada al ", "dado al ", "dada a la ", "dada a los ")


def _articulos(texto_: str, anio_propio: str | None) -> list[tuple[str, str]]:
    """Artículos y disposiciones que nombra el texto de una relación: [(clave, etiqueta)].
    'arts. 107.1 y 2.a) y 110.4' -> 107 y 110 (en una lista, un número menor que el anterior es un apartado).
    Con anio_propio (relaciones posteriores) se descartan los de otra norma: 'en la redacción dada por el art. 1.12
    de la Ley 7/2012'; en las anteriores los artículos son, justamente, los de la otra norma (anio_propio=None)."""
    t, salida, desde = _llano(texto_[:600]), [], 0  # lo que se muestra; una relación real cabe de sobra
    while (m := _INICIO.search(t, desde)) is not None and len(salida) < 60:
        desde = m.end()
        clase, propios = m.group(1), []
        disp = next((d for d in ("adicional", "transitoria", "final", "derogatoria") if clase.startswith(d)), None)
        anterior, pos = -1, m.start(2)
        for trozo in re.split(r"(,\s*|\s+y\s+|\s+e\s+)", m.group(2)):
            inicio, pos = pos, pos + len(trozo)
            if not trozo.strip() or re.fullmatch(r",\s*|\s+[ye]\s+", trozo):
                continue
            item = _ITEM.match(trozo)
            if disp:
                ordinal = next((o for o in _ORDINALES_LARGOS if trozo.startswith(o)), None)
                n = boe._ORDINALES.index(ordinal) + 1 if ordinal else (
                    int(item.group(1)) if item and item.group(1) != "unico" else None)
                fin_item = len(ordinal) if ordinal else item.end() if item else 0
                claves = [(f"disposicion {disp} {n}", f"disposición {disp} {n}")] if n and n > anterior else []
            elif item:
                rango = re.match(r"([0-9]{1,4}) a ([0-9]{1,4})\b", trozo)
                fin_item = rango.end() if rango else item.end()
                if rango and 0 < int(rango.group(2)) - int(rango.group(1)) <= 60:
                    n = int(rango.group(2))
                    claves = [(str(k), f"art. {k}") for k in range(int(rango.group(1)), n + 1)]
                else:
                    n = 0 if item.group(1) == "unico" else int(item.group(1))
                    base = f"{item.group(1)} {item.group(2) or ''}".strip()
                    nuevo = anterior < 0 or n > anterior or (n > 20 and re.match(r"[0-9]+\.[0-9]", trozo))
                    claves = [(base, f"art. {base}")] if nuevo else []
            else:
                n = None
            if n is None:  # se acaba la lista: lo que sigue puede ser otra mención ('y SE AÑADE el art. 48 bis')
                desde = inicio
                break
            cola = t[inicio + fin_item:inicio + fin_item + 160]
            ajena = re.match(r"[^ ,]{0,15},? (?:de la|del|de los) ", cola) and re.search(r"[0-9]{1,5}/([0-9]{4})", cola)
            if anio_propio and ajena and ajena.group(1) != anio_propio:
                propios = []  # la lista es de artículos de otra norma
                break
            propios += claves
            anterior = max(anterior, n)
        if not (anio_propio and t[max(0, m.start() - 12):m.start()].endswith(_AJENA)):
            salida += [(boe._norm_bloque(c), e) for c, e in propios[:60]]
    vistos = set()
    return [(c, e) for c, e in salida if not (c in vistos or vistos.add(c))][:60]


def _resultado(codigo: str, texto_: str) -> str | None:
    t = _llano(texto_)
    if codigo in ("530", "552"):
        return "admitida a trámite (pendiente según el BOE; puede estar ya resuelta)"
    for clave, nombre in (("inconstitucionalidad y nulidad", "inconstitucional y nulo"),
                          ("inconstitucionales y nulos", "inconstitucional y nulo"),
                          ("inconstitucional", "inconstitucional"), ("nulidad", "nulo"), ("nulo", "nulo"),
                          ("interpretacion conforme", "interpretación conforme"), ("interpret", "interpretación"),
                          ("desestim", "desestimado"), ("inadmisi", "inadmitido"), ("extincion", "extinguido"),
                          ("perdida", "sin objeto")):
        if clave in t:
            return nombre
    return None


_RELACIONES: dict[tuple, dict] = {}  # caché: una relación se calcula una vez aunque se pida por varias citas


def _relacion(fila: tuple, anio_propio: str) -> dict:
    clave = (fila, anio_propio)
    if clave not in _RELACIONES:
        if len(_RELACIONES) > 20_000:
            _RELACIONES.clear()
        _RELACIONES[clave] = _calcular_relacion(fila, anio_propio)
    return dict(_RELACIONES[clave], _claves=set(_RELACIONES[clave]["_claves"]))


def _calcular_relacion(fila: tuple, anio_propio: str) -> dict:
    codigo, palabra, ident, texto_ = fila
    tipos, arts = _tipos(codigo, palabra, texto_), _articulos(texto_, anio_propio)
    r = {"relacion": palabra, "tipos": tipos, "id": ident or None, "norma": _cita(palabra, texto_),
         "fecha": _fecha(texto_), "anio_boe": boe.anio(ident) if ident else None,
         "articulos": [e for _, e in arts], "texto": corto(texto_, 600),
         **({"url": f"{boe.WEB}/buscar/doc.php?id={ident}"} if ident else {})}
    if "jurisprudencia" in tipos:
        t = _llano(texto_)
        tc = codigo in ("470", "530", "552") and "supremo" not in t
        num = re.search(r"\b(sentencia|auto) ([0-9]{1,4}/[0-9]{4}|de [0-9]{1,2} de [a-z]{4,10} de [0-9]{4})", t)
        r |= {"tribunal": "Tribunal Supremo" if "supremo" in t else "Tribunal Constitucional" if tc else None,
              "resolucion": (("STC " if num.group(1) == "sentencia" else "ATC ") if tc else
                             num.group(1).capitalize() + " ") + num.group(2) if num else None,
              "resultado": _resultado(codigo, texto_)}
    r["_claves"] = {c for c, _ in arts}
    return r


def _versiones(ident: str, bloque: str) -> list[dict]:
    """Versiones del bloque: qué norma dio cada una, cuándo se publicó y desde cuándo rige, con la nota del BOE."""
    raiz = analizar_xml(texto(f"{boe.API}/legislacion-consolidada/id/{ident}/texto/bloque/{bloque}",
                              cabeceras={"Accept": "application/xml"}, timeout=20))
    salida = []
    for v in raiz.findall(".//version")[:200]:
        notas = [b for b in v.findall("blockquote") if (b.get("class") or "") != "soloTexto"]
        nota = " ".join("".join(notas[-1].itertext()).split()) if notas else ""
        salida.append({"norma": v.get("id_norma"), "publicada": _iso(v.get("fecha_publicacion")),
                       "rige_desde": _iso(v.get("fecha_vigencia")) or "sin fecha en el BOE",
                       **({"nota_del_boe": corto(nota, 400)} if nota else {}),
                       **({"original": True} if v.get("id_norma") == ident else {})})
    return sorted(salida, key=lambda x: x["publicada"] or "")


def _iso(f: str | None) -> str | None:
    return f"{f[:4]}-{f[4:6]}-{f[6:8]}" if f and re.fullmatch(r"[0-9]{8}", f) else None


def relaciones_norma(ley: str, articulo: str = "", tipo: str = "todas", max_resultados: int = 50) -> dict:
    tipo = _llano(tipo or "todas")
    if tipo not in TIPOS:
        raise ValueError(f"tipo debe ser uno de: {', '.join(TIPOS)}.")
    n = tope(max_resultados, 100)
    ident, resuelta = boe.resolver_ley(ley, consolidadas=False)
    datos = _analisis(ident)
    anio = boe.anio(ident)
    avisos = ["Relaciones según el análisis del BOE (informativo). 'fecha' es la de la norma relacionada tal como "
              "la cita el BOE (no la de publicación); si no consta, va 'anio_boe' (año de su id)."]
    if resuelta:
        avisos.append(f"Ley identificada por búsqueda: {resuelta[:200]}. Comprueba que es la que querías.")
    salida = {"id": ident, "fuente": f"{boe.WEB}/buscar/act.php?id={ident}" if datos["consolidada"] else
              f"{boe.WEB}/buscar/doc.php?id={ident}", "materias": datos["materias"], "notas": datos["notas"]}
    clave = None
    if (articulo or "").strip():
        try:
            a = boe.articulo(ident, articulo, 1)
            clave = boe._norm_bloque(a["titulo"] or "")
            salida["articulo"] = {"bloque": a["bloque"], "titulo": a["titulo"], "fuente": a["fuente"]}
            try:
                salida["versiones_del_articulo"] = _versiones(ident, a["bloque"])
            except FuenteError as e:
                avisos.append(f"No se pudieron leer las versiones del artículo ({e}).")
        except (FuenteError, ValueError) as e:
            m = re.match(r"(?:art[a-z]*\.? ?)?([0-9]{1,4}(?: ?(?:bis|ter|quater))?)", _llano(articulo))
            if not m or "peticiones" in str(e) or "tiempo total" in str(e):
                raise
            clave = boe._norm_bloque(m.group(1))
            avisos.append(f"No se localizó el bloque del artículo en el texto consolidado ({str(e)[:150]}): se "
                          "filtran las relaciones por el número, sin versiones del artículo.")

    dieron_version = {v["norma"] for v in salida.get("versiones_del_articulo", [])}

    def lista(filas: list[tuple], anio_: str | None) -> tuple[list[dict], list[dict], int]:
        rels = [_relacion(f, anio_) for f in filas]
        rels = [r for r in rels if tipo == "todas" or tipo in r["tipos"]]
        rels.sort(key=lambda r: r["fecha"] or r["anio_boe"] or "", reverse=True)
        sin_art = []
        if clave is not None:
            for r in rels:  # la norma dio una versión del artículo aunque el texto de la relación no lo nombre
                if r["id"] in dieron_version:
                    r["dio_redaccion_a_este_articulo"] = True
            sin_art = [r for r in rels if clave not in r["_claves"] and not r.get("dio_redaccion_a_este_articulo")
                       and (not r["_claves"] or "determinados preceptos" in _llano(r["texto"]))
                       and {"modificaciones", "derogaciones", "jurisprudencia"} & set(r["tipos"])]
            rels = [r for r in rels if clave in r["_claves"] or r.get("dio_redaccion_a_este_articulo")]
        total = len(rels)
        for r in rels + sin_art:
            r.pop("_claves", None)
        return rels[:n], sin_art[:21], total

    le_afectan, sin_post, total_post = lista(datos["posteriores"], anio)
    afecta_a, _, total_ant = lista(datos["anteriores"], None)
    salida |= {"tipo": tipo, "le_afectan": le_afectan, **({"afecta_a": afecta_a} if clave is None else {}),
               "totales": {"le_afectan": total_post, **({"afecta_a": total_ant} if clave is None else {})}}
    if clave is not None:
        avisos.append("Con artículo solo se filtra le_afectan (lo que afecta a este artículo); afecta_a no se da: pide "
                      "la norma sin artículo para ver lo que ella modifica.")
    if len(sin_post) > 20:
        avisos.append("no_dicen_a_que_articulo muestra 20: hay más relaciones sin artículo.")
        sin_post = sin_post[:20]
    if total_post > n or (clave is None and total_ant > n):
        avisos.append(f"Hay más relaciones de las que se muestran ({n} por lista, de la más reciente a la más "
                      "antigua): sube max_resultados (hasta 100) o filtra por tipo o artículo.")
    if clave is not None:
        salida["no_dicen_a_que_articulo"] = sin_post
        avisos.append("Filtrado por artículo: el BOE no da las relaciones por artículo, sino un texto ('SE MODIFICA "
                      "los arts. 74.5 y 103.2'); se leen de ahí, así que una mención redactada de forma rara puede "
                      "escaparse. 'no_dicen_a_que_articulo' son las que no nombran artículos ('determinados "
                      "preceptos') y pueden afectarle. 'versiones_del_articulo' es lo seguro: qué norma dio cada "
                      "redacción (incluidas las sentencias del TC que cambiaron el texto).")
        if not le_afectan and not sin_post:
            avisos.append("El análisis del BOE no nombra este artículo en ninguna relación del tipo pedido.")
    if not datos["consolidada"]:
        avisos.append("Norma sin texto consolidado: el análisis sale del diario del BOE.")
    salida["avisos"] = avisos
    return salida


def avisos_tc(ident: str, articulo_titulo: str, vigente_desde: str | None = None) -> list[tuple[int, str]]:
    """Para verificar_escrito: [(nivel, aviso)] si el TC (o el TS) declaró inconstitucional o nulo el artículo, o
    algún apartado o inciso, o hay una cuestión o recurso admitido sobre él. Nivel 2 si la sentencia es posterior a
    la redacción vigente (le afecta); 1 si es anterior (afectó a una redacción previa) o está pendiente."""
    try:
        datos = _analisis(ident)
    except FuenteError as e:
        return [(1, f"No se pudo comprobar en el BOE si el TC ha anulado este artículo ({str(e)[:120]}).")]
    clave, salida = boe._norm_bloque(articulo_titulo or ""), []
    vigente = (vigente_desde or "")[:8]
    for fila in datos["posteriores"]:
        r = _relacion(fila, boe.anio(ident))
        if "jurisprudencia" not in r["tipos"] or clave not in r["_claves"]:
            continue
        res, quien = r.get("resultado") or "", r.get("resolucion") or r["id"] or "resolución sin número"
        cuando = (r["fecha"] or "").replace("-", "")
        if res.startswith(("inconstitucional", "nulo")):
            posterior = not vigente or not cuando or cuando >= vigente
            salida.append((2 if posterior else 1, (
                ("ATENCIÓN: el " if posterior else "Afectó a una versión anterior a la vigente: el ") +
                f"{r.get('tribunal') or 'tribunal'} declaró {res} este artículo o parte de él ({quien}, "
                f"{r['id']}): «{r['texto'][:300]}». " + (
                    "Comprueba que el apartado o inciso que citas no es el anulado (leer_tc)." if posterior else
                    "Comprueba si el escrito aplica esa versión (hechos anteriores).")).strip()))
        elif res.startswith("admitida"):
            salida.append((1, f"Hay una cuestión o recurso de inconstitucionalidad admitido sobre este artículo "
                              f"({r['norma'] or r['id']}): «{r['texto'][:200]}». Puede estar ya resuelto: buscar_tc."))
    return salida[:10]
