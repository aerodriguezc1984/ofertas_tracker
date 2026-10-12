"""Las capas del proyecto, comprobadas en vez de prometidas."""

import pathlib
import re

import pytest

SRC = pathlib.Path(__file__).parent.parent / "src"

PROHIBIDO = {
    # `almacen` está aquí porque la rotura real que motivó esta prueba fue
    # `from almacen.operaciones import ultima_alerta` en nucleo/frecuencia.py.
    # Sin él, esta prueba pasaría en verde ante la repetición exacta del fallo
    # que la justifica.
    # `portal` está aquí porque la Etapa 4 añadió una capa que LEE de `almacen`:
    # la flecha va en un solo sentido, y nadie de abajo puede mirar hacia ella.
    "nucleo": ("sqlite3", "requests", "almacen", "portal"),
    "fuentes": ("sqlite3", "portal"),
    "almacen": ("portal",),
}


@pytest.mark.parametrize("capa, prohibidos", sorted(PROHIBIDO.items()))
def test_una_capa_no_importa_lo_que_no_le_toca(capa, prohibidos):
    archivos = sorted((SRC / capa).glob("*.py"))
    # Si la carpeta se renombra, el glob queda vacío y el bucle de abajo no
    # comprueba nada: un verde de cero sobre cero.
    assert archivos, f"no se encontró ningún módulo en la capa {capa}"

    for archivo in archivos:
        texto = archivo.read_text(encoding="utf-8")
        for modulo in prohibidos:
            assert not re.search(rf"^\s*(import|from)\s+{modulo}\b", texto, re.M), (
                f"{archivo.name} importa {modulo}, que no pertenece a la capa {capa}"
            )
