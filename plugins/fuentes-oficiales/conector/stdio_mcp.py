# Fuentes oficiales (versión abierta) 0.3.1. Hecho por Jurium. Licencia MIT (LICENSE).
"""Servidor MCP por stdio con la librería estándar (nació de Falso-CRM/mcp_server/stdio_mcp.py, hoy con cancelación,
ejecutor aparte y tope de línea;
código nuestro). Por qué sin el SDK `mcp`: cero código de terceros (regla del proyecto) y arranque
en ~1 s. Cubre tools con parámetros str/int/float/bool/dict/list (opcionalmente `| None`)."""
from __future__ import annotations

import inspect
import json
import queue
import sys
import threading

_TIPOS = {"str": "string", "int": "integer", "float": "number", "bool": "boolean",
          "dict": "object", "list": "array"}


def _tipo(anot) -> str | None:
    """'dict | None' -> 'object'. Las anotaciones llegan como texto (from __future__ import annotations)."""
    nombre = anot if isinstance(anot, str) else getattr(anot, "__name__", "")
    base = [t.strip() for t in nombre.split("|") if t.strip() != "None"]
    return _TIPOS.get(base[0].split("[")[0]) if base else None


def _coaccionar(valor, tipo):
    """Lo que hacía pydantic en el SDK: acepta '25', 'true' o un dict como texto JSON, y rechaza con un
    mensaje claro lo que no encaja con el tipo (un texto que llega como lista, un número infinito...)."""
    if tipo == "string":
        if not isinstance(valor, str):
            raise TypeError(f"se esperaba texto y llegó {type(valor).__name__}")
        return valor
    if tipo in ("integer", "number"):
        try:
            n = int(valor) if tipo == "integer" else float(valor)
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f"se esperaba un número y llegó {str(valor)[:40]!r}") from None
        if tipo == "number" and n != n or abs(n) == float("inf"):
            raise ValueError("se esperaba un número finito")
        return n
    if not isinstance(valor, str) or tipo is None:
        return valor
    if tipo == "boolean":
        return valor.strip().lower() in ("true", "1", "yes", "si", "sí")
    return json.loads(valor)  # object / array


