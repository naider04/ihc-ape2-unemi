"""
Pruebas de la proyeccion y del georreferenciado (ihc.proyeccion).

Se comprueban tres cosas: que la proyeccion sea coherente en ida y vuelta, que
el ajuste de la imagen al lienzo no la deforme y que la calibracion por puntos
de control recupere una transformacion conocida.
"""

import math

import pytest

from ihc.proyeccion import (Calibracion, GCP, Limites, Mapa, Proyeccion,
                            ProyeccionMercator, TransformacionVista)

LIMITES = Limites(-30.0, 330.0, 90.0, -90.0)


def prueba() -> Proyeccion:
    return Proyeccion(LIMITES, 1800, 913)


def test_extremos_del_mapa():
    """El borde izquierdo es -30°; +330° es el mismo meridiano, asi que envuelve."""
    p = prueba()
    assert p.a_pixeles(0.0, -30.0) == pytest.approx((0.0, 456.5))
    assert p.a_pixeles(90.0, -30.0) == pytest.approx((0.0, 0.0))
    assert p.a_pixeles(-90.0, -30.0) == pytest.approx((0.0, 913.0))
    # El mapa es cilindrico y continua: +330° se dibuja en el mismo borde.
    assert p.a_pixeles(0.0, 330.0) == pytest.approx(p.a_pixeles(0.0, -30.0))
    assert p.a_pixeles(0.0, 299.0)[0] == pytest.approx(1645.0)


def test_ecuador_y_quito_caen_donde_debe():
    """UIO (Quito) debe caer sobre Sudamerica en la imagen (x 1530-1590, y 445-470)."""
    x, y = prueba().a_pixeles(-0.1254, -78.3543)
    assert 1530 < x < 1590
    assert 445 < y < 470
    # Y Madrid, en el borde izquierdo del mapa (Europa).
    mx, _ = prueba().a_pixeles(40.4936, -3.5728)
    assert 100 < mx < 160


def test_ida_y_vuelta():
    p = prueba()
    for lat, lon in ((0.0, 0.0), (48.8, 2.3), (-33.9, 151.2), (-12.0, -77.1)):
        x, y = p.a_pixeles(lat, lon)
        lat2, lon2 = p.a_grados(x, y)
        assert lat2 == pytest.approx(lat, abs=1e-9)
        assert lon2 == pytest.approx(lon, abs=1e-9)


def test_fuera_de_rango_devuelve_none():
    p = prueba()
    assert p.a_grados_limitados(900, 1000) is None


def test_mercator_es_consistente():
    p = ProyeccionMercator(Limites(-180.0, 180.0, 85.0, -85.0), 1000, 1000)
    for lat, lon in ((0.0, 0.0), (40.0, -74.0), (-34.0, 151.0)):
        x, y = p.a_pixeles(lat, lon)
        lat2, lon2 = p.a_grados(x, y)
        assert lat2 == pytest.approx(lat, abs=1e-6)
        assert lon2 == pytest.approx(lon, abs=1e-6)


def test_encajar_conserva_la_relacion_de_aspecto():
    """La muestra deformaba 1800x913 a 1000x507; aqui no se deforma."""
    mapa = Mapa(prueba(), (1800, 913))
    x, y, ancho, alto = mapa.encajar(1000, 560, margen=8)
    assert ancho / alto == pytest.approx(1800 / 913, rel=1e-9)
    assert ancho <= 1000 - 16
    assert alto <= 560 - 16
    assert x == pytest.approx((1000 - ancho) / 2)


def test_escala_de_pixels_por_grado():
    """La imagen mide 1800x913, no 1800x900: hay 1.4 % de estiramiento vertical.

    Es una propiedad de la imagen base, no un error del codigo, y por eso se
    documenta explicitamente en vez de "corregirla" a ojo.
    """
    p = prueba()
    assert p.a_pixeles(0.0, 0.0)[0] - p.a_pixeles(0.0, 1.0)[0] == pytest.approx(-5.0)
    assert p.a_pixeles(0.0, 0.0)[1] - p.a_pixeles(1.0, 0.0)[1] == pytest.approx(913 / 180)


