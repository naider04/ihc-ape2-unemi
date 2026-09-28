"""
Pruebas de la geodesia (ihc.geo).

Son calculos con valor verificable: las distancias se comparan contra valores
publicados, de modo que si alguien cambia una formula el test falla.
"""

import math

import pytest

from ihc import geo


def test_haversine_quito_madrid():
    """Quito (UIO) - Madrid (MAD): 8 700 km aprox. en la realidad."""
    d = geo.haversine(-0.1254, -78.3543, 40.4936, -3.5728)
    assert 8_500 < d < 8_950


def test_haversine_casi_cero():
    assert geo.haversine(0.0, 0.0, 0.0, 0.0) == 0.0


def test_haversine_antimeridiano():
    """Dos puntos a cada lado del Pacifico: la distancia corta, no la larga."""
    corta = geo.haversine(0.0, 179.5, 0.0, -179.5)
    assert 100 < corta < 120  # 1 grado de longitud en el ecuador ~ 111 km


def test_haversine_simetrica():
    a = geo.haversine(51.5, -0.1, -33.9, 151.2)
    b = geo.haversine(-33.9, 151.2, 51.5, -0.1)
    assert a == pytest.approx(b)


def test_rumbo_inicial_cardinales():
    assert geo.rumbo_inicial(0, 0, 10, 0) == pytest.approx(0.0, abs=1e-6)      # norte
    assert geo.rumbo_inicial(0, 0, 0, 10) == pytest.approx(90.0, abs=1e-6)     # este
    assert geo.rumbo_inicial(0, 0, -10, 0) == pytest.approx(180.0, abs=1e-6)   # sur
    assert geo.rumbo_inicial(0, 10, 0, 0) == pytest.approx(270.0, abs=1e-6)   # oeste


def test_punto_sobre_arco_reproduce_el_destino():
    """Desplazarse con el rumbo inicial debe llegar al mismo punto."""
    lat, lon = -12.0, -77.1
    rumbo = geo.rumbo_inicial(lat, lon, 48.8, 2.3)
    distancia = geo.haversine(lat, lon, 48.8, 2.3)
    punto = geo.punto_sobre_arco(lat, lon, rumbo, distancia)
    assert punto.lat == pytest.approx(48.8, abs=1e-6)
    assert punto.lon == pytest.approx(2.3, abs=1e-6)


def test_interpolar_extremos():
    a, b = (-0.1254, -78.3543), (40.4936, -3.5728)
    inicio, medio, fin = geo.interpolar(a, b, 0.0), geo.interpolar(a, b, 0.5), geo.interpolar(a, b, 1.0)
    assert (inicio.lat, inicio.lon) == pytest.approx(a)
    assert (fin.lat, fin.lon) == pytest.approx(b)
    # El punto medio geodesico esta mas al norte que el punto medio lineal.
    assert medio.lat > (a[0] + b[0]) / 2.0


def test_longitud_ruta_suma_tramos():
    ruta = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0)]
    esperado = geo.haversine(0, 0, 0, 10) + geo.haversine(0, 10, 10, 10)
    assert geo.longitud_ruta(ruta) == pytest.approx(esperado)


def test_distancia_euclidiana_usa_math_sqrt():
    """Es el comando `math.sqrt` de la guia de comandos: 3-4-5."""
    assert geo.distancia_euclidiana(0, 0, 3, 4) == pytest.approx(5.0)
    assert geo.distancia_euclidiana(10, 10, 10, 10) == 0.0


def test_formatear_distancia():
    assert geo.formatear_distancia(0.4) == "400 m"
    assert geo.formatear_distancia(12.34) == "12.3 km"
    assert "8,7" in geo.formatear_distancia(8700)


def test_normalizar_lon():
    assert geo.normalizar_lon(190) == pytest.approx(-170)
    assert geo.normalizar_lon(-190) == pytest.approx(170)
    assert geo.normalizar_lon(180) == pytest.approx(-180)


def test_conversion_grados_radianes_consistente():
    assert math.degrees(math.radians(37.5)) == pytest.approx(37.5)
