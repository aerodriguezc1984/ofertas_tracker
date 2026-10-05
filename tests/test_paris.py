from pathlib import Path

from fuentes.base import Referencia
from fuentes.paris import Paris
from fuentes.transporte import TiendaBloqueada

FIXTURES = Path(__file__).parent / "fixtures"
FICHA = (FIXTURES / "paris_ficha.html").read_text(encoding="utf-8")
BUSQUEDA = (FIXTURES / "paris_busqueda.html").read_text(encoding="utf-8")
URL_FICHA = "https://www.paris.cl/home-panel-monaco-MK2GCAHDUR.html"

UNO = "https://www.paris.cl/apple-macbook-air-chip-m5-16gb-ram-512gb-ssd-13-plata-422566999.html"
DOS = "https://www.paris.cl/notebook-15-fc0250la-amd-ryzen-5-8gb-ram-512gb-ssd-156-fhd-512134999.html"
TRES = "https://www.paris.cl/rack-atenas-nogal-851304999.html"


def transporte_de(mapa):
    """Transporte falso: devuelve lo que diga el mapa para cada URL."""

    def traer(url):
        if url not in mapa:
            raise TiendaBloqueada(f"sin fixture para {url}")
        return mapa[url]

    return traer


def test_obtener_devuelve_la_captura():
    paris = Paris(transporte_de({URL_FICHA: FICHA}))
    capturas = paris.obtener([Referencia(tienda="paris", url=URL_FICHA)])
    assert len(capturas) == 1
    assert capturas[0].sku_externo == "MK2GCAHDUR"
    assert capturas[0].precio_internet == 229990
    assert capturas[0].tienda == "paris"


def test_una_ficha_bloqueada_no_tumba_las_demas():
    paris = Paris(transporte_de({URL_FICHA: FICHA}))
    capturas = paris.obtener([
        Referencia(tienda="paris", url="https://www.paris.cl/no-existe.html"),
        Referencia(tienda="paris", url=URL_FICHA),
    ])
    assert len(capturas) == 1


def test_buscar_extrae_las_fichas_sin_repetir():
    mapa = {
        "https://www.paris.cl/search?q=notebook": BUSQUEDA,
        UNO: FICHA, DOS: FICHA, TRES: FICHA,
    }
    pedidas = []

    def traer(url):
        pedidas.append(url)
        return mapa[url]

    capturas = Paris(traer).buscar("notebook", limite=10)
    # tres fichas distintas: el enlace repetido y /ayuda/ se descartan
    assert len(capturas) == 3
    assert len(pedidas) == 4  # una búsqueda + tres fichas


def test_buscar_respeta_el_limite():
    mapa = {"https://www.paris.cl/search?q=notebook": BUSQUEDA, UNO: FICHA}
    capturas = Paris(lambda u: mapa[u]).buscar("notebook", limite=1)
    assert len(capturas) == 1


def test_el_termino_se_codifica():
    pedidas = []

    def traer(url):
        pedidas.append(url)
        return "<html></html>"

    Paris(traer).buscar("notebook 16 gb", limite=5)
    assert pedidas[0] == "https://www.paris.cl/search?q=notebook+16+gb"


def test_una_busqueda_bloqueada_devuelve_vacio():
    def traer(url):
        raise TiendaBloqueada("403")

    assert Paris(traer).buscar("notebook", limite=5) == []