def test_mapa_a_pantalla_escala_uniforme():
    """La vista escala de forma uniforme: el acercamiento no deforma la geografia."""
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1000, 560, margen=8)
    a = mapa.a_pantalla(0.0, 0.0)
    b = mapa.a_pantalla(0.0, 10.0)
    antes = math.hypot(b[0] - a[0], b[1] - a[1])

    escala = mapa.vista.encuadrar((0.0, 0.0, 100.0, 100.0), 1000.0, 560.0)
    a2 = mapa.a_pantalla(0.0, 0.0)
    b2 = mapa.a_pantalla(0.0, 10.0)
    assert math.hypot(b2[0] - a2[0], b2[1] - a2[1]) == pytest.approx(escala * antes, rel=1e-9)


def test_ida_y_vuelta_a_traves_de_la_pantalla():
    """Coordenada -> pixel de pantalla -> coordenada: no se pierde precision."""
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1000, 560, margen=8)
    for lat, lon in ((-0.1254, -78.3543), (40.4936, -3.5728), (-33.9, 151.2)):
        x, y = mapa.a_pantalla(lat, lon)
        lat2, lon2 = mapa.a_grados((x, y))
        assert lat2 == pytest.approx(lat, abs=1e-6)
        assert lon2 == pytest.approx(lon, abs=1e-6)


def test_transformacion_vista_encuadra_la_caja():
    """Todos los puntos de la caja deben caer dentro del lienzo."""
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1000, 560, margen=8)
    caja = (600.0, 200.0, 900.0, 500.0)
    escala = mapa.encuadrar_puntos_para_caja(caja)
    assert escala >= 1.0
    x, y, ancho, alto = mapa.rect_mapa
    esquinas = ((caja[0], caja[1]), (caja[2], caja[1]), (caja[0], caja[3]), (caja[2], caja[3]))
    for punto in esquinas:
        sx, sy = mapa.mapa_a_pantalla(punto)
        assert x <= sx <= x + ancho
        assert y <= sy <= y + alto


def test_transformacion_vista_respeta_el_acercamiento_maximo():
    """Dos puntos muy juntos no deben llenar la pantalla."""
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1000, 560, margen=8)
    escala = mapa.encuadrar_puntos_para_caja((900.0, 450.0, 900.1, 450.1), 6.0)
    assert escala == pytest.approx(6.0)


def test_transformacion_vista_nunca_muestra_mas_que_el_mundo():
    """Con la escala en 1 se ve el mundo entero: mas alla, la tierra se encoge."""
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1000, 560, margen=8)
    escala = mapa.encuadrar_puntos_para_caja((0.0, 0.0, 1800.0, 913.0), 6.0)
    assert escala == pytest.approx(1.0)


def test_transformacion_vista_centra_la_caja():
    """El punto medio de la caja queda en el centro del area del mapa."""
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1000, 560, margen=8)
    caja = (400.0, 200.0, 800.0, 600.0)
    mapa.encuadrar_puntos_para_caja(caja)
    x, y, ancho, alto = mapa.rect_mapa
    centro = mapa.mapa_a_pantalla(((caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2))
    assert centro[0] == pytest.approx(x + ancho / 2, rel=1e-6)
    assert centro[1] == pytest.approx(y + alto / 2, rel=1e-6)


def test_caja_de_ruta_desplaza_el_corte_del_mapa():
    """Quito y Madrid quedan a 1.426 px en la proyeccion, no a 374.

    Sin desplazar el corte, la caja de la ruta seria casi el mapa entero y el
    encuadre automatico no podria acercarse. Al ajustar la continuidad, la caja
    mide la distancia real entre los dos puntos.
    """
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1000, 560, margen=8)
    x0, _, x1, _ = mapa.caja_de_ruta([(-0.13, -78.35), (40.42, -3.57)])
    assert x1 - x0 < 400, f"la caja no se ajusto al corte: {x1 - x0:.0f} px"
    assert x0 == pytest.approx(mapa.geo_a_mapa(-0.13, -78.35)[0])


