"""
Pruebas de la cuadricula de meridianos y paralelos (ihc.cuadricula).

Lo que importa comprobar aqui son las tres cosas que pueden salir mal sin que se
note mirando la pantalla:

  1. Que la malla del mapa este donde dice estar. En una rejilla dibujada a ojo,
     un meridiano desplazado dos grados no se distingue de uno bien puesto, pero
     hace que las etiquetas mientan. Se comprueba contra `a_pixeles`, que es la
     misma funcion que usan los paises y los Aeropuertos.
  2. Que la malla de la esfera se parta en el limbo y no atraviese el disco. Un
     meridiano de la cara oculta dibujado de un tirón es el error clasico de la
     ortografica, y en una miniatura de 90 px de radio es facil que pase
     desapercibido.
  3. Que el globo se coloque dentro del lienzo y no se dibuje cuando no cabe.
"""

import math

import pytest

from ihc import cuadricula
from ihc.proyeccion import Limites, Mapa, Proyeccion, ProyeccionMercator

LIMITES = Limites(-30.0, 330.0, 90.0, -90.0)


def prueba() -> Proyeccion:
    return Proyeccion(LIMITES, 1800, 913)


# --------------------------------------------------------------------------
# La malla sobre el mapa
# --------------------------------------------------------------------------

def test_grados_alineados_caen_en_multiplos():
    assert cuadricula.grados_alineados(-30.0, 330.0, 30.0) == pytest.approx(
        [0.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0, 210.0, 240.0, 270.0, 300.0])
    assert cuadricula.grados_alineados(-90.0, 90.0, 15.0) == pytest.approx(
        [-75.0, -60.0, -45.0, -30.0, -15.0, 0.0, 15.0, 30.0, 45.0, 60.0, 75.0])


def test_el_borde_de_la_lamina_no_se_etiqueta():
    """Los 90 grados coinciden con el marco del mapa: dibujarlos seria duplicarlos."""
    grados = cuadricula.grados_alineados(-90.0, 90.0, 30.0)
    assert max(abs(g) for g in grados) == pytest.approx(60.0)
    con_borde = cuadricula.grados_alineados(-90.0, 90.0, 30.0, incluir_borde=True)
    assert con_borde[0] == pytest.approx(-90.0) and con_borde[-1] == pytest.approx(90.0)


def test_meridiano_vertical_que_pasa_por_su_grado():
    """Un meridiano es una vertical, y en la equirectangular no se curva."""
    p = prueba()
    linea = cuadricula.meridiano(p, 90.0, LIMITES)
    esperado = p.a_pixeles(0.0, 90.0)[0]
    assert all(x == pytest.approx(esperado) for x, _ in linea)
    assert linea[0][1] == pytest.approx(913.0)   # polo sur, abajo
    assert linea[-1][1] == pytest.approx(0.0)    # polo norte, arriba


def test_paralelo_horizontal_que_atraviesa_la_lamina():
    p = prueba()
    linea = cuadricula.paralelo(p, 30.0, LIMITES)
    assert all(y == pytest.approx(p.a_pixeles(30.0, 0.0)[1]) for _, y in linea)
    assert linea[0][0] == pytest.approx(0.0)      # -30 grados, borde izquierdo
    assert linea[-1][0] == pytest.approx(1785.1, abs=0.5)  # un paso antes del derecho


def test_rejilla_devuelve_meridianos_y_paralelos_clasificados():
    lineas = cuadricula.rejilla(prueba(), LIMITES)
    meridianos = [l for l in lineas if l.eje == "lon"]
    paralelos = [l for l in lineas if l.eje == "lat"]
    assert len(meridianos) == 11   # de 0 a 300, ni -30 ni +330 son multiplos de 30
    assert len(paralelos) == 11    # de -75 a 75, cada 15
    assert [l.clase for l in paralelos].count("ecuator") == 1
    assert next(l for l in paralelos if l.clase == "ecuator").grado == pytest.approx(0.0)
    # Los multiples de 15 que no son multiplos de 30 son la malla fina.
    finos = [l.grado for l in paralelos if l.clase == "menor"]
    assert finos == pytest.approx([-75.0, -45.0, -15.0, 15.0, 45.0, 75.0])


def test_rejilla_usa_la_proyeccion_que_le_pasan():
    """La malla no son rectas dibujadas a mano: sigue a la proyeccion.

    En las dos proyecciones los meridianos y los paralelos son rectos, asi que la
    diferencia hay que buscarla donde se nota: en la distancia entre paralelos.
    En equirectangular todos los tramos de 30 grados miden lo mismo, y en
    Mercator los de las latitudes altas son mas cortos, porque la proyeccion
    agranda los polos. Si la rejilla no acompañara a la proyeccion, las dos
    medidas saldrian iguales.
    """
    equirectangular = prueba()
    mercator = ProyeccionMercator(Limites(-180.0, 180.0, 85.0, -85.0), 1800, 913)

    def separacion(proyeccion, uno: float, otro: float) -> float:
        return abs(proyeccion.a_pixeles(otro, 0.0)[1] - proyeccion.a_pixeles(uno, 0.0)[1])

    assert separacion(equirectangular, 30.0, 60.0) == pytest.approx(
        separacion(equirectangular, 0.0, 30.0))
    assert separacion(mercator, 30.0, 60.0) > separacion(mercator, 0.0, 30.0)


