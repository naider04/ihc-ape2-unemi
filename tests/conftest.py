"""Recursos compartidos por las pruebas.

Los datos se cargan una sola vez por modulo: son casi dos megabytes de paises y
cargarlos en cada prueba haria la suite mucho mas lenta.
"""

import pytest

from ihc.datos import FuenteDatos


@pytest.fixture(scope="session")
def fuente() -> FuenteDatos:
    return FuenteDatos().cargar()
