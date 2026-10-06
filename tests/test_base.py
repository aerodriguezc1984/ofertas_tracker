from fuentes.base import Candidato, Captura, Referencia


def test_una_captura_se_considera_etiquetada_por_defecto():
    """Solo las fuentes que infieren precios marcan lo contrario."""
    c = Captura(
        tienda="paris", sku_externo="S1", titulo="N",
        url="https://www.paris.cl/n-S1.html", precio_internet=1000,
    )
    assert c.precios_etiquetados is True


def test_un_candidato_puede_no_traer_captura():
    """Paris devuelve enlaces que hay que seguir; Falabella, datos ya leídos."""
    c = Candidato(referencia=Referencia(tienda="paris", url="https://www.paris.cl/n-S1.html"))
    assert c.captura is None
