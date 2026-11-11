# Fuentes oficiales (versión abierta) 0.3.0. Hecho por Jurium. Licencia MIT (LICENSE).
"""Hook UserPromptSubmit del plugin: si el mensaje trae una norma, una cita, un convenio o doctrina en juego, añade un
recordatorio corto para que Claude consulte el conector. Si no, no dice nada (cada consulta tarda de 5 a 60 s: no debe
saltar en cada mensaje). Nunca falla ni bloquea: ante cualquier problema, calla."""
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # con -I el directorio del script no entra solo
import perfil  # noqa: E402

# Palabras enteras (siglas incluidas: 'lis' no salta con 'lista') o principios de palabra ('derogad', 'catastr').
_CLAVES = re.compile(
    r"\b(?:(?:art(?:iculo)?s?\.? ?[0-9]+|leyes|ley|real decreto|rdl?|reglamento|codigo civil|codigo penal|"
    r"estatuto de los trabajadores|convenios?|tablas salariales|boe|borme|dgt|consultas? vinculantes?|teac|tear|"
    r"doctrina|jurisprudencia|sentencias?|tribunal supremo|ts|stc|tjue|directiva|ecli|roj|vigentes?|lgt|liva|lirpf|"
    r"lis|lgss|trlrhl|lsc|lec|lau|lph|lopd|rgpd|bdns|fiscalia|ordenanzas?|modelo [0-9]{3})\b|"
    r"derogad|catastr|subvenci)")


def recordatorio(prompt: str) -> str | None:
    llano = "".join(c for c in unicodedata.normalize("NFD", prompt[:20_000].lower()) if unicodedata.category(c) != "Mn")
    if not _CLAVES.search(llano):
        return None
    que = "una norma, un artículo, una cita o un dato catastral" if perfil.LIGHT else         "una norma, un artículo, una cita, un convenio o doctrina (DGT, TEAC, tribunales)"
    return (f"Recordatorio del conector fuentes-oficiales: si la respuesta depende de {que}, consúltalo con sus "
            "herramientas o skills y cita la fuente oficial; si no hace falta, no lo llames (cada consulta tarda de 5 a "
            "60 s). Sin datos personales de clientes en las consultas.")


if __name__ == "__main__":
    try:
        datos = json.loads(sys.stdin.buffer.read(200_000).decode("utf-8", "replace"))
        texto = recordatorio(str(datos.get("prompt", ""))) if isinstance(datos, dict) else None
        if texto:
            sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                                "additionalContext": texto}}))
    except Exception:
        pass
    sys.exit(0)
