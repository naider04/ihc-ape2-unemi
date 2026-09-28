"""
Pruebas de la carga de datos (ihc.datos).

Verifican que los recursos se leen del disco sin conexion, que las coordenadas
son plausibles y que la aplicacion no se cae cuando falta un archivo.
"""

import math
from pathlib import Path

import pytest

from ihc.datos import RAIZ_PROYECTO, FuenteDatos, simplificar_anillo

CSV = RAIZ_PROYECTO / "data" / "aeropuertos.csv"
PAISES = RAIZ_PROYECTO / "data" / "paises.json"


def test_el_csv_existe():
    """Si falla esto, ejecute: python herramientas/preparar_datos.py"""
    assert CSV.exists(), "falta data/aeropuertos.csv"


def test_carga_miles_de_aeropuertos(fuente):
    assert len(fuente.aeropuertos) > 3000
    assert not fuente.avisos


def test_coordenadas_validas(fuente):
    for aeropuerto in fuente.aeropuertos[:500]:
        assert -90 <= aeropuerto.lat <= 90
        assert -180 <= aeropuerto.lon <= 180


def test_busca_por_iata(fuente):
    uio = fuente.por_iata("UIO")
    assert uio is not None
    assert uio.ciudad == "Quito"
    assert uio.pais == "Ecuador"
    assert uio.lat == pytest.approx(-0.1254, abs=1e-3)


def test_busca_por_texto_sin_distinguir_mayusculas(fuente):
    assert fuente.buscar("uio")
    assert fuente.buscar("QUITO")
    assert fuente.buscar("mad")
    assert fuente.buscar("") == []
    assert fuente.buscar("ZZZ9") == []


def test_orden_de_busqueda_prioriza_grandes(fuente):
    resultados = fuente.buscar("London", limite=5)
    assert resultados
    assert resultados[0].tipo == "large_airport"


def test_etiqueta_y_descripcion(fuente):
    uio = fuente.por_iata("UIO")
    assert "UIO" in uio.etiqueta
    assert "Quito" in uio.descripcion


def test_pais_resuelto_desde_el_iso(fuente):
    """El CSV guarda el nombre del pais, no solo el codigo ISO."""
    assert fuente.por_iata("MAD").pais == "Spain"
    assert fuente.por_iata("JFK").pais == "United States of America"
    assert fuente.por_iata("SYD").pais == "Australia"


def test_elevacion_convertida_a_metros(fuente):
    mad = fuente.por_iata("MAD")
    assert mad.elevacion_m == round(mad.elevacion_ft * 0.3048)


def test_paises_cargados(fuente):
    assert PAISES.exists()
    assert len(fuente.paises) > 100
    ecuador = next((p for p in fuente.paises if p.iso == "EC"), None)
    assert ecuador is not None
    assert len(ecuador.anillos) >= 1


def test_modo_degradado_sin_csv(tmp_path: Path):
    """Sin datos, la aplicacion debe funcionar igual con la lista minima."""
    fuente = FuenteDatos(carpeta=tmp_path).cargar()
    assert fuente.avisos
    assert len(fuente.aeropuertos) == 12
    assert fuente.por_iata("UIO").ciudad == "Quito"
    assert fuente.por_iata("UIO").pais == "Ecuador"


def test_normalizar_omite_acentos():
    from ihc.datos import normalizar

    assert normalizar("España") == "ESPANA"
    assert normalizar("  Sao paulo ") == "SAO PAULO"
    assert normalizar("") == ""


def test_busqueda_ignora_tildes_y_mayusculas(fuente):
    assert fuente.buscar("españa")[0].pais == "Spain"
    assert fuente.buscar("ESPAÑA")[0].pais == "Spain"
    assert fuente.buscar("bogota")[0].iata == "BOG"
    assert fuente.buscar("São Paulo")[0].ciudad == "São Paulo"


def test_busqueda_prioriza_el_nombre_tecleado(fuente):
    """"Quito" es Quito, no Iquitos, que solo contiene la cadena."""
    assert fuente.buscar("Quito")[0].iata == "UIO"
    assert fuente.buscar("Londres")[0].ciudad == "London"
    assert fuente.buscar("Nueva York")[0].iata == "JFK"


def test_busqueda_por_pais_en_espanol(fuente):
    """>Los paises llegan en ingles; el usuario escribe en espanol."""
    assert all(a.pais == "Japan" for a in fuente.buscar("Japon", 5))
    assert all(a.pais == "Switzerland" for a in fuente.buscar("Suiza", 5))
    assert fuente.buscar("España", 5)


def test_indice_de_busqueda_cubre_todos(fuente):
    assert len(fuente._indice_busqueda) == len(fuente.aeropuertos)


# --- simplificacion de contornos (rendimiento del lienzo) ------------------