def test_encuadrar_puntos_muestra_los_dos_extremos():
    """El caso que reporto el usuario: origen y destino visibles a la vez."""
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1366, 560, margen=8)
    mapa.encuadrar_puntos([(-0.13, -78.35), (40.42, -3.57)], 6.0)
    x, y, ancho, alto = mapa.rect_mapa
    for lat, lon in ((-0.13, -78.35), (40.42, -3.57)):
        sx, sy = mapa.a_pantalla(lat, lon, repetir=True)
        assert 0 <= sx <= 1366
        assert 0 <= sy <= 560


def test_calibracion_recupera_transformacion_conocida():
    """Se genera un mapa con una transformacion afin y se recupera con 4 GCP."""
    # px = 2*lon + 3*lat + 10 ;  py = -lon + 0.5*lat + 5
    gcp = []
    for lon, lat in ((-78.0, -0.1), (-3.5, 40.5), (-74.0, 4.7), (151.0, -34.0), (0.0, 0.0)):
        gcp.append(GCP(lat=lat, lon=lon, x=2 * lon + 3 * lat + 10, y=-lon + 0.5 * lat + 5))
    cal = Calibracion.desde_gcp(gcp)
    assert cal.rms == pytest.approx(0.0, abs=1e-6)
    x, y = cal.a_pixeles(40.5, -3.5)
    assert x == pytest.approx(2 * -3.5 + 3 * 40.5 + 10)
    assert y == pytest.approx(-(-3.5) + 0.5 * 40.5 + 5)


def test_calibracion_exige_tres_puntos():
    with pytest.raises(ValueError):
        Calibracion.desde_gcp([GCP(0, 0, 0, 0), GCP(1, 1, 1, 1)])


def test_calibracion_detecta_puntos_mal_puestos():
    """Un GCP erroneo aumenta el error RMS: por eso se reporta la cifra."""
    buenos = [GCP(0, 0, 0, 0), GCP(10, 0, 100, 0), GCP(0, 10, 0, 100), GCP(10, 10, 100, 100)]
    exacta = Calibracion.desde_gcp(buenos)
    desviados = buenos[:-1] + [GCP(10, 10, 400, 400)]
    con_error = Calibracion.desde_gcp(desviados)
    assert exacta.rms < 1e-6
    assert con_error.rms > 1.0


def test_mapa_con_calibracion_invierte():
    mapa = Mapa(prueba(), (1800, 913))
    mapa.calibracion = Calibracion.desde_gcp([
        GCP(-0.1254, -78.3543, 1558.0, 457.0),
        GCP(40.4936, -3.5728, 130.0, 250.0),
        GCP(-33.9, 151.2, 480.0, 590.0),
    ])
    mapa.encajar(1000, 560, margen=8)
    x, y = mapa.a_pantalla(-0.1254, -78.3543)
    grados = mapa.a_grados((x, y))
    assert grados[0] == pytest.approx(-0.1254, abs=1e-6)
    assert grados[1] == pytest.approx(-78.3543, abs=1e-6)


# --- repeticion del mundo y desplazamiento de la vista ---------------------
# El defecto que reporto el usuario: los puntos quedaban desalineados porque
# se dibujaban con un desplazamiento fijo mientras la vista si se movia.

def test_el_fondo_se_desplaza_con_la_vista():
    """La copia base del mapa (map x = 0) debe seguir a la vista.

    Si se dibujara en `rect_x`, al desplazar la vista el fondo se quedaria
    quieto y los puntos se separarian de el.
    """
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1000, 560, margen=8)
    mapa.vista.encuadrar((600.0, 200.0, 900.0, 500.0), 1000.0 / mapa.escala_imagen,
                         560.0 / mapa.escala_imagen)
    borde_esperado = (mapa.rect_mapa[0] + mapa.vista.dx * mapa.escala_imagen)
    # La pantalla del punto (0, y) es el borde izquierdo de la copia base.
    assert mapa.mapa_a_pantalla((0.0, 0.0))[0] == pytest.approx(borde_esperado)


def test_un_trozo_de_imagen_cubre_el_lienzo():
    """Un recorte del mapa tiene que alcanzar de borde a borde el lienzo."""
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1366, 560, margen=8)
    mapa.encuadrar_puntos([(-0.13, -78.35), (40.42, -3.57)], 6.0)
    x_izq, x_der = mapa.rango_x_visible()
    # El ancho de la ventana en pixeles de mapa no puede exceder una vuelta.
    assert x_der - x_izq <= mapa.ancho_mundo
    assert x_izq < mapa.ancho_mundo


