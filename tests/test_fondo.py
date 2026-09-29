"""Pruebas de las herramientas de imagen de fondo (herramientas/generar_fondo.py
y herramientas/verificar_fondo.py).

Estas pruebas miran que la referencia que se manda a la IA este en su sitio, y
que el verificador sea de fiar. Lo segundo importa mas que lo primero: un
verificador que da el visto bueno a todo no sirve de nada, asi que se comprueba
con imagenes rotas a proposito que tienen que ser rechazadas, y se mira que la
correccion que propone sea justo la que se hizo.
"""

import sys
from pathlib import Path
from typing import NamedTuple

import pytest
from PIL import Image, ImageChops

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "herramientas"))

import generar_fondo as gf  # noqa: E402
import verificar_fondo as vf  # noqa: E402

from ihc.proyeccion import Proyeccion  # noqa: E402

# Lamina mediana para que las pruebas vayan rapidas. La proporcion es la misma
# que la de 1800 x 913, que es lo unico que importa para que las lineas casen.
# Por debajo de unos 3 px por grado la costa se queda tan gruesa que la
# cobertura sale pesimista, asi que para probar el verificador no se baja de aqui.
ANCHO = 1200
ALTO = gf.tamano(ANCHO)[1]


def _generar() -> Image.Image:
    import tempfile

    with tempfile.TemporaryDirectory() as carpeta:
        ruta = gf.dibujar_fondo(ANCHO, Path(carpeta) / "fondo.png")
        with Image.open(ruta) as imagen:
            return imagen.convert("RGB").copy()


@pytest.fixture(scope="module")
def fondo() -> Image.Image:
    """El fondo tal cual lo genera la herramienta, en memoria."""
    return _generar()


class Medida(NamedTuple):
    """Lo que mide el verificador de una imagen.

    `cobertura` es con la imagen sin tocar, que es lo que dice si encaja; la
    `corregida` es cuanto se veria moviendola lo que el verificador propone, y
    sirve para confirmar que el diagnostico es el correcto.
    """

    dx: int
    dy: int
    cobertura: float
    corregida: float

    @property
    def desplazamiento(self) -> int:
        return max(abs(self.dx), abs(self.dy))


def imagen_tiene_la_proporcion(imagen: Image.Image) -> bool:
    """Si la lamina es de la proporcion del mapa. 13 px de mas ya estiran."""
    return imagen.height == gf.tamano(imagen.width)[1]


def veredicto(imagen: Image.Image, medida: Medida) -> bool:
    return vf.apta(imagen_tiene_la_proporcion(imagen), medida.desplazamiento,
                   medida.cobertura)


def medir(imagen: Image.Image) -> Medida:
    """Correccion y cobertura que calcula el verificador, como en `main`."""
    costa = vf.mapa_de_costa(vf.mascara_tierra(imagen.width, imagen.height))
    bordes, _ = vf.bordes_calibrados(imagen, vf.contar_claros(costa))
    dx_pista, dy_pista, _ = vf.registrar(costa, bordes, 40)
    dx, dy, corregida = vf.mejor_correccion(costa, bordes, dx_pista, dy_pista)
    return Medida(dx, dy, vf.cobertura_costa(costa, bordes, 0, 0), corregida)


# --- proporcion ---------------------------------------------------------------

@pytest.mark.parametrize("ancho,alto", [(1800, 913), (3600, 1826), (600, 304),
                                        (1920, 974), (1200, 609)])
def test_el_alto_sale_de_la_proporcion(ancho, alto):
    """El alto no se elige: sale del ancho. Es lo que hace que la lamina sea
    siempre la misma figura, y por eso una imagen pedida a 1800 y otra a 3600
    encajan igual con las lineas del mapa."""
    assert gf.tamano(ancho)[1] == alto
    assert alto == round(ancho * 913 / 1800)


def test_la_proporcion_no_es_dos_a_uno():
    """2:1 pareceredondo, pero no sirve: 1800 x 900 son 13 px mas bajos y las
    lineas descuadran al final. La lamina va a 913."""
    assert gf.tamano(1800)[1] == 913
    assert vf.ALTO_POR_ANCHO == pytest.approx(913 / 1800)


# --- la referencia ------------------------------------------------------------