def test_el_paralelo_no_vuelve_al_borde_que_empieza():
    """La longitud envuelve: muestrear en +330 volveria al 0 y cruzaria el mapa."""
    linea = cuadricula.paralelo(prueba(), 30.0, LIMITES)
    assert linea[0][0] == pytest.approx(0.0)
    assert linea[-1][0] > 1700.0
    assert linea[-1][0] < 1800.0
    # Y ningun par de puntos se separa mas que el ancho de la lamina.
    assert max(abs(b[0] - a[0]) for a, b in zip(linea, linea[1:])) < 30.0


def test_etiquetas_de_latitud_y_longitud():
    assert cuadricula.etiqueta_lat(0.0) == "0°"
    assert cuadricula.etiqueta_lat(30.0) == "30° N"
    assert cuadricula.etiqueta_lat(-45.0) == "45° S"
    assert cuadricula.etiqueta_lon(0.0) == "0°"
    assert cuadricula.etiqueta_lon(90.0) == "90° E"
    assert cuadricula.etiqueta_lon(-60.0) == "60° O"
    # El mapa va hasta +330, que son los 30 oeste, no un numero mayor que 180.
    assert cuadricula.etiqueta_lon(330.0) == "30° O"
    assert cuadricula.etiqueta_lon(180.0) == "180°"


# --------------------------------------------------------------------------
# La misma malla sobre la esfera
# --------------------------------------------------------------------------

def test_el_centro_de_la_esfera_cae_en_el_centro_del_disco():
    punto = cuadricula.ortografica(10.0, 20.0, 10.0, 20.0, 90.0, (500.0, 300.0))
    assert punto == pytest.approx((500.0, 300.0))


def test_la_cara_oculta_no_se_dibuja():
    """El punto de enfrente del observador esta detras: None, no el centro."""
    assert cuadricula.ortografica(-10.0, -160.0, 10.0, 20.0, 90.0, (0.0, 0.0)) is None
    assert cuadricula.ortografica(89.0, 200.0, -80.0, 0.0, 90.0, (0.0, 0.0)) is None


def test_el_limbo_queda_justo_en_el_borde_del_disco():
    """Un punto a 90 grados del centro cae en la circunferencia, no dentro.

    Aqui hay un margen numerico a proposito: `cos_c` sale en 1e-17 y no en 0, y
    sin margen el meridiano del limbo se dibujaria entero y por dentro.
    """
    for grados in (90.0, -90.0):
        punto = cuadricula.ortografica(0.0, 20.0 + grados, 0.0, 20.0, 90.0, (0.0, 0.0))
        assert punto is None
    # Y a 89 grados ya es visible, pegado al borde.
    punto = cuadricula.ortografica(0.0, 20.0 + 89.0, 0.0, 20.0, 90.0, (0.0, 0.0))
    assert punto is not None
    assert math.hypot(*punto) == pytest.approx(90.0, abs=0.6)


def test_el_norte_del_disco_arriba():
    """La y de la pantalla crece hacia abajo, asi que el norte esta arriba."""
    norte = cuadricula.ortografica(40.0, 0.0, 0.0, 0.0, 50.0, (0.0, 0.0))
    sur = cuadricula.ortografica(-40.0, 0.0, 0.0, 0.0, 50.0, (0.0, 0.0))
    assert norte[1] < 0 < sur[1]


def test_las_lineas_de_la_esfera_no_se_salen_del_disco():
    centro = (300.0, 200.0)
    radio = 70.0
    for lat0, lon0 in ((0.0, 150.0), (48.0, -3.0), (-33.0, 151.0), (80.0, 10.0)):
        for linea in cuadricula.rejilla_esfera(lat0, lon0, radio, centro):
            for x, y in linea.puntos:
                assert math.hypot(x - centro[0], y - centro[1]) <= radio + 0.5


def test_el_meridiano_central_pasa_por_el_centro():
    lineas = cuadricula.rejilla_esfera(0.0, 150.0, 80.0, (0.0, 0.0))
    centrales = [l for l in lineas if l.clase == "central"]
    assert len(centrales) == 1
    assert centrales[0].grado == pytest.approx(150.0)
    for x, y in centrales[0].puntos:
        assert x == pytest.approx(0.0)   # meridiano central = vertical del centro


def test_el_ecuador_se_dibuja_mas_que_las_demas_lineas():
    lineas = cuadricula.rejilla_esfera(20.0, 0.0, 80.0, (0.0, 0.0))
    assert [l.grado for l in lineas if l.clase == "ecuator"] == [0.0]


