"""Comprueba que las alertas llegan a Telegram, antes de confiarle el ciclo.

No es una prueba automática: toca la red y depende de que exista un bot tuyo.
Se ejecuta a mano, una vez, al enlazar la cuenta.

    python herramientas/sonda_telegram.py

Hace tres cosas, en este orden:

1. Lee `TELEGRAM_BOT_TOKEN` del `.env`. Si falta, te dice cómo conseguirlo.
2. Si falta `TELEGRAM_CHAT_ID`, se lo pregunta a Telegram —de los mensajes que
   ya le mandaste al bot— y lo deja escrito en el `.env`. El chat_id no es un
   secreto: es el número de tu conversación.
3. Manda un mensaje de prueba con el formato real de una alerta.

**El token nunca se imprime**, ni en los mensajes de error. Va dentro de la URL
de cada petición, así que el texto de una excepción de `requests` lo arrastra:
por eso aquí solo se conserva el NOMBRE del tipo de la excepción, igual que en
`avisos/telegram.py`.
"""

import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

RAIZ = Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from avisos.telegram import NotificadorTelegram, TelegramMalConfigurado  # noqa: E402
from nucleo.comparacion import (  # noqa: E402
    OfertaAjena,
    ProductoVigilado,
    VeredictoMejorPrecio,
)

ENV = RAIZ / ".env"

# Un token de BotFather son <id del bot>:<35 caracteres>. Comprobar la forma
# antes de preguntarle a Telegram convierte el error más común —un espacio que
# se coló al copiar— en un mensaje que dice qué pasa, en vez de un 404 que
# parece otra cosa.
FORMA_DEL_TOKEN = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{30,45}")

PRODUCTO_DE_PRUEBA = ProductoVigilado(
    id=0,
    tienda="paris",
    sku_externo="000000000",
    titulo="PRUEBA — esto no es una oferta real",
    url="https://www.paris.cl/",
    precio_internet=499990,
    producto_solotodo=None,
)

VEREDICTO_DE_PRUEBA = VeredictoMejorPrecio(
    oferta=OfertaAjena(
        tienda="winpy", precio=399990, url="https://www.winpy.cl/", disponible=True
    ),
    ahorro=100000,
    porcentaje=20.0,
)


def _pedir_chat_id(token: str) -> tuple[str | None, str]:
    """Devuelve (chat_id, motivo). El motivo distingue POR QUÉ no lo hay.

    Que no haya chat_id tiene tres causas muy distintas —la red, el token, o que
    todavía no le hayas escrito al bot— y cada una se arregla de otra forma.
    Devolverlas todas como `None` obliga a quien llama a adivinar, y adivinar en
    un mensaje de error es cómo se manda a alguien a mirar al sitio equivocado.
    """
    tipo_de_fallo = None
    try:
        respuesta = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates", timeout=30
        )
        datos = respuesta.json()
    except Exception as error:
        tipo_de_fallo = type(error).__name__
    if tipo_de_fallo is not None:
        # Fuera del `except` para que la excepción nueva no encadene la vieja,
        # cuyo texto lleva la URL —y la URL lleva el token—.
        return None, f"red:{tipo_de_fallo}"

    if not datos.get("ok"):
        # `description` viene de Telegram y no incluye la URL.
        return None, f"rechazado:{datos.get('description')}"

    for actualizacion in reversed(datos.get("result") or []):
        mensaje = actualizacion.get("message") or actualizacion.get("channel_post") or {}
        chat = mensaje.get("chat") or {}
        if chat.get("id") is not None:
            return str(chat["id"]), "ok"
    return None, "sin_conversacion"


def _guardar_chat_id(chat_id: str) -> None:
    """Escribe el chat_id en el `.env` sin tocar el resto del archivo."""
    lineas = ENV.read_text(encoding="utf-8").splitlines()
    salida, puesto = [], False
    for linea in lineas:
        if linea.startswith("TELEGRAM_CHAT_ID="):
            salida.append(f"TELEGRAM_CHAT_ID={chat_id}")
            puesto = True
        else:
            salida.append(linea)
    if not puesto:
        salida.append(f"TELEGRAM_CHAT_ID={chat_id}")
    ENV.write_text("\n".join(salida) + "\n", encoding="utf-8")


def main() -> int:
    if not ENV.exists():
        print(f"FALLA: no existe {ENV}.")
        print("Copia .env.example a .env y pega ahí el token del bot.")
        return 1

    load_dotenv(ENV)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("FALTA EL TOKEN.")
        print()
        print("  1. En Telegram, habla con @BotFather y manda /newbot")
        print("  2. Copia el token que te dé (algo como 8123456789:AAF...)")
        print(f"  3. Pégalo en {ENV}, en la línea TELEGRAM_BOT_TOKEN=")
        print()
        print("Después vuelve a ejecutar esta sonda.")
        return 1

    if not FORMA_DEL_TOKEN.fullmatch(token):
        print("EL TOKEN NO TIENE LA FORMA DE UN TOKEN DE TELEGRAM.")
        print()
        print("  Se esperaba <id del bot>:<35 caracteres>, por ejemplo")
        print("  8123456789:AAF... — en total 46 caracteres, sin espacios.")
        print(f"  Lo que hay en el .env tiene {len(token)} caracteres.")
        print()
        print("Lo más común es que se colara un espacio o un salto de línea al")
        print("copiarlo desde el mensaje de BotFather, o que falte un trozo.")
        return 1

    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        print("Falta el chat_id. Se lo pregunto a Telegram...")
        chat_id, motivo = _pedir_chat_id(token)
        if motivo.startswith("red:"):
            print(f"FALLA: no se pudo hablar con Telegram ({motivo.split(':', 1)[1]}).")
            print("Es un problema de conexión, no del token ni del bot.")
            return 1
        if motivo.startswith("rechazado:"):
            print(f"FALLA: Telegram rechazó el token: {motivo.split(':', 1)[1]!r}")
            print()
            print("El token tiene la forma correcta pero no corresponde a ningún")
            print("bot. Vuelve a copiarlo entero desde BotFather: si el bot se")
            print("borró o regeneraste el token, el viejo deja de valer.")
            return 1
        if motivo == "sin_conversacion":
            print()
            print("El token es válido, pero no hay ninguna conversación con el bot.")
            print("Búscalo en Telegram por su usuario, mándale un «hola», y repite.")
            return 1
        _guardar_chat_id(chat_id)
        os.environ["TELEGRAM_CHAT_ID"] = chat_id
        print(f"OK: chat_id {chat_id}, guardado en .env\n")

    try:
        notificador = NotificadorTelegram(token=token, chat_id=chat_id)
    except TelegramMalConfigurado as error:
        print(f"FALLA: {error}")
        return 1

    print("Mandando un mensaje de prueba con el formato real de una alerta...")
    try:
        notificador.enviar_mejor_precio(PRODUCTO_DE_PRUEBA, VEREDICTO_DE_PRUEBA)
    except Exception as error:
        # `EnvioFallido` ya viene limpio de token; cualquier otra se reduce a su
        # tipo por si acaso.
        print(f"FALLA: {type(error).__name__}: {error}")
        return 1

    print()
    print("OK: mírate Telegram. Si te llegó, ya puedes poner en config.yaml:")
    print("    alertas:")
    print("      canal: telegram")
    print()
    print("Ojo: el canal es uno u otro. Con telegram, logs/alertas.jsonl deja")
    print("de llenarse.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
