# herramientas/sonda_falabella.py
"""Comprueba contra falabella.com que el raspado sigue funcionando.

No es una prueba automática: toca la red y depende de que haya productos. Se
ejecuta a mano cuando algo huele mal o antes de dar por buena una entrega.

Comprueba las dos mitades: que la búsqueda devuelve candidatos con precios
inferidos, y que la ficha de uno de ellos devuelve los tres precios ETIQUETADOS
anclados a su propio SKU — que es la parte frágil del adaptador.

    python herramientas/sonda_falabella.py "notebook"
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fuentes.base import Referencia                 # noqa: E402
from fuentes.falabella import Falabella             # noqa: E402
from fuentes.transporte import crear_transporte     # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    termino = sys.argv[1] if len(sys.argv) > 1 else "notebook"

    falabella = Falabella(crear_transporte())
    inferidas = falabella.buscar(termino, limite=3)

    if not inferidas:
        print(f"FALLA: la búsqueda de {termino!r} no devolvió nada.")
        print("Puede que Falabella haya cambiado su ItemList o esté bloqueando.")
        return 1

    print(f"OK: {len(inferidas)} candidatos para {termino!r} (precios inferidos)\n")
    for c in inferidas:
        print(f"  {c.titulo[:58]}")
        print(f"    sku={c.sku_externo}  tarjeta={c.precio_tarjeta}  "
              f"internet={c.precio_internet}  normal={c.precio_normal}")

    primera = inferidas[0]
    print(f"\nConfirmando la primera contra su ficha...")
    exactas = falabella.obtener([
        Referencia(tienda="falabella", url=primera.url, sku_externo=primera.sku_externo)
    ])
    if not exactas:
        print("FALLA: la ficha no devolvió datos utilizables.")
        print("Lo más probable: el anclaje al sellerSkuId ya no encuentra el bloque.")
        return 1

    e = exactas[0]
    print(f"OK: ficha leída, precios etiquetados={e.precios_etiquetados}")
    print(f"    tarjeta={e.precio_tarjeta}  internet={e.precio_internet}  normal={e.precio_normal}")
    if (primera.precio_tarjeta, primera.precio_internet) != (e.precio_tarjeta, e.precio_internet):
        print("\nAVISO: la inferencia del orden NO coincidió con las etiquetas de la ficha.")
        print("No es un fallo —por eso se confirma— pero conviene saberlo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
