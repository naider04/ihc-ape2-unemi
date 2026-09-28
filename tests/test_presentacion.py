"""
Pruebas de Presentacion: la ventana tiene que caber en la pantalla del usuario.

El defecto reportado era que en un portatil de 1366x768 la parte de abajo
(paneles de telemetria y consola) quedaba fuera de la pantalla. Estas pruebas
comprueban el calculo para varias pantallas sin abrir una ventana.
"""

import pytest

from ihc.app import (ALT_MINIMO_LIENZO, ALTO_MAXIMO_LIENZO, ANCHO_MAXIMO_VENTANA,
                      ANCHO_MINIMO_VENTANA, dimensiones_ventana)

# Altura que ocupan barra, buscador, los tres paneles y la consola, medida con
# la tipografia actual: todo lo que no es el mapa.
ESPACIO_FIJO = 250

PANTALLAS = [(1366, 768), (1920, 1080), (1280, 720), (1366, 768 * 2), (1024, 640)]


@pytest.mark.parametrize("pantalla", PANTALLAS)
def test_la_ventana_cabe_en_la_pantalla(pantalla):
    ancho, alto, alto_lienzo = dimensiones_ventana(*pantalla, ESPACIO_FIJO)
    assert alto <= pantalla[1] - 40, f"se sale por abajo en {pantalla}"
    assert ancho <= pantalla[0], f"se sale por un lado en {pantalla}"


@pytest.mark.parametrize("pantalla", PANTALLAS)
def test_el_lienzo_nevera_tiene_un_tamano_util(pantalla):
    _, _, alto_lienzo = dimensiones_ventana(*pantalla, ESPACIO_FIJO)
    assert alto_lienzo >= ALT_MINIMO_LIENZO
    assert alto_lienzo <= ALTO_MAXIMO_LIENZO


def test_en_una_pantalla_de_768_el_lienzo_sigue_siendo_util():
    """El caso exacto que reporto el usuario: la ventana pedia 812 px."""
    _, _, alto_lienzo = dimensiones_ventana(1366, 768, ESPACIO_FIJO)
    assert alto_lienzo >= 380, f"el lienzo queda demasiado bajo: {alto_lienzo}"


def test_una_pantalla_alta_no_estira_el_lienzo_infinito():
    """En 4K el mapa no debe ocupar 2000 px de alto: se limita."""
    _, _, alto_lienzo = dimensiones_ventana(3840, 2160, ESPACIO_FIJO)
    assert alto_lienzo == ALTO_MAXIMO_LIENZO


def test_una_pantalla_muy_ancha_no_estira_la_ventana():
    ancho, _, _ = dimensiones_ventana(3840, 2160, ESPACIO_FIJO)
    assert ancho == ANCHO_MAXIMO_VENTANA


def test_una_pantalla_estrecha_respeta_el_minimo():
    ancho, _, _ = dimensiones_ventana(800, 600, ESPACIO_FIJO)
    assert ancho == ANCHO_MINIMO_VENTANA


def test_pantalla_alta_deja_mas_mapa_que_pantalla_baja():
    _, _, alto_bajo = dimensiones_ventana(1366, 768, ESPACIO_FIJO)
    _, _, alto_alto = dimensiones_ventana(1920, 1080, ESPACIO_FIJO)
    assert alto_alto > alto_bajo