def test_simplificar_elimina_vertices_colineales():
    """Un cuadrado con un punto en cada lado se queda en cinco vertices."""
    cuadrado = [(0, 0), (5, 0), (10, 0), (10, 5), (10, 10), (5, 10), (0, 10), (0, 5)]
    assert simplificar_anillo(cuadrado, 0.1) == [(0.0, 0.0), (10.0, 0.0),
                                                  (10.0, 10.0), (0.0, 10.0),
                                                  (0.0, 5.0)]


def test_simplificar_conserva_los_puntos_que_importan():
    """Con tolerancia 0 no se quita nada: es el dato intacto."""
    sinuoso = [(0, 0), (5, 4), (10, -4), (15, 0)]
    assert simplificar_anillo(sinuoso, 0.0) == sinuoso


def test_simplificar_no_rompe_anillos_cortos_o_vacios():
    assert simplificar_anillo([]) == []
    assert simplificar_anillo([(1, 2), (3, 4)]) == [(1.0, 2.0), (3.0, 4.0)]


def test_simplificar_aguanta_anillos_muy_largos():
    """Canada y Rusia superan los mil vertices, mas que el limite de recursividad.

    Douglas-Peucker con pila explicita es justamente para eso; con recursion
    normal, este test lo detectaria.
    """
    circulo = [(50.0 * math.cos(2 * math.pi * i / 3000),
                50.0 * math.sin(2 * math.pi * i / 3000)) for i in range(3000)]
    circulo.append(circulo[0])
    simplificado = simplificar_anillo(circulo, 0.1)
    assert 0 < len(simplificado) < len(circulo)
    assert simplificado[0] == circulo[0] and simplificado[-1] == circulo[-1]


def test_los_paises_se_cargan_simplificados(fuente):
    """Los 242 paises se leen, quedan con menos vertices y conservan su nombre."""
    assert len(fuente.paises) == 242
    total = sum(len(anillo) for pais in fuente.paises for anillo in pais.anillos)
    assert 0 < total < 99613, "esperaba menos vertices que el original de Natural Earth"
    assert {"Ecuador", "Japan", "France"} <= {p.nombre for p in fuente.paises}


def test_las_latitudes_de_los_anillos_son_validas(fuente):
    """Todo anillo se guarda como (longitud, latitud), como en GeoJSON.

    Si el orden se invirtiera, la segunda cifra pasaria a leerse como latitud y
    cualquier punto con longitud mayor de 90 seria una latitude imposible: Japon
    y Australia se dibujaban fuera del mapa, arriba del todo, y Ecuador salia en
    el Atlantico. El sintoma era "el mapa va desalineado".
    """
    for pais in fuente.paises:
        for anillo in pais.anillos:
            for lon, lat in anillo:
                assert -90.0 <= lat <= 90.0, (
                    f"{pais.nombre}: {lon}, {lat} no es un par (lon, lat)")


def test_el_centroide_de_un_pais_cae_cerca_de_sus_aeropuertos(fuente):
    """El centroide de un pais tiene que caer junto a los puntos de su pais.

    Comprueba el orden de las coordenadas de extremo a extremo: si la app
    invirtiese (lon, lat) al proyectar, el pais se dibujaria a 1.400 px de sus
    propios aeropuertos, y por mas que ambos usen la misma proyeccion.
    """
    from ihc.proyeccion import Limites, Proyeccion

    proyeccion = Proyeccion(Limites(-30.0, 330.0, 90.0, -90.0), 1800.0, 913.0)
    ecuador = next(p for p in fuente.paises if p.nombre == "Ecuador")
    anillo = ecuador.anillos[0]
    centro_lon = sum(c[0] for c in anillo) / len(anillo)
    centro_lat = sum(c[1] for c in anillo) / len(anillo)
    x, y = proyeccion.a_pixeles(centro_lat, centro_lon)
    quito = proyeccion.a_pixeles(-0.125, -78.354)
    assert abs(x - quito[0]) < 60 and abs(y - quito[1]) < 60, (
        f"Ecuador se dibuja en {x:.0f},{y:.0f} y Quito esta en {quito[0]:.0f},{quito[1]:.0f}")


def test_el_resumen_no_descarta_islas_de_paises_fracturados(fuente):
    """Alaska, Hawai y las Canarias son anillos aparte: no pueden desaparecer.

    El resumen de datos se queda con los anillos de medio grado o mas. Si volviese
    a un "los cuatro mas grandes", un pais con muchas islas se quedaria sin
    territorio: en 50m Estados Unidos tiene 127 poligonos y Hawai es el quinto.
    """
    estados = next(p for p in fuente.paises if p.nombre == "United States of America")
    hawaiana = [a for a in estados.anillos
                if 19.0 <= min(c[1] for c in a) and max(c[1] for c in a) <= 22.0]
    assert hawaiana, "Hawai deberia seguir en los anillos de Estados Unidos"
    espana = next(p for p in fuente.paises if p.nombre == "Spain")
    largo = max(max(c[0] for c in a) - min(c[0] for c in a) for a in espana.anillos)
    assert largo > 10.0, "las Canarias o las Baleares se han perdido"
