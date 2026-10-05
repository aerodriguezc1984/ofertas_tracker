"""Las capas del proyecto, comprobadas en vez de prometidas."""

import pathlib
import re

import pytest

SRC = pathlib.Path(__file__).parent.parent / "src"

PROHIBIDO = {
    "nucleo": ("sqlite3", "requests"),
    "fuentes": ("sqlite3",),
}


@pytest.mark.parametrize("capa, prohibidos", sorted(PROHIBIDO.items()))
def test_una_capa_no_importa_lo_que_no_le_toca(capa, prohibidos):
    for archivo in sorted((SRC / capa).glob("*.py")):
        texto = archivo.read_text(encoding="utf-8")
        for modulo in prohibidos:
            assert not re.search(rf"^\s*(import|from)\s+{modulo}\b", texto, re.M), (
                f"{archivo.name} importa {modulo}, que no pertenece a la capa {capa}"
            )