def test_rangos_visibles_cubren_el_lienzo():
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1366, 560, margen=8)
    mapa.encuadrar_puntos([(-0.13, -78.35), (40.42, -3.57)], 6.0)
    x0, x1 = mapa.rango_x_visible()
    y0, y1 = mapa.rango_y_visible()
    ancho_mapa = mapa.ancho_lienzo / (mapa.escala_imagen * mapa.vista.escala)
    alto_mapa = mapa.alto_lienzo / (mapa.escala_imagen * mapa.vista.escala)
    # El rango lleva 1 px de holgura a cada lado para que el recorte no deje
    # una linea de mar al borde.
    assert x1 - x0 == pytest.approx(ancho_mapa + 2.0, rel=1e-6)
    assert y1 - y0 == pytest.approx(alto_mapa + 2.0, rel=1e-6)


def test_copias_de_x_devuelve_el_tramo_visible():
    """Un pais al otro lado del corte tambien debe dibujarse."""
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1366, 560, margen=8)
    mapa.encuadrar_puntos([(-0.13, -78.35), (40.42, -3.57)], 6.0)
    x0, x1 = mapa.rango_x_visible()
    for x in (x0 + 1.0, (x0 + x1) / 2.0, x1 - 1.0):
        copias = mapa.copias_de_x(x, x)
        assert copias, "un punto visible necesita al menos una copia"
        assert any(x + k - x0 <= x1 - x0 for k in copias)


def test_copias_de_x_no_repet_un_pais_lejano():
    """Un pais fuera de la vista no debe dibujarse en ninguna copia."""
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1366, 560, margen=8)
    mapa.encuadrar_puntos([(48.85, 2.35), (40.42, -3.57)], 6.0)
    x0, x1 = mapa.rango_x_visible()
    for x in (20.0, 900.0, 1700.0):
        if x0 <= x <= x1:
            continue
        copias = mapa.copias_de_x(x, x)
        for k in copias:
            assert not (x + k >= x0 and x + k <= x1), \
                f"se dibuja fuera de la vista: {x} + {k}"


def test_sin_acentuar_no_se_repite_el_mundo():
    """A escala 1 el mundo ya cabe: la segunda copia solo llenaba los bordes.

    En un monitor de 1366 px la ventana son 2.886 px de mapa y el mundo mide
    1.800, asi que la repeticion es posible, pero no necesaria: pintar los 177
    paises dos veces costaba 98 ms en vez de 41.
    """
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1366, 560, margen=8)
    assert mapa.vista.escala == pytest.approx(1.0)
    assert not mapa.repeticiones_activas()
    assert mapa.copias_de_x(100.0, 200.0) == [0.0]


def test_acercando_si_se_repite_el_mundo():
    """Al acercar la ventana es mas estrecha que el mundo y hay que repetir."""
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1366, 560, margen=8)
    mapa.encuadrar_puntos([(0.13, -78.36), (40.42, -3.57)], 6.0)
    assert mapa.repeticiones_activas()
    x0, x1 = mapa.rango_x_visible()
    assert x1 - x0 < mapa.ancho_mundo, "con la vista acercada no caben dos mundos"
    # Quito cae en la copia -1 (a la izquierda del corte) y Madrid en la 0.
    quito = mapa.geo_a_mapa(0.13, -78.36)[0]
    assert mapa.copias_de_x(quito, quito)


def test_copias_de_x_solo_devuelve_las_visibles():
    """Ninguna copia devuelta puede quedar fuera de la ventana actual.

    Un elemento que no interseca la vista se dibuja igualmente en la copia mas
    cercana: si no, el corte del mapa se comeria paises enteros de la derecha.
    """
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1366, 560, margen=8)
    mapa.encuadrar_puntos([(0.13, -78.36), (40.42, -3.57)], 6.0)
    x0, x1 = mapa.rango_x_visible()
    for x in (50.0, 900.0, 1500.0, 1799.0):
        copias = mapa.copias_de_x(x, x)
        assert copias, "siempre se dibuja en alguna copia"
        if x0 <= x <= x1:
            for k in copias:
                assert x0 <= x + k <= x1, f"copia fuera de la vista: {x} + {k}"


