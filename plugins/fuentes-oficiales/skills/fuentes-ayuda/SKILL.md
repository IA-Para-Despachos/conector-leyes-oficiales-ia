---
name: fuentes-ayuda
description: Explica qué se puede preguntar al conector de fuentes oficiales de Jurium, con diez ejemplos copiables por áreas (fiscal, laboral, mercantil, inmuebles, UE). Úsala cuando el usuario pregunte qué puede hacer o preguntar con el conector, pida ayuda, ejemplos o "por dónde empiezo", o acabe de instalarlo.
---

<!-- Fuentes oficiales (versión abierta) 0.3.1. Hecho por Jurium. Licencia MIT (LICENSE). -->

# Qué puedes preguntar al conector de fuentes oficiales

Preséntale al usuario esta lista tal cual, por áreas, con los ejemplos copiables. Cada uno consulta la fuente oficial en
directo y cita su enlace; tarda de 5 a 60 s. Sin nombres ni DNI de clientes en las preguntas. Lo que sale es
informativo y lo revisa siempre una persona.

## Diez cosas que puedes preguntar

**Fiscal**
1. «¿Qué dice hoy el artículo 20.Uno.23 de la Ley del IVA? Dime desde cuándo rige esa redacción.»
2. «¿Qué normas han modificado el artículo 20 de la Ley del IVA?» (grafo de modificaciones del BOE).

**Laboral**
3. «¿Qué dice hoy el artículo 53 del Estatuto de los Trabajadores sobre el despido objetivo?»
4. «¿Qué convenios colectivos se han publicado en el BOE en los últimos 15 días?»

**Mercantil**
5. «¿Qué dice hoy el artículo 160 de la Ley de Sociedades de Capital sobre las competencias de la junta general?»
6. «¿Qué actos se han publicado hoy en el BORME para [provincia]? Filtra por [nombre de la sociedad].»
7. «Revisa estas citas antes de presentar el escrito: [fragmento con las citas, con huecos como "[cliente]"].»
   (`verificar_escrito`: comprueba que cada artículo de ley existe y está vigente; no dice que la ley afirme lo que el
   escrito le atribuye, eso se lee.)

**Inmuebles y empresas**
8. «Dame los datos catastrales de la referencia [referencia catastral] o de [calle, número, municipio, provincia].»
9. «¿Está dado de alta en VIES el NIF-IVA [ESB...] de este proveedor?» (solo empresas, nunca un DNI).

**Unión Europea**
10. «¿Qué dice hoy el artículo 6 del RGPD sobre la licitud del tratamiento?»

Y subvenciones: «¿Qué convocatorias de ayudas para digitalización de pymes hay abiertas?».

## Lo que esta versión no hace
No consulta doctrina de Hacienda (DGT, TEAC), tribunales, convenios, fichas de empresa ni anuncios del BOE: para eso, la
web oficial. Las ordenanzas municipales van con la skill `ordenanzas-municipales`, por el navegador.

## Más recetas
La demo del conector y más recetas de uso están en la comunidad «IA para Despachos»: demo, {ENLACE_DEMO}; recetas,
{ENLACE_RECETAS}. Si algún enlace aparece aún entre llaves, sin rellenar, no lo des.