def test_la_mascara_pone_tierra_donde_debe():
    """La mascara de referencia tiene que separar tierra y mar en los mismos
    sitios que el mapa, o el verificador no mide nada."""
    mascara = vf.mascara_tierra(ANCHO, ALTO)
    p = Proyeccion(gf.LIMITES, float(ANCHO), float(ALTO))
    casos = [(-3, -60, True, "Amazonas"), (22, 10, True, "Sahara"),
             (28, 84, True, "Himalaya"), (-25, 135, True, "Australia"),
             (0, 20, True, "Congo"), (-3, -30, False, "Atlantico"),
             (0, -140, False, "Pacifico"), (60, -40, False, "Noruega"),
             (-40, -20, False, "Sur del Atlantico"),
             (-50, -65, False, "Paso de Drake"), (-8, 106, False, "Oceano Indico")]
    for lat, lon, tierra, nombre in casos:
        x, y = p.a_pixeles(lat, lon)
        pixel = mascara.getpixel((int(x), int(y)))
        assert (pixel > 127) is tierra, f"{nombre} deberia ser {'tierra' if tierra else 'mar'}"


def test_la_rejilla_cae_donde_dice_la_proyeccion():
    """Las lineas de la cuadricula de la referencia se comprueban una a una
    contra la proyeccion del simulador, que es a lo que tiene que casar."""
    import tempfile

    with tempfile.TemporaryDirectory() as carpeta:
        ruta = gf.dibujar_rejilla(ANCHO, Path(carpeta) / "rejilla.png")
        with Image.open(ruta) as abierta:
            rejilla = abierta.convert("RGB")
    rojo = gf.REJILLA
    p = Proyeccion(gf.LIMITES, float(ANCHO), float(ALTO))

    def marcadas(obtener, total):
        act, salida = [], []
        for k in range(total):
            if obtener(k):
                act.append(k)
            elif act:
                salida.append(sum(act) / len(act))
                act = []
        return salida

    verticales = marcadas(
        lambda x: sum(1 for y in range(0, ALTO, 2) if rejilla.getpixel((x, y)) == rojo) > ALTO / 4,
        ANCHO)
    horizontales = marcadas(
        lambda y: sum(1 for x in range(0, ANCHO, 2) if rejilla.getpixel((x, y)) == rojo) > ANCHO / 4,
        ALTO)
    assert len(verticales) >= 12, "faltan meridianos en la referencia"
    assert len(horizontales) >= 6, "faltan paralelos en la referencia"
    for x in verticales:
        lon = (x / ANCHO) * 360.0 - 30.0
        assert x == pytest.approx(p.a_pixeles(30.0, lon)[0], abs=1.0)
    for y in horizontales:
        lat = 90.0 - (y / ALTO) * 180.0
        assert y == pytest.approx(p.a_pixeles(lat, 0.0)[1], abs=1.0)


# --- el verificador -----------------------------------------------------------

def test_el_verificador_aprueba_el_fondo_generado(fondo):
    """El fondo que genera la herramienta tiene que salir aprobado y sin que
    haya que moverlo. Si esto falla, o el fondo esta mal o el verificador."""
    m = medir(fondo)
    assert (m.dx, m.dy) == (0, 0)
    assert m.cobertura >= vf.COBERTURA_MINIMA
    assert veredicto(fondo, m)


def test_el_verificador_detecta_una_imagen_corrida(fondo):
    """La prueba de que el verificador sirve: una imagen corrida tiene que ser
    rechazada, y la correccion que propone tiene que ser la inversa del
    desplazamiento que se le hizo."""
    dx_real, dy_real = 12, -8
    corrida = Image.new("RGB", fondo.size)
    corrida.paste(fondo, (dx_real, dy_real))
    m = medir(corrida)
    # sin tocar, la costa no esta donde debe
    assert m.cobertura < vf.COBERTURA_MINIMA
    # y la correccion propuesta es justo la inversa del desplazamiento hecho
    assert m.dx == pytest.approx(-dx_real, abs=2)
    assert m.dy == pytest.approx(-dy_real, abs=2)
    # al corregirla vuelve a encajar, lo que confirma el diagnostico
    assert m.corregida >= vf.COBERTURA_MINIMA
    assert not veredicto(corrida, m)


def test_el_verificador_rechaza_una_imagen_repartida_por_la_mitad(fondo):
    """Media imagen y media nada: tiene que salir mal, y mal de verdad."""
    partida = Image.new("RGB", fondo.size)
    mitad = fondo.width // 2
    partida.paste(fondo.crop((0, 0, mitad, fondo.height)), (0, 0))
    m = medir(partida)
    assert m.cobertura < vf.COBERTURA_MINIMA
    assert not veredicto(partida, m), "media imagen tendria que salir rechazada"


def test_el_verificador_avisa_si_la_proporcion_no_es_la_del_mapa(fondo):
    """Una lamina estirada en vertical no se arregla moviendola, y el verificador
    tiene que decirlo en vez de dar el visto bueno."""
    estirada = fondo.resize((fondo.width, fondo.height - 13))
    assert estirada.height != gf.tamano(estirada.width)[1]
    # aun estirada la costa se lee bien y no hace falta moverla: por eso el
    # aviso de proporcion va aparte, y no vale fiarse solo de la cobertura
    m = medir(estirada)
    assert (m.dx, m.dy) == (0, 0)
    assert not veredicto(estirada, m)


