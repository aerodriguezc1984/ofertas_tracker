from pathlib import Path

from fuentes.base import Referencia
from fuentes.falabella import Falabella

FIXTURES = Path(__file__).parent / "fixtures"
BUSQUEDA = (FIXTURES / "falabella_busqueda.html").read_text(encoding="utf-8")
FICHA = (FIXTURES / "falabella_ficha.html").read_text(encoding="utf-8")
FICHA_VARIANTE = (FIXTURES / "falabella_ficha_variante.html").read_text(encoding="utf-8")

TRES = "https://www.falabella.com/falabella-cl/product/80676157/notebook-tres/80676157"
DOS = "https://www.falabella.com/falabella-cl/product/80726514/notebook-dos/80726514"
VARIANTE = "https://www.falabella.com/falabella-cl/product/80725439/mb-neo-13"


def test_la_url_de_busqueda_usa_el_parametro_de_falabella():
    pedidas = []

    def traer(url):
        pedidas.append(url)
        return "<html></html>"

    Falabella(traer).buscar("notebook 16gb", limite=5)
    assert pedidas[0] == (
        "https://www.falabella.com/falabella-cl/search?Ntt=notebook+16gb"
    )


def test_la_busqueda_no_pide_ninguna_ficha():
    """El ItemList ya trae los productos: una petición, no dieciséis."""
    pedidas = []

    def traer(url):
        pedidas.append(url)
        return BUSQUEDA

    capturas = Falabella(traer).buscar("notebook", limite=10)
    assert len(capturas) == 2
    assert len(pedidas) == 1


def test_el_sku_sale_de_la_url():
    capturas = Falabella(lambda u: BUSQUEDA).buscar("notebook", limite=10)
    assert [c.sku_externo for c in capturas] == ["80676157", "80726514"]


def test_con_tres_ofertas_la_mas_barata_es_la_de_tarjeta():
    c = Falabella(lambda u: BUSQUEDA).buscar("notebook", limite=10)[0]
    assert c.precio_tarjeta == 419990
    assert c.precio_internet == 439990
    assert c.precio_normal == 549990
    assert c.tarjeta == "CMR"


def test_con_dos_ofertas_no_hay_precio_de_tarjeta():
    c = Falabella(lambda u: BUSQUEDA).buscar("notebook", limite=10)[1]
    assert c.precio_tarjeta is None
    assert c.tarjeta is None
    assert c.precio_internet == 679990
    assert c.precio_normal == 1069990


def test_los_precios_de_la_busqueda_quedan_marcados_como_inferidos():
    """Nada de lo que salga de aquí puede alertar sin confirmarse."""
    capturas = Falabella(lambda u: BUSQUEDA).buscar("notebook", limite=10)
    assert all(c.precios_etiquetados is False for c in capturas)


def test_un_producto_sin_sku_en_la_url_se_descarta():
    html = (
        '<script type="application/ld+json">'
        '{"@type":"ItemList","itemListElement":[{"@type":"ListItem","item":'
        '{"@type":"Product","name":"Sin sku","url":"https://www.falabella.com/raro",'
        '"offers":[{"price":"1000"},{"price":"2000"}]}}]}'
        "</script>"
    )
    assert Falabella(lambda u: html).buscar("x", limite=5) == []


def test_la_ficha_ancla_los_precios_al_sku_correcto():
    """La fixture trae antes un bloque de promoción de OTRO producto.

    Si el anclaje falla, salen 299.990 / 319.990 / 429.990, que son de un
    producto distinto. Es el fallo que no rompe nada: solo miente.
    """
    c = Falabella(lambda u: FICHA).obtener([Referencia("falabella", TRES)])[0]
    assert c.precio_tarjeta == 419990
    assert c.precio_internet == 439990
    assert c.precio_normal == 549990
    assert c.tarjeta == "CMR"


def test_la_ficha_da_precios_etiquetados():
    c = Falabella(lambda u: FICHA).obtener([Referencia("falabella", TRES)])[0]
    assert c.precios_etiquetados is True


def test_la_ficha_toma_titulo_sku_y_stock_del_json_ld():
    c = Falabella(lambda u: FICHA).obtener([Referencia("falabella", TRES)])[0]
    assert c.titulo == 'Notebook 15,6" Full HD'
    assert c.sku_externo == "80676157"
    assert c.disponible is True
    assert c.ean is None          # el gtin13 vale la cadena "null"


def test_una_ficha_sin_bloque_anclado_se_descarta():
    """Mejor ninguna captura que la del producto de al lado."""
    solo_promo = FICHA.replace('"sellerSkuId":"80676157"', '"sellerSkuId":"11111111"')
    assert Falabella(lambda u: solo_promo).obtener([Referencia("falabella", TRES)]) == []


def test_una_ficha_cuyo_json_ld_pertenece_a_otra_url_se_descarta():
    """La identidad la da el `@id` del bloque, no su sku.

    Si el bloque dice pertenecer a otra ficha —el carrusel de al lado—, usarlo
    guardaría el producto equivocado bajo la URL vigilada. No falla: miente.

    El sku NO sirve para esto desde que Falabella publica en la ficha la
    variante por defecto, cuyo sku no es el id de la URL. Ver
    `test_una_ficha_cuya_variante_cambia_el_sku_se_captura_igual`.
    """
    ajena = FICHA.replace("/product/80676157/notebook-tres", "/product/99999999/otro")
    assert Falabella(lambda u: ajena).obtener([Referencia("falabella", TRES)]) == []


def test_una_ficha_cuya_variante_cambia_el_sku_se_captura_igual():
    """Falabella sirve en el JSON-LD la variante por defecto, no el id de la URL.

    La ficha de `/product/80725439/...` declara `sku: 80725441`, que es otra
    variante del mismo artículo. Antes la guarda comparaba ese sku contra el id
    de la URL y descartaba la ficha entera: Falabella dejó de confirmarse y, con
    ello, de alertar y de compararse.
    """
    c = Falabella(lambda u: FICHA_VARIANTE).obtener([Referencia("falabella", VARIANTE)])[0]
    assert c.precio_internet == 759990
    assert c.precio_normal == 869990
    assert c.precios_etiquetados is True


def test_la_identidad_se_mantiene_en_el_id_de_la_url_y_no_en_el_de_la_variante():
    """El sku guardado es el de la URL, que es como se descubrió el producto.

    Si la ficha impusiera el sku de la variante, el mismo artículo tendría dos
    identidades —una por la búsqueda y otra por la ficha— y chocaría contra el
    UNIQUE de `productos.url` al darse de alta por segunda vez.
    """
    c = Falabella(lambda u: FICHA_VARIANTE).obtener([Referencia("falabella", VARIANTE)])[0]
    assert c.sku_externo == "80725439"
