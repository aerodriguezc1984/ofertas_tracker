"""Escribe el portal: la página y su foto de datos.

No toca la red ni la base más que para leer. Se ejecuta al final de cada ciclo,
y también a mano para mirar el portal en local:

    python herramientas/generar_portal.py              # a ./portal
    python herramientas/generar_portal.py /otra/ruta
"""

import json
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from almacen.conexion import abrir          # noqa: E402
from portal.datos import datos_del_portal   # noqa: E402

PLANTILLA = RAIZ / "src" / "portal" / "plantilla.html"
MARCADOR = "__DATOS__"


def generar(
    con: sqlite3.Connection, carpeta: Path | str, ventana_dias: int = 90
) -> tuple[Path, Path]:
    """Escribe `index.html` y `datos.json`. Devuelve sus rutas."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)

    datos = datos_del_portal(con, ventana_dias)

    ruta_datos = carpeta / "datos.json"
    ruta_datos.write_text(
        json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # La plantilla trae el nombre del archivo de datos en un marcador, para que
    # la página no dependa de dónde se sirva.
    ruta_html = carpeta / "index.html"
    ruta_html.write_text(
        PLANTILLA.read_text(encoding="utf-8").replace(MARCADOR, "datos.json"),
        encoding="utf-8",
    )
    return ruta_html, ruta_datos


def main() -> int:
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "portal"
    con = abrir(RAIZ / "data" / "tracker.db")
    html, datos = generar(con, destino)
    print(f"escrito {html}")
    print(f"escrito {datos} ({datos.stat().st_size // 1024} KB)")
    print(f"\nábrelo con: start {html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