def test_la_esfera_gira_con_la_vista():
    """Centrar la malla en otro meridiano desplaza la malla, no solo la gira."""
    antes = cuadricula.rejilla_esfera(0.0, 0.0, 80.0, (0.0, 0.0))
    despues = cuadricula.rejilla_esfera(0.0, 90.0, 80.0, (0.0, 0.0))
    grado_antes = {l.grado for l in antes if l.clase == "central"}
    grado_despues = {l.grado for l in despues if l.clase == "central"}
    assert grado_antes == {0.0} and grado_despues == {90.0}


def test_cerca_del_polo_se_ve_mas_meridiano_que_en_el_ecuador():
    """Mirando el polo norte casi todos los meridianos son visibles.

    Es geometria, no un fallo: el horizonte esta a 10 grados del polo, asi que
    la mayor parte de los meridianos quedan dentro del disco.
    """
    en_ecuador = cuadricula.rejilla_esfera(0.0, 0.0, 80.0, (0.0, 0.0))
    en_el_polo = cuadricula.rejilla_esfera(85.0, 0.0, 80.0, (0.0, 0.0))
    assert len([l for l in en_el_polo if l.clase == "mayor"]) > \
        len([l for l in en_ecuador if l.clase == "mayor"])


# --------------------------------------------------------------------------
# Colocacion del globo y centro de la vista
# --------------------------------------------------------------------------

def test_el_globo_se_coloca_en_la_esquina_inferior_derecha():
    cx, cy, radio = cuadricula.colocar_esfera(1200.0, 560.0)
    assert cx + radio == pytest.approx(1200.0 - cuadricula.MARGEN_ESFERA)
    assert cy + radio == pytest.approx(560.0 - cuadricula.MARGEN_ESFERA)
    assert radio > 0


def test_el_globo_se_pega_al_mapa_y_no_a_la_ventana():
    """Con la lamina centrada sobran margenes negros: el globo va con el mapa.

    Es el caso real de la aplicacion (lienzo 1306x369, lamina de 696x353), y en
    el que se nota: en la esquina de la ventana el globo queda flotando sobre el
    negro, a 150 px del mapa.
    """
    rect = (305.0, 8.0, 696.0, 353.0)
    cx, cy, radio = cuadricula.colocar_esfera(1306.0, 369.0, rect)
    assert cx + radio == pytest.approx(rect[0] + rect[2] - cuadricula.MARGEN_ESFERA)
    assert cy + radio == pytest.approx(rect[1] + rect[3] - cuadricula.MARGEN_ESFERA)
    # Y sigue dentro de la ventana, que es lo unico que importa.
    assert 0.0 <= cx - radio and cx + radio <= 1306.0
    assert 0.0 <= cy - radio and cy + radio <= 369.0


def test_el_globo_no_se_sale_cuando_el_mapa_se_sale_de_la_pantalla():
    """Al acercar, la lamina se sale por los bordes: el globo se queda dentro."""
    cx, cy, radio = cuadricula.colocar_esfera(1200.0, 560.0, (900.0, -400.0, 4000.0, 2000.0))
    assert cx + radio <= 1200.0 - cuadricula.MARGEN_ESFERA + 1e-9
    assert cy + radio <= 560.0 - cuadricula.MARGEN_ESFERA + 1e-9
    assert cx - radio >= 0.0 and cy - radio >= 0.0


def test_el_globo_no_se_sale_en_un_lienzo_pequeno():
    assert cuadricula.colocar_esfera(200.0, 150.0) is None
    assert cuadricula.colocar_esfera(cuadricula.ANCHO_MIN_ESFERA - 1,
                                    cuadricula.ALTO_MIN_ESFERA) is None
    assert cuadricula.colocar_esfera(cuadricula.ANCHO_MIN_ESFERA,
                                    cuadricula.ALTO_MIN_ESFERA) is not None


def test_el_radio_se_queda_entre_los_limites():
    for ancho, alto in ((300.0, 260.0), (1500.0, 900.0), (960.0, 640.0)):
        _, _, radio = cuadricula.colocar_esfera(ancho, alto)
        assert cuadricula.RADIO_ESFERA_MIN <= radio <= cuadricula.RADIO_ESFERA_MAX


def test_el_centro_de_la_vista_es_el_que_mira_el_lienzo():
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1000, 560, margen=8)
    lat, lon = cuadricula.centro_de_vista(mapa)
    assert -90.0 <= lat <= 90.0 and -180.0 <= lon < 180.0
    # El centro de la lamina es el ecuador y el meridiano que cae en medio.
    assert abs(lat) < 1e-9
    assert lon == pytest.approx(150.0, abs=1e-6)


def test_el_centro_de_la_vista_sigue_siendo_valido_fuera_de_la_lamina():
    """Si la vista se sale del mapa, el globo se centra en la proyeccion."""
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1000, 560, margen=8)
    mapa.vista.desplazar(50_000.0, 50_000.0)
    lat, lon = cuadricula.centro_de_vista(mapa)
    assert -90.0 <= lat <= 90.0
    assert -180.0 <= lon < 180.0
