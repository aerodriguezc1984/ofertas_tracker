"""Orquesta un ciclo completo: capturar, guardar, evaluar, avisar."""

import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Bajo pytest, `src` entra por el pythonpath del pyproject.toml. Al ejecutar
# `python runner.py` a secas no hay tal cosa, así que se añade aquí.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from almacen.conexion import abrir                 # noqa: E402
from almacen.operaciones import (                  # noqa: E402
    alta_o_actualiza_producto,
    dias_de_historico,
    minimo_historico,
    registrar_alerta,
    registrar_si_cambio,
    ultima_alerta,
)
from avisos.archivo import NotificadorArchivo      # noqa: E402
from avisos.telegram import (                      # noqa: E402
    NotificadorTelegram,
    TelegramMalConfigurado,
)
from fuentes.base import Referencia                # noqa: E402
from fuentes.paris import Paris                    # noqa: E402
from fuentes.transporte import crear_transporte    # noqa: E402
from nucleo.evaluador import Reglas, evaluar       # noqa: E402
from nucleo.frecuencia import debe_notificar       # noqa: E402

registro = logging.getLogger("rastreador")

RAIZ = Path(__file__).parent


def cargar_config(ruta: Path | str) -> dict:
    return yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))


def _reglas_de(entrada: dict, que: str) -> Reglas | None:
    """Las Reglas de una entrada, o None si declara alguna que no existe.

    Una errata en el YAML debe costar ese producto, no el ciclo entero.
    """
    try:
        return Reglas(**(entrada.get("reglas") or {}))
    except TypeError as error:
        registro.warning("se salta %s por una regla desconocida: %s", que, error)
        return None


def _entrada_valida(entrada, obligatorias: tuple[str, ...], donde: str) -> bool:
    """Si a una entrada le falta lo imprescindible, se avisa y se salta."""
    if not isinstance(entrada, dict):
        registro.warning("se salta una entrada de %s que no es un mapa: %r", donde, entrada)
        return False
    faltan = [clave for clave in obligatorias if not entrada.get(clave)]
    if faltan:
        registro.warning(
            "se salta una entrada de %s sin %s: %r", donde, ", ".join(faltan), entrada
        )
        return False
    return True


def cargar_lista_deseos(ruta: Path | str) -> tuple[list[dict], list[dict]]:
    """Devuelve (vigilados, busquedas) con las reglas ya convertidas."""
    datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}

    vigilados = []
    for entrada in datos.get("vigilados") or []:
        if not _entrada_valida(entrada, ("tienda", "url"), "vigilados"):
            continue
        reglas = _reglas_de(entrada, entrada["url"])
        if reglas is None:
            continue
        vigilados.append(
            {"tienda": entrada["tienda"], "url": entrada["url"], "reglas": reglas}
        )

    busquedas = []
    for entrada in datos.get("busquedas") or []:
        if not _entrada_valida(entrada, ("tienda", "termino"), "busquedas"):
            continue
        reglas = _reglas_de(entrada, entrada["termino"])
        if reglas is None:
            continue
        busquedas.append(
            {"tienda": entrada["tienda"], "termino": entrada["termino"], "reglas": reglas}
        )

    return vigilados, busquedas


def _procesar(con, capturas, reglas, notificador, config) -> int:
    """Guarda las capturas, evalúa y avisa. Devuelve cuántas alertas mandó."""
    ventana = config["historico"]["ventana_minimo_dias"]
    dias_minimos = config["historico"]["dias_minimos_para_descuento"]
    cooldown = config["alertas"]["cooldown_dias"]

    enviadas = 0
    for captura in capturas:
        try:
            producto_id = alta_o_actualiza_producto(con, captura)

            # El mínimo se consulta ANTES de insertar la captura de hoy: si no,
            # el precio actual sería su propio mínimo y el descuento siempre
            # cero.
            minimo = minimo_historico(con, producto_id, ventana)
            dias = dias_de_historico(con, producto_id)

            registrar_si_cambio(con, producto_id, captura)

            veredicto = evaluar(captura, reglas, minimo, dias, dias_minimos)
            if veredicto is None:
                continue
            anterior = ultima_alerta(con, producto_id, veredicto.regla)
            if not debe_notificar(anterior, veredicto.precio, cooldown):
                continue

            try:
                notificador.enviar(captura, veredicto)
            except Exception as error:
                # La captura ya está en el histórico, así que el dato no se
                # pierde. No se registra la alerta: el próximo ciclo volverá a
                # intentarlo.
                registro.warning(
                    "no se pudo avisar de %s (%s); se reintentará en el próximo ciclo",
                    captura.url,
                    error,
                )
                continue

            registrar_alerta(con, producto_id, veredicto.regla, veredicto.precio)
            enviadas += 1
        except Exception as error:  # noqa: BLE001
            # Con traza: este `except` es ancho a propósito, y sin el tipo y el
            # fichero un error nuestro se confundiría con una captura saltada.
            registro.warning(
                "no se pudo procesar %s: %s", captura.url, error, exc_info=True
            )
            continue

    return enviadas


def ejecutar_ciclo(con, fuentes, vigilados, busquedas, notificador, config) -> int:
    """Un ciclo completo. Un fallo de una tienda nunca detiene a las demás."""
    enviadas = 0

    for vigilado in vigilados:
        fuente = fuentes.get(vigilado["tienda"])
        if fuente is None:
            registro.warning("sin fuente para la tienda %r", vigilado["tienda"])
            continue
        try:
            capturas = fuente.obtener(
                [Referencia(tienda=vigilado["tienda"], url=vigilado["url"])]
            )
        except Exception as error:  # noqa: BLE001
            registro.warning("fuente %s falló: %s", fuente.nombre, error)
            continue
        enviadas += _procesar(con, capturas, vigilado["reglas"], notificador, config)

    limite = config.get("ejecucion", {}).get("limite_por_busqueda", 15)
    for busqueda in busquedas:
        fuente = fuentes.get(busqueda["tienda"])
        if fuente is None:
            registro.warning("sin fuente para la tienda %r", busqueda["tienda"])
            continue
        try:
            capturas = fuente.buscar(busqueda["termino"], limite)
        except Exception as error:  # noqa: BLE001
            registro.warning("búsqueda en %s falló: %s", fuente.nombre, error)
            continue
        enviadas += _procesar(con, capturas, busqueda["reglas"], notificador, config)

    return enviadas


def construir_notificador(config):
    if config["alertas"].get("canal", "archivo") == "telegram":
        return NotificadorTelegram(
            token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        )
    return NotificadorArchivo(RAIZ / config["alertas"]["ruta_archivo"])


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # urllib3 registra la ruta de cada petición en DEBUG, y la de Telegram
    # lleva el token incrustado. No depender del nivel por defecto.
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    load_dotenv(RAIZ / ".env")

    config = cargar_config(RAIZ / "config" / "config.yaml")
    vigilados, busquedas = cargar_lista_deseos(RAIZ / "config" / "lista_deseos.yaml")

    transporte = crear_transporte(
        reintentos=config["ejecucion"]["reintentos"],
        pausa=tuple(config["ejecucion"]["espera_entre_peticiones_seg"]),
    )
    fuentes = {"paris": Paris(transporte)}

    try:
        notificador = construir_notificador(config)
    except TelegramMalConfigurado as error:
        print(f"Error de configuración: {error}")
        return 1

    con = abrir(RAIZ / "data" / "tracker.db")
    enviadas = ejecutar_ciclo(con, fuentes, vigilados, busquedas, notificador, config)
    registro.info("ciclo terminado: %s alertas enviadas", enviadas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