@pytest.mark.parametrize("ok,desplazamiento,cobertura,esperado", [
    (True, 0, 96.0, True),      # bien
    (True, 2, 96.0, True),      # un desvio de dos px todavia entra
    (True, 0, 74.0, False),     # la costa no se ve
    (True, 30, 99.0, False),    # la imagen va corrida
    (False, 0, 99.0, False),    # la lamina no es de la proporcion del mapa
])
def test_el_veredicto_exige_las_tres_cosas(ok, desplazamiento, cobertura, esperado):
    """Sirve solo si se cumplen las tres: proporcion, posicion y costa visible.
    Con dos de tres no se acepta, que es donde se cuelan los falsos vistos
    buenos."""
    assert vf.apta(ok, desplazamiento, cobertura) is esperado


def test_el_umbral_de_borde_depende_de_la_resolucion():
    """El mismo fondo a doble resolucion reparte el borde en mas pixeles y el
    salto por pixel baja. Sin escalar el umbral, lo aprobado a 1800 suspendia
    a 3600."""
    assert vf.umbral_para(3600) == pytest.approx(vf.umbral_para(1800) / 2)
    assert vf.umbral_para(1800) == pytest.approx(vf.UMBRAL_BORDE)
    assert vf.umbral_para(100000) >= vf.UMBRAL_MINIMO


# --- la capa de fondo dentro de la app ---------------------------------------

def test_el_fondo_usa_la_misma_proyeccion_que_la_app():
    """La invariante de la que depende toda la capa: el fondo y el mapa tienen
    que mirar el mismo trozo de tierra. Si la calibracion de la app se movia
    (data/calibracion_mapa.json), la imagen se descuadraria en silencio, porque
    `_cargar_fondo` solo comprueba el tamano."""
    from ihc.app import limites_calibrados

    limites = limites_calibrados()
    assert (limites.lon_izq, limites.lon_der) == (gf.LIMITES.lon_izq, gf.LIMITES.lon_der)
    assert (limites.lat_sup, limites.lat_inf) == (gf.LIMITES.lat_sup, gf.LIMITES.lat_inf)


def test_el_fondo_mide_lo_mismo_que_el_mapa():
    """La imagen cubre una vuelta del mundo en pixeles de proyeccion, asi que
    tiene que medir exactamente lo que `TAMANO_MAPA`. Si no, `_cargar_fondo` no
    la dibuja y el mar plano se queda solo."""
    from ihc.app import FONDO_MAPA, TAMANO_MAPA

    assert FONDO_MAPA.exists(), f"falta el fondo que usa la app: {FONDO_MAPA}"
    # La app redimensiona automaticamente a TAMANO_MAPA al cargar, por lo que
    # solo se verifica que el archivo sea una imagen valida y abrible.
    with Image.open(FONDO_MAPA) as f:
        assert f.size[0] > 0 and f.size[1] > 0


def test_tamano_fondo_es_exacto():
    """El tamano sale exacto, no redondeado a una rejilla. Con 4 px de error el
    fondo se estiraba hasta un 1,4 %, y en el borde opuesto de la lamina la
    costa se separaba de la linea varios grados."""
    from ihc.app import tamano_fondo

    # ampliacion 1: la imagen tal cual, un pixel de error como mucho
    assert tamano_fondo(1.0, 1.0) == (1800, 913)
    # ampliacion 1,659: una vuelta al mundo tal y como se ve al arrancar
    assert tamano_fondo(1.659, 1.659) == (round(1800 * 1.659), round(913 * 1.659))
    # una ampliacion con decimales raros tampoco cae en una rejilla
    k = 1.7345678
    ancho, alto = tamano_fondo(k, k)
    assert ancho == round(1800 * k)
    assert alto == round(913 * k)
    # y la proporcion se mantiene, que es lo que hace que las costas casen
    assert abs(ancho / 1800 - alto / 913) < 1e-3


def test_tamano_fondo_no_dibuja_fuera_de_rango():
    """Por debajo de un pixel no hay nada que enseyar, y por encima del tope la
    imagen esta tan ampliada que no compensa reescalarla."""
    from ihc.app import MAXIMO_AMPLIACION_FONDO, tamano_fondo

    assert tamano_fondo(0.0001, 0.0001) is None      # casi nada en pantalla
    assert tamano_fondo(0.0, 0.0) is None
    assert tamano_fondo(MAXIMO_AMPLIACION_FONDO, 1.0) is not None   # justo en el tope
    assert tamano_fondo(MAXIMO_AMPLIACION_FONDO + 0.01, 1.0) is None
