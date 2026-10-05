"""El contrato que cumple toda fuente, venga de donde venga el dato."""

from dataclasses import dataclass
from typing import Callable, Protocol

# Una fuente no habla HTTP directamente: recibe una función que, dada una URL,
# devuelve el cuerpo como texto. Así las pruebas no tocan la red.
Transporte = Callable[[str], str]


@dataclass(frozen=True)
class Captura:
    """Una lectura de precio ya normalizada. Todos los precios en CLP enteros."""

    tienda: str
    sku_externo: str
    titulo: str
    url: str
    precio_internet: int
    precio_normal: int | None = None
    precio_tarjeta: int | None = None
    tarjeta: str | None = None
    disponible: bool = True
    imagen_url: str | None = None
    ean: str | None = None
    # Falso solo cuando los precios se han inferido del orden en que la tienda
    # los lista, sin etiqueta que diga cuál es cuál. El orquestador confirma
    # contra la ficha antes de alertar o de escribir en el histórico.
    precios_etiquetados: bool = True


@dataclass(frozen=True)
class Referencia:
    """Lo que la lista de deseos entrega a una fuente: qué mirar y dónde."""

    tienda: str
    url: str
    sku_externo: str | None = None


@dataclass(frozen=True)
class Candidato:
    """Lo que una búsqueda encuentra: dónde mirar y lo que ya se sabe de ahí.

    Unas tiendas devuelven enlaces que hay que seguir (`captura` a None); otras
    traen los productos dentro de la propia página de resultados.
    """

    referencia: Referencia
    captura: Captura | None = None


class Fuente(Protocol):
    nombre: str

    def obtener(self, referencias: list[Referencia]) -> list[Captura]: ...

    def buscar(self, termino: str, limite: int) -> list[Captura]: ...
