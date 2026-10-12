"""¿Responden las tiendas desde ESTA máquina?

La pregunta que decide si el rastreador puede vivir fuera de un equipo
doméstico. El retail chileno filtra direcciones de centro de datos con
frecuencia, y un bloqueo no siempre llega como un 403: a veces es un 200 con una
página puente que no trae nada que raspar.

    python herramientas/sonda_entorno.py

No analiza nada ni escribe en la base: solo pide y mide. Lo que reporta de cada
destino es el código, el tamaño, y si el cuerpo trae las señales que el
rastreador necesita. Un 200 pequeño sin JSON-LD es un bloqueo disfrazado, y
conviene nombrarlo así en vez de decir «no se pudo analizar».
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fuentes.transporte import TiendaBloqueada, crear_transporte  # noqa: E402

# Sin pausa: son cuatro peticiones y queremos la respuesta, no disimular.
traer = crear_transporte(pausa=None)

DESTINOS = [
    (
        "SoloTodo (API)",
        "https://api.solotodo.com/stores/",
        ["\"name\""],
    ),
    (
        "Paris (búsqueda)",
        "https://www.paris.cl/search?q=notebook",
        ["application/ld+json"],
    ),
    (
        "Falabella (búsqueda)",
        "https://www.falabella.com/falabella-cl/search?Ntt=notebook",
        ["application/ld+json"],
    ),
    (
        "Falabella (ficha)",
        "https://www.falabella.com/falabella-cl/product/16894286/notebook",
        ["application/ld+json", "\"prices\":["],
    ),
]


def _donde_estoy() -> None:
    try:
        datos = json.loads(traer("https://api.ipify.org?format=json"))
        print(f"IP pública desde la que se pide: {datos.get('ip')}")
    except Exception as error:
        print(f"No se pudo averiguar la IP ({type(error).__name__})")
    print()


def main() -> int:
    print("=" * 72)
    print("¿Responden las tiendas desde aquí?")
    print("=" * 72)
    _donde_estoy()

    fallos = 0
    for nombre, url, señales in DESTINOS:
        print(f"--- {nombre}")
        try:
            cuerpo = traer(url)
        except TiendaBloqueada as error:
            # El transporte ya convierte 4xx, 5xx y los tiempos agotados en esto.
            print(f"    BLOQUEADO: {error}")
            print()
            fallos += 1
            continue

        encontradas = [s for s in señales if s in cuerpo]
        faltan = [s for s in señales if s not in cuerpo]
        print(f"    respondió {len(cuerpo):,} bytes".replace(",", "."))
        for s in encontradas:
            print(f"    tiene {s!r}")
        for s in faltan:
            print(f"    NO TIENE {s!r}")

        if faltan:
            # 200 con el cuerpo equivocado: una página puente, un captcha o un
            # interstitial. Decirlo así evita que mañana se depure el analizador.
            print("    -> responde pero NO sirve: es un bloqueo disfrazado de 200")
            fallos += 1
        else:
            print("    -> SIRVE")
        print()

    print("=" * 72)
    if fallos:
        print(f"{fallos} de {len(DESTINOS)} destinos no sirven desde aquí.")
    else:
        print(f"Los {len(DESTINOS)} destinos responden con lo que hace falta.")
    print("=" * 72)
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
