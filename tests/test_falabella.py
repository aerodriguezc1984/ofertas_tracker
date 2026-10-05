from pathlib import Path

from fuentes.base import Referencia
from fuentes.falabella import Falabella

FIXTURES = Path(__file__).parent / "fixtures"
BUSQUEDA = (FIXTURES / "falabella_busqueda.html").read_text(encoding="utf-8")
FICHA = (FIXTURES / "falabella_ficha.html").read_text(encoding="utf-8")

TRES = "https://www.falabella.com/falabella-cl/product/80676157/notebook-tres/80676157"
DOS = "https://www.falabella.com/falabella-cl/product/80726514/notebook-dos/80726514"


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


def test_una_ficha_cuyo_json_ld_describe_otro_producto_se_descarta():
    """Si el Product no es el de la URL, su sku arrastraría el anclaje."""
    ajena = FICHA.replace('"sku":"80676157","name"', '"sku":"77777777","name"')
    assert Falabella(lambda u: ajena).obtener([Referencia("falabella", TRES)]) == []
