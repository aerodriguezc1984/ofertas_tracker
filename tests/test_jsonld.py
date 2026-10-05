"""La base hace el andamiaje; cada tienda pone tres ganchos."""

from fuentes.base import Candidato, Captura, Referencia
from fuentes.jsonld import FuenteJsonLd
from fuentes.transporte import TiendaBloqueada


def captura(sku="S1", url="https://t.cl/a.html"):
    return Captura(tienda="prueba", sku_externo=sku, titulo="X", url=url, precio_internet=1000)


class FuenteDePrueba(FuenteJsonLd):
    nombre = "prueba"
    BASE = "https://t.cl"

    def __init__(self, transporte, candidatos_fijos):
        super().__init__(transporte)
        self._fijos = candidatos_fijos

    def url_de_busqueda(self, termino):
        return f"{self.BASE}/buscar?q={termino}"

    def candidatos(self, html):
        return list(self._fijos)

    def captura_de_ficha(self, html, url):
        return captura(url=url) if html == "ficha" else None


def test_un_candidato_con_captura_no_cuesta_una_peticion_de_ficha():
    pedidas = []

    def traer(url):
        pedidas.append(url)
        return "busqueda"

    fuente = FuenteDePrueba(traer, [
        Candidato(referencia=Referencia("prueba", "https://t.cl/a.html"), captura=captura()),
    ])
    capturas = fuente.buscar("x", limite=5)

    assert len(capturas) == 1
    assert pedidas == ["https://t.cl/buscar?q=x"]  # solo la búsqueda


def test_un_candidato_sin_captura_provoca_la_peticion_de_su_ficha():
    pedidas = []

    def traer(url):
        pedidas.append(url)
        return "busqueda" if "buscar" in url else "ficha"

    fuente = FuenteDePrueba(traer, [
        Candidato(referencia=Referencia("prueba", "https://t.cl/a.html")),
    ])
    capturas = fuente.buscar("x", limite=5)

    assert len(capturas) == 1
    assert pedidas == ["https://t.cl/buscar?q=x", "https://t.cl/a.html"]


def test_la_base_deduplica_y_corta_por_limite():
    def traer(url):
        return "busqueda"

    repetido = Candidato(referencia=Referencia("prueba", "https://t.cl/a.html"), captura=captura())
    otro = Candidato(referencia=Referencia("prueba", "https://t.cl/b.html"), captura=captura(sku="S2", url="https://t.cl/b.html"))
    tercero = Candidato(referencia=Referencia("prueba", "https://t.cl/c.html"), captura=captura(sku="S3", url="https://t.cl/c.html"))

    capturas = FuenteDePrueba(traer, [repetido, repetido, otro, tercero]).buscar("x", limite=2)

    # Afirmar CUÁLES vuelven, no cuántos: sin deduplicado volverían dos veces
    # la misma y el recuento seguiría dando 2.
    assert [c.url for c in capturas] == ["https://t.cl/a.html", "https://t.cl/b.html"]


def test_un_limite_de_cero_no_elige_ningun_candidato():
    """El corte va antes de aceptar: `limite=0` no devuelve nada."""
    def traer(url):
        return "busqueda"

    uno = Candidato(referencia=Referencia("prueba", "https://t.cl/a.html"), captura=captura())
    assert FuenteDePrueba(traer, [uno]).buscar("x", limite=0) == []


def test_una_busqueda_bloqueada_devuelve_vacio():
    def traer(url):
        raise TiendaBloqueada("403")

    assert FuenteDePrueba(traer, []).buscar("x", limite=5) == []


def test_una_ficha_bloqueada_no_tumba_las_demas():
    def traer(url):
        if url.endswith("rota.html"):
            raise TiendaBloqueada("404")
        return "ficha"

    fuente = FuenteDePrueba(traer, [])
    capturas = fuente.obtener([
        Referencia("prueba", "https://t.cl/rota.html"),
        Referencia("prueba", "https://t.cl/buena.html"),
    ])
    assert len(capturas) == 1


def test_una_ficha_sin_datos_utilizables_se_descarta():
    fuente = FuenteDePrueba(lambda url: "vacia", [])
    assert fuente.obtener([Referencia("prueba", "https://t.cl/a.html")]) == []
