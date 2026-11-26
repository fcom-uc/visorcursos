#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
construir_horarios.py — genera la página publicada de Horarios FCOM.

Datos:
    cursos.json     todos los cursos del período, agrupados por escuela: {escuela: [secciones]}
    paquetes.json   paquetes de mínimos FCOM: {nombre del paquete: ["COM140", "FIL2001", …]}
Los dos archivos se reconocen por su contenido, en cualquier orden. Los paquetes son opcionales.

Pestañas de la página:
    "Cursos FCOM"   secciones con código COM o incluido en algún paquete; el combo filtra por paquete.
    "Otros cursos"  todas las demás, por escuela. La pestaña aparece solo si queda alguna.
    Regla ad hoc: si esas otras son de 15 cursos (códigos) o menos, se tratan como vacantes especiales
    solicitadas por la Facultad: van a "Cursos FCOM" con la etiqueta "Otros cursos solicitados" y no
    hay pestaña "Otros cursos".
Así, con la programación FCOM (solo COM y mínimos) la página muestra una pestaña, y con el catálogo
completo de la universidad, dos.

Modo estándar (enlazado): la página queda liviana y lee los JSON desde su misma carpeta
(data-src="archivo.json"). Se publican juntos el HTML y los JSON. Para actualizar un JSON basta
reemplazarlo, sin volver a generar la página, si conserva su nombre. La página debe abrirse desde
un servidor (sitio web, o localhost: "python -m http.server" en la carpeta y luego
http://localhost:8000/…), no con doble clic.
Con --incrustar, los JSON van dentro del HTML: un solo archivo que funciona sin servidor.

Uso:
    python construir_horarios.py cursos.json paquetes.json --nombre 2027a
    python construir_horarios.py cursos.json paquetes.json --nombre 2027a --incrustar
    python construir_horarios.py cursos.json paquetes.json --solo-validar

Opciones:
    --nombre           identifica la oferta: separa lo que cada estudiante guarda en su navegador.
                       Úsese sin fecha (p. ej. 2027a) para que los horarios guardados se conserven
                       entre actualizaciones. Por omisión, el nombre del JSON de cursos.
    --escuela-inicial  escuela que se muestra al abrir "Otros cursos" (por omisión, Actividades Universitarias)
    --salida, --fuente
"""
import argparse
import html
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

MODALIDADES = ["Cátedra", "Ayudantía", "Terreno", "Laboratorio", "Taller", "Práctica", "Tesis", "Otro"]
# Igual que la página: "M2", "WMA" y también "LIB V2" o "SUP L1" (se toma V2, L1)
RE_BLOQUE = re.compile(r"(?<![A-Z])([LMWJVS])(MA|[1-9])(?![0-9A-Z])")
ESCUELA_INICIAL = "Actividades Universitarias"
UMBRAL_TRUNCADO = 500     # una escuela con exactamente este número de secciones sugiere una exportación cortada
MAX_EJEMPLOS = 10         # ejemplos por aviso
MAX_SOLICITADOS = 15      # hasta estos cursos no COM ni de paquetes van a "Cursos FCOM" (igual que la página)


def re_tag(ident):
    return re.compile(r'(<script id="' + ident + r'" type="application/json")[^>]*>(.*?)(</script>)', re.S)


RE_CURSOS = re_tag("horarios-data")
RE_PAQUETES = re_tag("paquetes-data")


def sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn").lower().strip()


def campo(obj, nombre):
    """Lee un campo tolerando tildes y mayúsculas distintas (igual que la página)."""
    if nombre in obj:
        return obj[nombre]
    n = sin_tildes(nombre)
    for k, v in obj.items():
        if sin_tildes(k) == n:
            return v
    return None


def codigo(s):
    return str(campo(s, "Código") or "").strip()


def ejemplos(lista):
    lista = list(lista)
    return ", ".join(lista[:MAX_EJEMPLOS]) + (f" … (+{len(lista) - MAX_EJEMPLOS})" if len(lista) > MAX_EJEMPLOS else "")


# ───────────────────────── Reconocer los archivos ─────────────────────────

def es_agrupado(d):
    return (isinstance(d, dict) and bool(d) and all(isinstance(v, list) for v in d.values())
            and any(isinstance(x, dict) for v in d.values() for x in v))


def es_paquetes(d):
    return (isinstance(d, dict) and bool(d) and all(isinstance(v, list) for v in d.values())
            and all(isinstance(x, str) for v in d.values() for x in v))


def secciones_de(cursos):
    """[(escuela, sección)] de {escuela: [...]}; también acepta una lista (formato anterior, sin escuela)."""
    if isinstance(cursos, list):
        return [("", s) for s in cursos]
    if isinstance(cursos, dict) and isinstance(cursos.get("Cursos"), list):
        return [("", s) for s in cursos["Cursos"]]
    return [(e, s) for e, v in cursos.items() for s in v]


# ───────────────────────── Validación ─────────────────────────

def validar(cursos, paquetes):
    """Devuelve (errores, avisos, resumen)."""
    errores, avisos = [], []
    pares = secciones_de(cursos)
    if not pares:
        return ["el JSON de cursos no tiene secciones"], [], {}
    en_paquetes = set()
    for cods in (paquetes or {}).values():
        en_paquetes.update(c.strip().upper() for c in cods)

    def es_fcom(cod):
        return cod.upper().startswith("COM") or cod.upper() in en_paquetes

    sin_cod, no_obj, no_lista = 0, 0, Counter()
    claves, nrcs = Counter(), Counter()
    sin_modulos, raros, ej_raros = [], Counter(), defaultdict(list)
    sin_seccion = []
    fcom, otros = [], []
    por_escuela = Counter()
    for escuela, s in pares:
        if not isinstance(s, dict):
            no_obj += 1
            continue
        cod = codigo(s)
        if not cod:
            sin_cod += 1
            continue
        por_escuela[escuela] += 1
        sec, nrc = campo(s, "Sección"), campo(s, "NRC")
        claves[(cod, sec, nrc)] += 1
        if nrc is not None:
            nrcs[nrc] += 1
        if sec is None:
            sin_seccion.append(cod)
        total = 0
        for m in MODALIDADES:
            v = campo(s, m)
            if v is None:
                continue
            if not isinstance(v, list):
                no_lista[m] += 1
                continue
            for b in v:
                n = len(RE_BLOQUE.findall(str(b).upper()))
                total += n
                if not n and str(b).strip():
                    p = re.sub(r"\d", "9", str(b).strip().upper())
                    raros[p] += 1
                    if len(ej_raros[p]) < 3:
                        ej_raros[p].append(cod)
        if total == 0:
            sin_modulos.append(f"{cod}-{sec if sec is not None else '—'}")
        (fcom if es_fcom(cod) else otros).append((escuela, cod))

    if sin_cod:
        errores.append(f"{sin_cod} sección(es) sin Código")
    if no_obj:
        errores.append(f"{no_obj} elemento(s) que no son secciones")
    for m, n in no_lista.items():
        avisos.append(f"«{m}» no es una lista en {n} sección(es); se ignora")
    for e, n in por_escuela.items():
        if n == UMBRAL_TRUNCADO:
            avisos.append(f"«{e}» tiene exactamente {UMBRAL_TRUNCADO} secciones: ¿la exportación quedó cortada?")
    rep = [f"{c}-{s if s is not None else '—'}" for (c, s, n), k in claves.items() if k > 1]
    if rep:
        avisos.append(f"{len(rep)} sección(es) repetidas con el mismo código, sección y NRC: {ejemplos(rep)}")
    nrc_rep = [str(n) for n, k in nrcs.items() if k > 1]
    if nrc_rep:
        avisos.append(f"{len(nrc_rep)} NRC usado(s) por más de una sección: {ejemplos(nrc_rep)}")
    if sin_seccion:
        avisos.append(f"{len(sin_seccion)} sección(es) sin número de sección: {ejemplos(sin_seccion)}")
    for p, n in raros.most_common():
        avisos.append(f"módulo sin día y número ({n} veces), se ignora: \"{p}\" — p. ej. {', '.join(ej_raros[p])}")
    if sin_modulos:
        avisos.append(f"{len(sin_modulos)} sección(es) sin módulos ubicables (quedan «sin horario»): {ejemplos(sin_modulos)}")

    # Paquetes
    if paquetes:
        programados = {c.upper() for _, c in fcom}
        dentro = defaultdict(list)
        for nombre, cods in paquetes.items():
            r = sorted(c for c, n in Counter(c.strip().upper() for c in cods).items() if n > 1)
            if r:
                avisos.append(f"paquete «{nombre}»: códigos repetidos: {', '.join(r)}")
            for c in set(c.strip().upper() for c in cods):
                dentro[c].append(nombre)
        for c, ns in sorted(dentro.items()):
            if len(ns) > 1:
                avisos.append(f"{c} está en {len(ns)} paquetes: " + " / ".join(ns))
        fuera = sorted({c for _, c in fcom if c.upper() not in dentro})
        if fuera:
            avisos.append(f"{len(fuera)} curso(s) COM fuera de los paquetes (opción «Cursos optativos o de servicio FCOM»): {ejemplos(fuera)}")
        sin = set(dentro) - programados
        if sin:
            avisos.append(f"{len(sin)} código(s) de los paquetes sin secciones en este JSON (normal si no se dictan este período)")
    else:
        avisos.append("sin archivo de paquetes: la pestaña «Cursos FCOM» tendrá solo los códigos COM y el combo usará "
                      "las columnas verdadero/falso del JSON, si las tiene")

    resumen = {"fcom": len(fcom), "otros": len(otros),
               "esc_otros": len({e for e, _ in otros}),
               "cods_otros": sorted({c for _, c in otros})}
    return errores, avisos, resumen


# ───────────────────────── Construcción ─────────────────────────

def compactar(d):
    """Para --incrustar: omite los arreglos de módulos vacíos (la página los trata igual)."""
    if isinstance(d, dict) and es_agrupado(d):
        return {e: [{k: v for k, v in s.items() if not (isinstance(v, list) and not v)} if isinstance(s, dict) else s
                    for s in secs] for e, secs in d.items()}
    return d


def serializar(datos):
    """Una sección por línea (legible en el HTML) y todo '<' escapado como \\u003c."""
    if isinstance(datos, list):
        txt = "[\n" + ",\n".join(json.dumps(x, ensure_ascii=False) for x in datos) + "\n]"
    elif es_paquetes(datos):
        txt = "{\n" + ",\n".join(json.dumps(k, ensure_ascii=False) + ":" + json.dumps(v, ensure_ascii=False)
                                  for k, v in datos.items()) + "\n}"
    elif es_agrupado(datos):
        txt = "{\n" + ",\n".join(json.dumps(e, ensure_ascii=False) + ":[\n" +
                                  ",\n".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in secs) + "\n]"
                                  for e, secs in datos.items()) + "\n}"
    else:
        txt = json.dumps(datos, ensure_ascii=False, indent=1)
    return txt.replace("<", "\\u003c")


def poner(texto, regex, ident, atributos, datos):
    """Rellena <script id="ident">: atributos {nombre: valor} y, si datos no es None, el JSON adentro."""
    if not regex.search(texto):
        raise RuntimeError(f'la fuente no tiene <script id="{ident}" type="application/json">')
    abre = f'<script id="{ident}" type="application/json"' + "".join(
        f' {k}="' + html.escape(v, quote=True) + '"' for k, v in atributos.items()) + '>'
    cuerpo = ("\n" + serializar(datos) + "\n") if datos is not None else ""
    texto = regex.sub(lambda m: abre + cuerpo + m.group(3), texto, count=1)
    # Verificaciones: lo incrustado se recupera idéntico y no puede cerrar la etiqueta antes de tiempo
    contenido = regex.search(texto).group(2)
    if "</" in contenido:
        raise RuntimeError(f"el JSON incrustado en {ident} contiene '</' (no debería ocurrir tras el escape)")
    if datos is not None and json.loads(contenido) != datos:
        raise RuntimeError(f"el JSON incrustado en {ident} no se recupera idéntico")
    return texto


def leer_json(ruta):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8-sig"))   # utf-8-sig quita el BOM si viene
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: no se pudo leer {ruta}: {e}")


def main():
    ap = argparse.ArgumentParser(description="Genera Horarios FCOM a partir del JSON de cursos y el de paquetes.")
    ap.add_argument("archivos", type=Path, nargs="+", metavar="json",
                    help="JSON de cursos ({escuela: [secciones]}) y, opcionalmente, JSON de paquetes, en cualquier orden")
    ap.add_argument("--nombre", help="nombre de la oferta (por omisión, el nombre del JSON de cursos)")
    ap.add_argument("--escuela-inicial", default=ESCUELA_INICIAL,
                    help=f"escuela que se muestra al abrir «Otros cursos» (por omisión, {ESCUELA_INICIAL})")
    ap.add_argument("--incrustar", action="store_true",
                    help="mete los JSON dentro del HTML (un solo archivo, sirve sin servidor)")
    ap.add_argument("--fuente", type=Path, default=Path(__file__).with_name("_Horarios_Fuente.html"))
    ap.add_argument("--salida", type=Path, help="HTML a generar (por omisión, Horarios_Publica_<nombre>.html)")
    ap.add_argument("--solo-validar", action="store_true", help="valida los JSON sin generar nada")
    a = ap.parse_args()

    # Reconocer cada archivo por su contenido
    ruta_c = ruta_p = None
    cursos = paquetes = None
    for ruta in a.archivos:
        d = leer_json(ruta)
        if es_paquetes(d):
            if paquetes is not None:
                sys.exit(f"ERROR: hay dos archivos de paquetes ({ruta_p.name} y {ruta.name})")
            ruta_p, paquetes = ruta, d
        elif es_agrupado(d) or isinstance(d, list) or (isinstance(d, dict) and "Cursos" in d):
            if cursos is not None:
                sys.exit(f"ERROR: hay dos archivos de cursos ({ruta_c.name} y {ruta.name}); "
                         "todos los cursos van en un solo JSON, agrupados por escuela")
            ruta_c, cursos = ruta, d
        else:
            sys.exit(f"ERROR: {ruta.name} no es ni un JSON de cursos ni uno de paquetes")
    if cursos is None:
        sys.exit("ERROR: falta el JSON de cursos")

    errores, avisos, r = validar(cursos, paquetes)
    print(f"Cursos: {ruta_c.name} — {len(secciones_de(cursos))} secciones")
    if paquetes is not None:
        print(f"Paquetes: {ruta_p.name} — {len(paquetes)} paquetes")
    for x in avisos:
        print("  aviso:", x)
    for x in errores:
        print("  ERROR:", x)
    if errores:
        sys.exit(1)
    print(f"Pestaña «Cursos FCOM»: {r['fcom']} secciones (COM o en algún paquete)")
    if r["otros"] and len(r["cods_otros"]) <= MAX_SOLICITADOS:
        print(f"  + «Otros cursos solicitados»: {r['otros']} secciones de {len(r['cods_otros'])} curso(s) que no son COM "
              f"ni están en paquetes ({MAX_SOLICITADOS} o menos): {', '.join(r['cods_otros'])}")
        print("Sin pestaña «Otros cursos»")
    elif r["otros"]:
        detalle = f": {ejemplos(r['cods_otros'])}" if len(r["cods_otros"]) <= 30 else ""
        print(f"Pestaña «Otros cursos»: {r['otros']} secciones en {r['esc_otros']} escuela(s){detalle}")
    else:
        print("Sin pestaña «Otros cursos» (todo es COM o está en algún paquete)")

    if a.solo_validar:
        print("Validación terminada (no se generó nada).")
        return

    nombre = a.nombre or ruta_c.stem
    salida = a.salida or a.fuente.with_name(f"Horarios_Publica_{nombre}.html")
    if salida.resolve() == a.fuente.resolve():
        sys.exit("ERROR: la salida no puede ser la misma fuente")
    destino = salida.resolve().parent

    def enlace(ruta):
        """Modo enlazado: ruta del JSON relativa al HTML."""
        rel = Path(os.path.relpath(ruta.resolve(), destino)).as_posix()
        if "/" in rel:
            print(f"  aviso: {ruta.name} no está en la carpeta del HTML; se enlaza como «{rel}». "
                  f"Al publicar, conserva esa ubicación o copia el JSON junto al HTML.")
        return rel

    try:
        texto = a.fuente.read_text(encoding="utf-8")
        at_c = {"data-oferta": nombre, "data-archivo": ruta_c.stem, "data-escuela-inicial": a.escuela_inicial}
        at_p = {"data-paquetes": ruta_p.stem if ruta_p else ""}
        if a.incrustar:
            texto = poner(texto, RE_CURSOS, "horarios-data", at_c, compactar(cursos))
            texto = poner(texto, RE_PAQUETES, "paquetes-data", at_p, paquetes)
        else:
            texto = poner(texto, RE_CURSOS, "horarios-data", dict(at_c, **{"data-src": enlace(ruta_c)}), None)
            texto = poner(texto, RE_PAQUETES, "paquetes-data",
                          dict(at_p, **({"data-src": enlace(ruta_p)} if ruta_p else {})), None)
        salida.write_text(texto, encoding="utf-8", newline="\n")
    except (OSError, RuntimeError) as e:
        sys.exit(f"ERROR: {e}")
    kb = salida.stat().st_size / 1024
    modo = ("JSON incrustados: funciona sin servidor" if a.incrustar
            else "lee los JSON de su carpeta: publicar juntos y abrir desde un servidor")
    print(f"Generado: {salida}  ({kb:,.0f} KB; oferta \"{nombre}\"; {modo})")


if __name__ == "__main__":
    main()
