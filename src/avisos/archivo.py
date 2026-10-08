"""Notificador de respaldo: deja las alertas en un .jsonl legible."""

import json
from datetime import datetime, timezone
from pathlib import Path

from avisos.base import redactar, redactar_mejor_precio
from fuentes.base import Captura
from nucleo.comparacion import ProductoVigilado, VeredictoMejorPrecio
from nucleo.evaluador import Veredicto


class NotificadorArchivo:
    def __init__(self, ruta: Path | str) -> None:
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)

    def enviar(self, captura: Captura, veredicto: Veredicto) -> None:
        registro = {
            "momento": datetime.now(timezone.utc).isoformat(),
            "tienda": captura.tienda,
            "titulo": captura.titulo,
            "url": captura.url,
            "regla": veredicto.regla,
            "precio": veredicto.precio,
            "mensaje": redactar(captura, veredicto),
        }
        with self.ruta.open("a", encoding="utf-8") as archivo:
            archivo.write(json.dumps(registro, ensure_ascii=False) + "\n")

    def enviar_mejor_precio(
        self, producto: ProductoVigilado, veredicto: VeredictoMejorPrecio
    ) -> None:
        registro = {
            "momento": datetime.now(timezone.utc).isoformat(),
            "tienda": producto.tienda,
            "tienda_ajena": veredicto.oferta.tienda,
            "titulo": producto.titulo,
            "url": veredicto.oferta.url,
            "regla": "mejor_precio",
            "precio": veredicto.oferta.precio,
            "precio_nuestro": producto.precio_internet,
            "mensaje": redactar_mejor_precio(producto, veredicto),
        }
        with self.ruta.open("a", encoding="utf-8") as archivo:
            archivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
