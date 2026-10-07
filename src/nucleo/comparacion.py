"""Decide si el mismo producto está lo bastante más barato en otra tienda.

Pura: sin red, sin SQL y sin reloj. Entra nuestro precio y lo que un agregador
dice de las demás tiendas; sale un veredicto o nada. Que no sepa de dónde vienen
las ofertas es lo que la hace probable entera con listas escritas a mano.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OfertaAjena:
    """El precio del mismo artículo en una tienda que no capturamos nosotros."""

    tienda: str
    precio: int
    url: str
    disponible: bool = True


@dataclass(frozen=True)
class ProductoVigilado:
    """Una fila de `productos` con su último precio, lista para comparar."""

    id: int
    tienda: str
    sku_externo: str
    titulo: str
    url: str
    precio_internet: int
    producto_solotodo: int | None


@dataclass(frozen=True)
class ReglasComparacion:
    """Los dos umbrales. Se exigen LOS DOS, no uno.

    Cada uno tapa el agujero del otro: sin el absoluto, un mouse de 8.000 pesos
    avisa por 800; sin el relativo, un notebook de 900.000 avisa por 10.000, que
    no mueve ninguna decisión.
    """

    caida_minima_pct: float = 10.0
    ahorro_minimo_pesos: int = 10000


@dataclass(frozen=True)
class VeredictoMejorPrecio:
    oferta: OfertaAjena
    ahorro: int
    porcentaje: float


def mejor_oferta(
    precio_nuestro: int,
    tienda_nuestra: str,
    ofertas: list[OfertaAjena],
    reglas: ReglasComparacion,
) -> VeredictoMejorPrecio | None:
    """La mejor oferta ajena que supera los dos umbrales, o None."""
    if precio_nuestro <= 0:
        # El porcentaje divide por este número. Y un producto sin precio no
        # tiene con qué comparar: no es un caso de error, es un «todavía no».
        return None

    candidatas = [
        oferta
        for oferta in ofertas
        if oferta.disponible
        and oferta.precio > 0
        and oferta.precio < precio_nuestro
        # Nuestro propio producto aparece en su lista de entidades: el
        # agregador también cubre nuestra tienda. Compararse consigo mismo
        # diría que Paris está más barato que Paris.
        and oferta.tienda != tienda_nuestra
    ]
    if not candidatas:
        return None

    # El desempate por nombre no es cosmético: sin él, dos tiendas al mismo
    # precio darían un aviso distinto según el orden en que la API las listara.
    mejor = min(candidatas, key=lambda oferta: (oferta.precio, oferta.tienda))

    ahorro = precio_nuestro - mejor.precio
    porcentaje = ahorro / precio_nuestro * 100
    if ahorro < reglas.ahorro_minimo_pesos or porcentaje < reglas.caida_minima_pct:
        return None

    return VeredictoMejorPrecio(oferta=mejor, ahorro=ahorro, porcentaje=porcentaje)