class FastMCP:
    def __init__(self, name: str, instructions: str = "", errores_esperados: tuple = (), al_llamar=None,
                 al_devolver=None, version: str = "0.1"):
        self.name, self.instructions, self.tools, self.anotaciones = name, instructions, {}, {}
        self.version = version
        # Errores cuyo mensaje ya es para el usuario: se devuelven tal cual, sin el nombre técnico.
        self.esperados = (ValueError, TypeError, *errores_esperados)
        self.al_llamar = al_llamar  # al_llamar(nombre, args), antes de cada tool (plazo, filtros)
        self.al_devolver = al_devolver  # transforma cada resultado antes de enviarlo (p. ej. acotarlo)
        self.cancelados, self.en_curso = set(), None
        self.ejecutor = None  # si se fija, ejecuta cada tools/call en otro sitio (un proceso aparte) y da su resultado

    def tool(self, solo_lectura: bool = True, red: bool = True, destructiva: bool = False):
        def registrar(f):
            params = {p.name: p for p in inspect.signature(f).parameters.values()}
            props = {}
            for n, p in params.items():
                props[n] = {}
                if (t := _tipo(p.annotation)):
                    props[n]["type"] = t
                if p.default is not inspect.Parameter.empty:
                    props[n]["default"] = p.default
            schema = {"type": "object", "properties": props,
                      "required": [n for n, p in params.items() if p.default is inspect.Parameter.empty]}
            self.tools[f.__name__] = (f, schema)
            self.anotaciones[f.__name__] = {"readOnlyHint": solo_lectura, "openWorldHint": red,
                                            **({"destructiveHint": True} if destructiva else {})}
            return f
        return registrar

    def _llamar(self, nombre, args):
        f, schema = self.tools[nombre]
        props = schema["properties"]
        if not isinstance(args or {}, dict):
            raise TypeError("Los argumentos deben ser un objeto JSON.")
        # Un null se trata como "no lo indico": vale el valor por defecto (o falta, si es obligatorio).
        args = {k: _coaccionar(v, props[k].get("type")) for k, v in (args or {}).items() if k in props and v is not None}
        if (faltan := [k for k in schema["required"] if k not in args]):
            raise TypeError(f"Faltan argumentos obligatorios: {', '.join(faltan)}")
        if self.al_llamar:
            self.al_llamar(nombre, args)
        out = f(**args)
        if self.al_devolver:
            out = self.al_devolver(out)
        # JSON compacto (sin sangría): el mismo contenido en un tercio menos de contexto de Claude
        return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=str)

    def _responder(self, msg):
        m, params = msg.get("method"), msg.get("params") or {}
        if not isinstance(params, dict):
            raise LookupError(-32602, "params debe ser un objeto JSON")
        if m == "initialize":
            return {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": self.name, "version": self.version},
                    "instructions": self.instructions}
        if m == "ping":
            return {}
        if m == "tools/list":
            return {"tools": [{"name": n, "description": inspect.cleandoc(f.__doc__ or ""), "inputSchema": s,
                               "annotations": self.anotaciones[n]}
                              for n, (f, s) in self.tools.items()]}
        vacios = {"prompts/list": "prompts", "resources/list": "resources",
                  "resources/templates/list": "resourceTemplates"}
        if m in vacios:  # el cliente los pide al conectar; no exponemos ninguno
            return {vacios[m]: []}
        if m == "tools/call":
            if params.get("name") not in self.tools:
                raise LookupError(-32602, f"Tool desconocida: {str(params.get('name'))[:60]}")
            if self.ejecutor:
                return self.ejecutor(params)
            try:
                texto, error = self._llamar(params["name"], params.get("arguments")), False
            except Exception as e:  # el fallo de una tool vuelve a Claude; el servidor sigue vivo
                # Un error inesperado puede llevar en su texto lo que vino de la fuente (o una ruta): solo su tipo.
                detalle = e if isinstance(e, self.esperados) else f"error interno ({type(e).__name__})"
                texto, error = f"No se pudo ({params['name']}): {detalle}", True
                if self.al_devolver:  # el mensaje puede traer texto de la fuente: mismo tratamiento que un resultado
                    texto = self.al_devolver(texto)
            return {"content": [{"type": "text", "text": texto}], "isError": error}
        raise LookupError(-32601, f"Método no soportado: {m}")

    MAX_LINEA = 32_000_000  # bytes por mensaje: una línea enorme no se lee entera en memoria

    def cancelada(self) -> bool:
        """Si Claude Code ha cancelado la llamada que se está atendiendo (notifications/cancelled)."""
        return self.en_curso is not None and self.en_curso in self.cancelados

    def _leer_entrada(self, cola) -> None:
        """Lee la entrada en un hilo aparte: así una cancelación llega aunque haya una llamada en curso."""
        entrada = sys.stdin.buffer
        while (linea := entrada.readline(self.MAX_LINEA)):
            if len(linea) >= self.MAX_LINEA and not linea.endswith(b"\n"):
                while (resto := entrada.readline(self.MAX_LINEA)) and not resto.endswith(b"\n"):
                    pass  # se descarta hasta el final de la línea
                cola.put("{\n")  # se responde 'JSON no válido'
                continue
            texto = linea.decode("utf-8", "replace")  # bytes inválidos no tumban el servidor
            if '"notifications/cancelled"' in texto and len(texto) < 10_000:  # una cancelación es un mensaje corto
                try:
                    msg = json.loads(texto)
                except Exception:
                    msg = None
                if isinstance(msg, dict) and msg.get("method") == "notifications/cancelled":  # solo si lo es de verdad
                    ident = (msg.get("params") or {}).get("requestId") if isinstance(msg.get("params"), dict) else None
                    if isinstance(ident, (str, int)):
                        if len(self.cancelados) >= 1_000:
                            self.cancelados.clear()
                        self.cancelados.add(ident)
                    continue
            cola.put(texto)  # cola con tope: si Claude Code manda mucho mientras una herramienta trabaja, se espera
        cola.put(None)

    def run(self):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        self.cancelados, self.en_curso = set(), None
        cola = queue.Queue(maxsize=4)
        threading.Thread(target=self._leer_entrada, args=(cola,), daemon=True).start()
        while (linea := cola.get()) is not None:
            try:
                msg = json.loads(linea)
            except Exception:  # JSON roto, anidado sin fin o con números enormes: se responde error, sin caer
                if linea.strip():
                    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                                 "error": {"code": -32700, "message": "JSON no válido"}}) + "\n")
                    sys.stdout.flush()
                continue
            if not isinstance(msg, dict) or "id" not in msg:  # notificaciones: no se responden
                continue
            ident = msg["id"]
            if isinstance(ident, bool) or not (isinstance(ident, str) or (isinstance(ident, (int, float))
                                                                        and ident == ident and abs(ident) != float("inf"))):
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                             "error": {"code": -32600, "message": "id no válido"}}) + "\n")
                sys.stdout.flush()
                continue
            try:
                self.en_curso = msg["id"]
                resp = {"jsonrpc": "2.0", "id": msg["id"], "result": self._responder(msg)}
                if isinstance(msg["id"], (str, int)):
                    self.cancelados.discard(msg["id"])
            except LookupError as e:
                resp = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": e.args[0], "message": e.args[1]}}
            except Exception as e:  # nada de lo que llegue por stdin puede tumbar el servidor
                resp = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": f"Error interno: {type(e).__name__}"}}
            try:  # ensure_ascii: un carácter Unicode inválido (\ud800) sale escapado y no rompe la escritura
                sys.stdout.write(json.dumps(resp, ensure_ascii=True, allow_nan=False, default=str) + "\n")
            except Exception:
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": "Error interno"}}) + "\n")
            sys.stdout.flush()
