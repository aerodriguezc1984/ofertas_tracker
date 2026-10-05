"""Qué se le dice al usuario y por dónde."""

from typing import Protocol

from fuentes.base import Captura
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


class Notificador(Protocol):
    def enviar(self, captura: Captura, veredicto: Veredicto) -> None: ...
