"""Decide si una captura es una oferta según las reglas del producto."""

from dataclasses import dataclass

from fuentes.base import Captura


@dataclass(frozen=True)
class Reglas:
    precio_maximo: int | None = None
    descuento_minimo_pct: float | None = None
    permitir_precio_tarjeta: bool = False


@dataclass(frozen=True)
class Veredicto:
    regla: str
    precio: int
    motivo: str


def pesos(cantidad: int) -> str:
    """89990 -> '$89.990', como se escribe en Chile."""
    return "$" + f"{cantidad:,}".replace(",", ".")


def precio_aplicable(captura: Captura, reglas: Reglas) -> int:
    """El precio que el usuario considera pagable.

    Por defecto solo cuenta el que paga cualquiera: una oferta que exige la
    tarjeta de la casa no es una oferta si no tienes esa tarjeta.
    """
    if reglas.permitir_precio_tarjeta and captura.precio_tarjeta is not None:
        return min(captura.precio_internet, captura.precio_tarjeta)
    return captura.precio_internet


def evaluar(
    captura: Captura,
    reglas: Reglas,
    minimo_historico: int | None,
    dias_historico: float,
    dias_minimos: int,
) -> Veredicto | None:
    """El veredicto, o None si la captura no es una oferta."""
    if not captura.disponible:
        return None

    precio = precio_aplicable(captura, reglas)

    if reglas.precio_maximo is not None and precio <= reglas.precio_maximo:
        return Veredicto(
            regla="precio_maximo",
            precio=precio,
            motivo=f"{pesos(precio)}, por debajo de tu tope de {pesos(reglas.precio_maximo)}",
        )

    # La guarda de arranque en frío: sin histórico suficiente, el mínimo es el
    # propio precio de hoy y el descuento no significa nada.
    if (
        reglas.descuento_minimo_pct is not None
        and minimo_historico
        and dias_historico >= dias_minimos
    ):
        caida = (minimo_historico - precio) / minimo_historico * 100
        if caida >= reglas.descuento_minimo_pct:
            return Veredicto(
                regla="descuento_minimo_pct",
                precio=precio,
                motivo=f"{caida:.0f} % por debajo de su mínimo histórico",
            )

    return None
