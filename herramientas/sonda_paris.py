# herramientas/sonda_paris.py
"""Comprueba contra paris.cl que el raspado sigue funcionando.

No es una prueba automática: toca la red y depende de que un producto exista.
Se ejecuta a mano cuando algo huele mal o antes de dar por buena una entrega.

    python herramientas/sonda_paris.py "notebook"
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fuentes.paris import Paris                   # noqa: E402
from fuentes.transporte import crear_transporte   # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    termino = sys.argv[1] if len(sys.argv) > 1 else "notebook"

    capturas = Paris(crear_transporte()).buscar(termino, limite=3)

    if not capturas:
        print(f"FALLA: la búsqueda de {termino!r} no devolvió nada.")
        print("Puede que Paris haya cambiado la forma de sus enlaces o su JSON-LD.")
        return 1

    print(f"OK: {len(capturas)} capturas para {termino!r}\n")
    for c in capturas:
        print(f"  {c.titulo[:60]}")
        print(f"    sku={c.sku_externo}  precio={c.precio_internet}  stock={c.disponible}")
        print(f"    {c.url}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
