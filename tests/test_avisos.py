# tests/test_avisos.py
import json

import pytest

from avisos.archivo import NotificadorArchivo
from avisos.base import redactar, redactar_mejor_precio
from avisos.telegram import EnvioFallido, NotificadorTelegram, TelegramMalConfigurado
from fuentes.base import Captura
from nucleo.comparacion import OfertaAjena, ProductoVigilado, VeredictoMejorPrecio
from nucleo.evaluador import Veredicto

CAPTURA = Captura(
    tienda="paris", sku_externo="S1", titulo="Notebook Lenovo",
    url="https://www.paris.cl/n-S1.html", precio_internet=89990, precio_normal=129990,
)
VEREDICTO = Veredicto(regla="precio_maximo", precio=89990, motivo="por debajo de tu tope")

PRODUCTO = ProductoVigilado(
    id=1,
    tienda="paris",
    sku_externo="106450999",
    titulo="Notebook IdeaPad Slim 3",
    url="https://www.paris.cl/notebook-106450999.html",
    precio_internet=499990,
    producto_solotodo=269594,
)

VEREDICTO_MEJOR_PRECIO = VeredictoMejorPrecio(
    oferta=OfertaAjena(
        tienda="winpy", precio=399990, url="https://www.winpy.cl/venta/notebook/"
    ),
    ahorro=100000,
    porcentaje=20.0,
)


def test_el_mensaje_lleva_lo_imprescindible():
    texto = redactar(CAPTURA, VEREDICTO)
    assert "Notebook Lenovo" in texto
    assert "89.990" in texto          # formato chileno, con punto de miles
    assert "paris" in texto.lower()
    assert CAPTURA.url in texto


def test_el_notificador_de_archivo_escribe_una_linea_json(tmp_path):
    ruta = tmp_path / "alertas.jsonl"
    NotificadorArchivo(ruta).enviar(CAPTURA, VEREDICTO)
    NotificadorArchivo(ruta).enviar(CAPTURA, VEREDICTO)

    lineas = ruta.read_text(encoding="utf-8").strip().splitlines()
    assert len(lineas) == 2
    registro = json.loads(lineas[0])
    assert registro["precio"] == 89990
    assert registro["url"] == CAPTURA.url


def test_telegram_sin_token_falla_al_construirse():
    """Mejor estallar al arrancar que a mitad del ciclo."""
    with pytest.raises(TelegramMalConfigurado):
        NotificadorTelegram(token="", chat_id="123")


def test_telegram_envia_el_mensaje():
    enviados = []

    class SesionFalsa:
        def post(self, url, json=None, timeout=None):
            enviados.append((url, json))

            class R:
                status_code = 200

            return R()

    NotificadorTelegram("secreto", "123", sesion=SesionFalsa()).enviar(CAPTURA, VEREDICTO)
    url, cuerpo = enviados[0]
    assert url.endswith("/sendMessage")
    assert cuerpo["chat_id"] == "123"
    assert "Notebook Lenovo" in cuerpo["text"]


def test_telegram_no_filtra_el_token_en_el_error():
    class SesionFalsa:
        def post(self, url, json=None, timeout=None):
            class R:
                status_code = 401

            return R()

    notificador = NotificadorTelegram("SECRETO-QUE-NO-DEBE-SALIR", "123", sesion=SesionFalsa())
    with pytest.raises(EnvioFallido) as error:
        notificador.enviar(CAPTURA, VEREDICTO)
    assert "SECRETO-QUE-NO-DEBE-SALIR" not in str(error.value)


def test_telegram_no_filtra_el_token_cuando_falla_la_red():
    """Las excepciones de requests llevan la URL, y la URL lleva el token."""
    TOKEN = "SECRETO-QUE-NO-DEBE-SALIR"

    class SesionQueFalla:
        def post(self, url, json=None, timeout=None):
            raise ConnectionError(
                f"HTTPSConnectionPool(host='api.telegram.org', port=443): "
                f"Max retries exceeded with url: /bot{TOKEN}/sendMessage"
            )

    notificador = NotificadorTelegram(TOKEN, "123", sesion=SesionQueFalla())
    with pytest.raises(EnvioFallido) as error:
        notificador.enviar(CAPTURA, VEREDICTO)

    assert TOKEN not in str(error.value)
    assert TOKEN not in repr(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None or TOKEN not in str(error.value.__context__)


def test_el_aviso_nombra_las_dos_tiendas_y_el_ahorro():
    texto = redactar_mejor_precio(PRODUCTO, VEREDICTO_MEJOR_PRECIO)
    assert "paris" in texto
    assert "winpy" in texto
    assert "$499.990" in texto
    assert "$399.990" in texto
    assert "$100.000" in texto


def test_el_aviso_enlaza_a_la_tienda_ajena_no_a_la_nuestra():
    """El enlace útil es el de donde está barato, no el de donde ya miramos."""
    texto = redactar_mejor_precio(PRODUCTO, VEREDICTO_MEJOR_PRECIO)
    assert VEREDICTO_MEJOR_PRECIO.oferta.url in texto
    assert PRODUCTO.url not in texto


def test_el_aviso_dice_de_donde_sale_el_precio_ajeno():
    """Nuestro precio es de hoy; el ajeno es de SoloTodo y puede ir rezagado."""
    assert "SoloTodo" in redactar_mejor_precio(PRODUCTO, VEREDICTO_MEJOR_PRECIO)


def test_el_notificador_de_archivo_escribe_el_aviso_de_mejor_precio(tmp_path):
    ruta = tmp_path / "alertas.jsonl"
    NotificadorArchivo(ruta).enviar_mejor_precio(PRODUCTO, VEREDICTO_MEJOR_PRECIO)

    linea = json.loads(ruta.read_text(encoding="utf-8").strip())
    assert linea["regla"] == "mejor_precio"
    assert linea["tienda"] == "paris"
    assert linea["tienda_ajena"] == "winpy"
    assert linea["precio"] == 399990
    assert linea["url"] == VEREDICTO_MEJOR_PRECIO.oferta.url


def test_un_fallo_al_redactar_no_se_disfraza_de_fallo_de_red():
    """Un error construyendo el mensaje no es un problema de conexión."""

    class CapturaRota:
        tienda = "paris"
        titulo = "Notebook"
        url = "https://www.paris.cl/n-S1.html"
        precio_internet = 1000

        @property
        def precio_normal(self):
            raise RuntimeError("fallo al redactar")

    class SesionQueNoDebeUsarse:
        def post(self, url, json=None, timeout=None):
            raise AssertionError("no se debió llegar a la red")

    notificador = NotificadorTelegram("T", "123", sesion=SesionQueNoDebeUsarse())
    with pytest.raises(RuntimeError, match="fallo al redactar"):
        notificador.enviar(CapturaRota(), VEREDICTO)
