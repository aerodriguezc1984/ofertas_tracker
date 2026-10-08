"""Qué se le dice al usuario y por dónde."""

from typing import Protocol

from fuentes.base import Captura
from nucleo.comparacion import ProductoVigilado, VeredictoMejorPrecio
from nucleo.evaluador import Veredicto, pesos


def redactar(captura: Captura, veredicto: Veredicto) -> str:
    lineas = [
        "🔥 Oferta detectada",
        "",
        captura.titulo,
        f"Tienda: {captura.tienda}",
        f"Precio: {pesos(veredicto.precio)}",
    ]
    if captura.precio_normal and captura.precio_normal > veredicto.precio:
        lineas.append(f"Antes: {pesos(captura.precio_normal)}")
    lineas += [f"Motivo: {veredicto.motivo}", "", captura.url]
    return "\n".join(lineas)


def redactar_mejor_precio(
    producto: ProductoVigilado, veredicto: VeredictoMejorPrecio
) -> str:
    """El aviso de que el mismo artículo está más barato en otra tienda.

    Dice de dónde sale cada precio: el nuestro lo capturamos hoy, el ajeno lo
    da el agregador y puede ir rezagado. Y enlaza a la tienda ajena, que es el
    enlace que sirve para algo.
    """
    return "\n".join(
        [
            "💸 Más barato en otra tienda",
            "",
            producto.titulo,
            f"En {producto.tienda}: {pesos(producto.precio_internet)}",
            f"En {veredicto.oferta.tienda}: {pesos(veredicto.oferta.precio)}",
            f"Ahorras {pesos(veredicto.ahorro)} ({veredicto.porcentaje:.0f} %)",
            "",
            "El precio de la otra tienda lo da SoloTodo y puede ir rezagado.",
            "",
            veredicto.oferta.url,
        ]
    )


class Notificador(Protocol):
    def enviar(self, captura: Captura, veredicto: Veredicto) -> None: ...

    def enviar_mejor_precio(
        self, producto: ProductoVigilado, veredicto: VeredictoMejorPrecio
    ) -> None: ...