def test_copia_mas_cercana_elige_el_mundo_correcto():
    """Desplaza el elemento a la copia mas proxima, con el menor desplazamiento.

    "Mas cercana" no significa "visible": un punto del lado opuesto del mundo
    puede quedar fuera de la vista, y entonces lo descarta el recorte por
    pantalla. Lo que no puede hacer es shifted mas de media vuelta, porque
    entonces saltaria al hemisferio equivocado.
    """
    mapa = Mapa(prueba(), (1800, 913))
    mapa.encajar(1366, 560, margen=8)
    mapa.encuadrar_puntos([(0.13, -78.36), (40.42, -3.57)], 6.0)
    ancho = mapa.ancho_mundo
    x0, x1 = mapa.rango_x_visible()
    centro = (x0 + x1) / 2.0
    for x in (0.0, 10.0, 900.0, 1500.0, 1799.0):
        destino = mapa.copia_mas_cercana(x)
        # Cae exactamente sobre una copia del mundo...
        assert (destino - x) % ancho == pytest.approx(0.0, abs=1e-6)
        # ...y nunca se aleja de la vista: elige la copia mas proxima al centro.
        assert abs(destino - centro) <= abs(x - centro) + 1e-6


def test_el_anillo_de_un_pais_cae_cerca_de_sus_aeropuertos(fuente):
    """El orden (lon, lat) de GeoJSON se invierte al proyectar.

    Este test cruza el dato con la proyeccion, que es donde se equivoco el
    codigo: el pais se dibujaba girado 90 grados y a 1.400 px de sus propios
    aeropuertos, aunque ambos usaran la misma matriz.
    """
    mapa = Mapa(Proyeccion(Limites(-30.0, 330.0, 90.0, -90.0), 1800.0, 913.0),
                (1800, 913))
    ecuador = next(p for p in fuente.paises if p.nombre == "Ecuador")
    puntos = mapa.anillo_a_mapa(ecuador.anillos[0])
    x = sum(p[0] for p in puntos) / len(puntos)
    y = sum(p[1] for p in puntos) / len(puntos)
    quito = mapa.geo_a_mapa(-0.125, -78.354)
    assert abs(x - quito[0]) < 60 and abs(y - quito[1]) < 60, (
        f"Ecuador se dibuja en {x:.0f},{y:.0f} y Quito esta en {quito[0]:.0f},{quito[1]:.0f}")


def test_ningun_pais_se_dibuja_fuera_de_la_lamina(fuente):
    """Con el orden equivocado, Japon y Australia caian con latitud menor de -90."""
    mapa = Mapa(Proyeccion(Limites(-30.0, 330.0, 90.0, -90.0), 1800.0, 913.0),
                (1800, 913))
    for pais in fuente.paises:
        for anillo in pais.anillos:
            for _, y in mapa.anillo_a_mapa(anillo):
                assert -1.0 <= y <= mapa.alto_imagen + 1.0, (
                    f"{pais.nombre} queda en y={y:.0f}, fuera de la lamina")


def test_los_coeficientes_abiertos_dicen_lo_mismo_que_la_matriz():
    """La forma rapida del dibujado tiene que coincidir con `mapa_a_pantalla`."""
    mapa = Mapa(Proyeccion(LIMITES, 1800.0, 913.0), (1800, 913))
    mapa.encajar(1400, 800)
    mapa.vista.escala = 3.7
    mapa.vista.dx = 12.5
    mapa.vista.dy = -40.25
    kx, ky, cx, cy = mapa.coeficientes_pantalla()
    for punto in ((0.0, 0.0), (1799.0, 912.0), (123.5, 456.25), (900.0, 913.0)):
        esperado = mapa.mapa_a_pantalla(punto)
        abierto = (punto[0] * kx + cx, punto[1] * ky + cy)
        assert abs(esperado[0] - abierto[0]) < 1e-9
        assert abs(esperado[1] - abierto[1]) < 1e-9
