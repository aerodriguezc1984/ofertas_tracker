"""Cómo fue el último ciclo, mirando el registro y la base.

Pensado para el día después: la tarea programada corrió sola de madrugada y no
hay nadie delante. Esto contesta en diez líneas lo único que importa —si corrió,
si falló algo, qué descubrió, de qué avisó— sin leerse `logs/ciclo.log` entero.

    python herramientas/resumen_ciclo.py          # la última ejecución
    python herramientas/resumen_ciclo.py 3        # las últimas tres

No toca la red. Solo lee.
"""

import re
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).parent.parent
REGISTRO = RAIZ / "logs" / "ciclo.log"
BASE = RAIZ / "data" / "tracker.db"

# El lanzador escribe `===== fecha hora =====` antes de cada ejecución.
_CABECERA = re.compile(r"^===== (.+?) =====\s*$")
_FIN = re.compile(r"^----- fin, codigo (\d+) -----")


def _ejecuciones(texto: str) -> list[dict]:
    """Parte el registro por ejecuciones, de la más reciente a la más antigua."""
    corridas: list[dict] = []
    for linea in texto.splitlines():
        cabecera = _CABECERA.match(linea)
        if cabecera:
            corridas.append({"cuando": cabecera.group(1).strip(), "lineas": [], "codigo": None})
            continue
        if not corridas:
            continue
        fin = _FIN.match(linea)
        if fin:
            corridas[-1]["codigo"] = int(fin.group(1))
        else:
            corridas[-1]["lineas"].append(linea)
    return corridas[::-1]


def _resumir(corrida: dict) -> None:
    lineas = corrida["lineas"]
    codigo = corrida["codigo"]
    estado = "sin terminar" if codigo is None else ("OK" if codigo == 0 else f"FALLÓ ({codigo})")
    print(f"\n=== {corrida['cuando']}  ->  {estado} ===")

    for patron, etiqueta in (
        (r"ciclo terminado: (\d+) alertas", "alertas de precio"),
        (r"comparaci.n terminada: (\d+) avisos", "avisos de mejor precio"),
    ):
        encontrado = [m.group(1) for l in lineas if (m := re.search(patron, l))]
        print(f"   {etiqueta:26} {encontrado[-1] if encontrado else '—'}")

    # Los avisos se agrupan por tipo: treinta líneas iguales no dicen más que
    # una con su recuento, y esconden la que sí es distinta.
    avisos: dict[str, int] = {}
    for l in lineas:
        if "WARNING" not in l:
            continue
        # Se recorta el sujeto variable (url, sku, término) para agrupar.
        clave = re.sub(r"'[^']*'|https?://\S+|\b\d{4,}\b", "…", l.split("WARNING")[-1]).strip()
        avisos[clave] = avisos.get(clave, 0) + 1
    if avisos:
        print(f"   {'avisos (agrupados)':26} {sum(avisos.values())}")
        for clave, n in sorted(avisos.items(), key=lambda x: -x[1])[:6]:
            print(f"       {n:3}x {clave[:88]}")
    else:
        print(f"   {'avisos':26} ninguno")


def _estado_de_la_base() -> None:
    if not BASE.exists():
        print("\n(no hay base todavía)")
        return
    con = sqlite3.connect(BASE)
    con.row_factory = sqlite3.Row
    print("\n=== la base ahora mismo ===")
    print("   productos:", con.execute("SELECT COUNT(*) FROM productos").fetchone()[0],
          "| tiendas:", con.execute("SELECT COUNT(DISTINCT tienda) FROM productos").fetchone()[0])
    print("   histórico:", con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0],
          "filas |", con.execute(
              "SELECT COUNT(*) FROM (SELECT producto_id FROM historico_precios"
              " GROUP BY producto_id HAVING COUNT(*) > 1)").fetchone()[0],
          "productos con pasado")
    print("   alertas:", dict(con.execute(
        "SELECT regla, COUNT(*) FROM registro_alertas GROUP BY regla").fetchall()))

    print("\n   últimos avisos enviados:")
    for fila in con.execute(
        """
        SELECT a.enviado_el, a.regla, p.tienda, substr(p.titulo, 1, 38) AS titulo,
               a.precio_notificado
          FROM registro_alertas a JOIN productos p ON p.id = a.producto_id
         ORDER BY a.id DESC LIMIT 8
        """
    ):
        print("     %s  %-14s %-14s %-40s $%s" % tuple(fila))


def main() -> int:
    if not REGISTRO.exists():
        print(f"No hay registro en {REGISTRO}.")
        print("La tarea programada aún no ha corrido, o corrió sin el lanzador.")
        return 1

    cuantas = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    corridas = _ejecuciones(REGISTRO.read_text(encoding="utf-8", errors="replace"))
    if not corridas:
        print(f"{REGISTRO} existe pero no tiene ninguna ejecución completa.")
        return 1

    for corrida in corridas[:cuantas]:
        _resumir(corrida)
    _estado_de_la_base()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
