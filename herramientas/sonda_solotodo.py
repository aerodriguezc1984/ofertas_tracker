# herramientas/sonda_solotodo.py
"""Comprueba contra api.solotodo.com que la fuente sigue funcionando.

No es una prueba automática: toca la red y depende de que haya entidades
activas. Se ejecuta a mano cuando algo huele mal o antes de dar por buena una
entrega.

    python herramientas/sonda_solotodo.py "notebook"
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fuentes.solotodo import SoloTodo                # noqa: E402
from fuentes.transporte import crear_transporte      # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    termino = sys.argv[1] if len(sys.argv) > 1 else "notebook"

    fuente = SoloTodo(crear_transporte(), excluidas=["paris", "falabella"])
    capturas = fuente.buscar(termino, limite=5)

    if not capturas:
        print(f"FALLA: la búsqueda de {termino!r} no devolvió nada.")
        print("Puede que la API haya cambiado de forma, o que esté bloqueando.")
        return 1

    print(f"OK: {len(capturas)} capturas para {termino!r}\n")
    for c in capturas:
        print(f"  [{c.tienda}] {c.titulo[:52]}")
        print(f"    oferta={c.precio_internet}  normal={c.precio_normal}  "
              f"stock={c.disponible}  producto_solotodo={c.producto_solotodo}")
        print(f"    {c.url[:88]}")

    directas = {"paris", "falabella"}
    coladas = sorted({c.tienda for c in capturas} & directas)
    if coladas:
        print(f"\nAVISO: se colaron tiendas que cubrimos en directo: {coladas}")
        print("La exclusión no está funcionando.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
