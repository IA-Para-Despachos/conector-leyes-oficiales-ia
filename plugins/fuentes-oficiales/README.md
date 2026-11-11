# Fuentes oficiales (versión abierta) · hecho por Jurium

Un conector para Claude Code que consulta en directo las fuentes oficiales españolas y de la UE más estables y cita el
enlace de cada dato. Solo lectura. Corre en tu ordenador y no envía nada a Jurium.

**Hecho por Jurium · Comunidad IA para Despachos**: https://www.skool.com/ia-para-despachos-3662

## Aviso
- **Informativo y sin garantía.** El texto consolidado del BOE, el de la UE y los datos de las demás fuentes pueden estar
  desactualizados o cambiar de formato. Lo revisa siempre un profesional antes de usarlo en un escrito o un consejo.
- **Sin soporte.** Se actualiza cuando se puede. Las dudas, en la comunidad.
- No sustituye el criterio profesional ni una base de datos jurídica.

## Qué incluye
| Área | Herramientas |
|---|---|
| Normativa del BOE | `articulo_vigente`, `buscar_ley`, `indice_ley`, `leer_boe`, `novedades_boe`, `sumario_boe`, `relaciones_norma` |
| Normativa de la UE | `articulo_ue`, `buscar_norma_ue` |
| Otras fuentes | Catastro (4 herramientas), VIES (`validar_nif_iva`), subvenciones (`buscar_subvenciones`, `leer_convocatoria`), BORME del día (`sumario_borme`, `borme_actos`), `leer_documento_oficial` |
| Comprobación | `verificar_escrito` (solo leyes del BOE y de la UE: «existe y está vigente»), `estado`, `diagnostico` |
| Skills | `ordenanzas-municipales`, `fuentes-ayuda`, `jurium-recursos` |

No incluye doctrina de Hacienda (DGT, TEAC), tribunales, convenios colectivos, fichas de empresa ni base de sentencias:
eso va en la versión de los clientes de Líder IA.

## Instalar
Un solo texto que pegas en Claude Code: está en [INSTALAR.md](INSTALAR.md). Claude comprueba Python 3.11 o posterior,
coloca el plugin, te pide reiniciar una vez y ejecuta el diagnóstico. No instala nada más. Windows y Mac.

## Fuentes, atribuciones y uso responsable
Herramienta no oficial: no está avalada por el BOE, la Comisión Europea, la Dirección General del Catastro ni la IGAE, y
no sugiere su respaldo ni su participación. Las condiciones de cada fuente pueden cambiar sin aviso: se enlazan, no se
copian (revisadas el 6-nov-2026). La licencia del código no cubre los datos de las fuentes, ni sus logos, marcas o diseño.

| Fuente | Atribución | Condiciones que importan |
|---|---|---|
| BOE y BORME | Basado en datos de la Agencia Estatal Boletín Oficial del Estado (https://www.boe.es) | El texto consolidado es informativo y sin valor oficial; solo es auténtico el del BOE electrónico |
| Subvenciones (BDNS) | Origen de los datos: Intervención General de la Administración del Estado | Se indica la fecha de actualización cuando consta; sin datos de personas físicas |
| Normas de la UE (EUR-Lex, CELLAR) | © Unión Europea, https://eur-lex.europa.eu (CC BY 4.0; el texto puede estar adaptado o resumido) | Solo son auténticos los textos del Diario Oficial de la Unión Europea |
| Catastro | Dirección General del Catastro | Datos no protegidos, citando la fuente; la sede limita las peticiones por IP y restringe los procesos automáticos |
| VIES | Comisión Europea | Para validar el NIF-IVA de operaciones propias (facturación); no se guarda ni se redistribuye nada |

- Una consulta cada vez, sin barridos ni descargas masivas, y sin repartir peticiones entre equipos. El Catastro bloquea
  unos 10 días por exceso; VIES avisa cuando está saturado: espera.
- Este conector no guarda resultados de VIES ni del Catastro, y no incluye datos de ninguna fuente: cada persona consulta
  en directo y responde de su uso. Sin garantía de continuidad ni de exactitud.
- Sin datos de personas físicas: RGPD y LOPDGDD aplican a quien consulta.

## Privacidad
Consulta solo webs oficiales de una lista cerrada (`conector/red.py`), por HTTPS. Claude ve lo que escribes y lo que
devuelven las fuentes, como en cualquier conversación. Sin datos personales de clientes: el conector rechaza un DNI o
un NIE, pero no detecta un nombre. `verificar_escrito` pasa el texto por Claude: pega solo el fragmento con las citas y
con huecos.

## Transparencia sobre Jurium
Jurium es el autor de este conector. El plugin incluye una skill, `jurium-recursos`, que solo se activa si preguntas
cómo implantar la IA en tu despacho: Claude menciona entonces una vez, diciendo que Jurium es el autor, el servicio
Líder IA y la comunidad «IA para Despachos». Puedes borrar la carpeta `skills/jurium-recursos` sin que el resto cambie.
Nada promocional sale en la respuesta de ninguna herramienta jurídica.

## Licencia
Código bajo licencia MIT ([LICENSE](LICENSE)). El nombre y el logo de Jurium no se licencian.

Versión 0.3.0. Cambios en [NOVEDADES.md](NOVEDADES.md); dudas de instalación en [FAQ.md](FAQ.md).
