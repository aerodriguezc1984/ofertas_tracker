# herramientas/sonda_comparacion.py
"""Comprueba contra api.solotodo.com que el emparejado sigue funcionando.

No es una prueba automática: toca la red y depende de que el producto exista.
Se ejecuta a mano cuando algo huele mal o antes de dar por buena una entrega.

    python herramientas/sonda_comparacion.py paris 106450999
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fuentes.solotodo import SoloTodo                # noqa: E402
from fuentes.transporte import crear_transporte      # noqa: E402
from nucleo.evaluador import pesos                   # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    tienda = sys.argv[1] if len(sys.argv) > 1 else "paris"
    sku = sys.argv[2] if len(sys.argv) > 2 else "106450999"

    fuente = SoloTodo(crear_transporte())

    identificador = fuente.identidad_de(tienda, sku)
    if identificador is None:
        print(f"FALLA: no se resolvió la identidad de {tienda}/{sku}.")
        print("Puede que el sku ya no exista, o que la API haya cambiado de forma.")
        return 1
    print(f"OK: {tienda}/{sku} -> producto {identificador}\n")

    ofertas = fuente.ofertas_de(identificador)
    if not ofertas:
        print(f"FALLA: el producto {identificador} no devolvió ninguna oferta.")
        return 1

    print(f"OK: {len(ofertas)} ofertas\n")
    for oferta in sorted(ofertas, key=lambda o: o.precio):
        estado = "disponible" if oferta.disponible else "agotado"
        print(f"  [{oferta.tienda}] {pesos(oferta.precio)}  ({estado})")
        print(f"    {oferta.url[:88]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
