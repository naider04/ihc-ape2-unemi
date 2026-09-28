"""
verificar_fondo.py - Comprueba que una imagen de fondo encaja con las lineas.

Recibe la imagen que se haya generado por fuera y dice, con numeros, si sus
costas caen donde el simulador dibuja las costas. La referencia no es la opinion
de nadie: es Natural Earth, la misma fuente con la que esta hecho el mapa.

La medicion va por el borde, no por el color. Se busca en que pixel esta la costa
de la imagen y se compara con la costa real; el color de la tierra y el del mar
pueden ser los que quiera, porque lo que tiene que casar es la linea. Asi el
estilo nofalsea el resultado: una imagen con relieve, sombras o colores raros
sale igual de buena, y una imagen corrida unos pixeles sale mala aunque tenga
los colores perfectos.

Tambien dice cuanto habria que mover la imagen, en pixeles y en grados, para que
encajara. Si son dos o tres, se puede pedir el recorte ese; si son muchos, la
imagen se hizo con otra proyeccion y hay que volver a pedirla.

Uso:
    python herramientas/verificar_fondo.py --imagen ../mi_fondo.png
    python herramientas/verificar_fondo.py --imagen fondo.png --alcance 60
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from ihc.proyeccion import Limites, Proyeccion  # noqa: E402

from generar_fondo import ALTO_POR_ANCHO, LIMITES, cargar_anillos, proyectar  # noqa: E402

# Grados de longitud por pixel y grados de latitud por pixel, ya escalados al
# ancho y alto de la lamina. Se calculan al vuelo; aqui solo el valor de muestra.
# Un desfase de 1 px es 0,2 grados de longitud.
UMBRAL_BORDE = 14          # diferencia de gris minima para contar como borde
                          # (a 1800 px de ancho; se escala con la resolucion)
UMBRAL_MINIMO = 3.0        # hasta donde se puede relajar si el contraste es bajo
TOLERANCIA_PX = 2.0        # desfase maximo que se considera "encaja"
COBERTURA_MINIMA = 90.0    # % de costa real que debe tener borde pegado


def mascara_tierra(ancho: int, alto: int) -> Image.Image:
    """Mascara de tierra en blanco y negro, en la misma rejilla que la imagen.

    Se dibuja con el mismo trazo y la misma proyeccion que usa el mapa, para que
    la costa de referencia sea exactamente la linea que el simulador dibuja.
    """
    mascara = Image.new("L", (ancho, alto), 0)
    lienzo = ImageDraw.Draw(mascara)
    proyeccion = Proyeccion(LIMITES, float(ancho), float(alto))
    for anillo in cargar_anillos():
        puntos = proyectar(proyeccion, anillo)
        if len(puntos) >= 3:
            lienzo.polygon(puntos, fill=255)
    return mascara


def mapa_de_costa(mascara: Image.Image) -> Image.Image:
    """Pixels en el borde de la mascara: la costa, en blanco sobre negro."""
    bordes = mascara.filter(ImageFilter.FIND_EDGES)
    return bordes.point(lambda v: 255 if v > 0 else 0, mode="L")


def _gradientes(imagen: Image.Image) -> Image.Image:
    return imagen.convert("L").filter(ImageFilter.SMOOTH).filter(ImageFilter.FIND_EDGES)


def umbral_para(ancho: int) -> float:
    """Umbral de borde para esa resolucion.

    El mismo cambio de color reparte su diferencia en mas pixeles cuanto mas
    grande es la imagen, y el salto por pixel baja. Por eso el umbral se divide
    por el factor de escala; si no, el mismo fondo aprobado a 1800 px suspendia
    a 3600 px solo por eso.
    """
    return max(UMBRAL_MINIMO, UMBRAL_BORDE * 1800.0 / max(1, ancho))


def mapa_de_bordes(imagen: Image.Image, umbral: float) -> Image.Image:
    """Bordes de la imagen recibida, en blanco sobre negro.

    Sale la costa seguro, porque es un cambio fuerte de color. tambien salen
    otros detalles, como rios o relieve, pero al buscar el desplazamiento solo
    importa el pico de coincidencias, y ese lo pone la costa, que es la linea mas
    larga y la unica que esta en las dos imagenes.
    """
    bordes = _gradientes(imagen)
    return bordes.point(lambda v: 255 if v > umbral else 0, mode="L")


def bordes_calibrados(imagen: Image.Image, largo_costa: int) -> tuple[Image.Image, float]:
    """Bordes con el umbral ajustado hasta que se ve la costa.

    Si la imagen tiene poco contraste, con el umbral normal no sale nada y la
    medicion daria cero por donde quiera. Se va bajando el umbral hasta que se
    detecta una parte razonable de la costa real, y se devuelve con que umbral
    quedo, que se imprime para que el numero se pueda ensuinguir.
    """
    umbral = umbral_para(imagen.width)
    while True:
        bordes = mapa_de_bordes(imagen, umbral)
        encontrados = contar_claros(bordes)
        # La costa real mide `largo_costa` px. Se espera de la imagen algo
        # parecido; si se detecta menos de la mitad, el umbral esta alto.
        if encontrados >= largo_costa * 0.5 or umbral <= UMBRAL_MINIMO:
            return bordes, umbral
        umbral = max(UMBRAL_MINIMO, umbral / 1.7)


def contar_claros(imagen: Image.Image) -> int:
    """Cuantos pixeles claros hay. `histogram` va en C, que se nota."""
    return sum(imagen.histogram()[1:])


def solape(a: Image.Image, b: Image.Image) -> int:
    """Pixeles en los que las dos imagenes binarias se encienden a la vez.

    Con valores de 0 y 255, el minimo es un AND y el maximo un OR, y los dos van
    en C. (`logical_and` de Pillow solo acepta modo "1", que va mas lento.)
    """
    return contar_claros(ImageChops.darker(a, b))


def registrar(costa: Image.Image, bordes: Image.Image, alcance: int = 40
              ) -> tuple[int, int, int]:
    """Busca el desplazamiento que mas encaja, en dos vueltas.

    Primero de 4 en 4 px por todo el alcance, y luego de 1 en 1 alrededor de lo
    mejor. Devuelve (dx, dy, solape) con el desplazamiento de la imagen que hay
    que aplicar para alinearla con el mapa.
    """
    mejor = (0, 0, solape(bordes, costa))
    for salto, rango in ((4, range(-alcance, alcance + 1, 4)),
                         (1, range(-5, 6))):
        for dy in rango:
            for dx in rango:
                n = solape(ImageChops.offset(bordes, dx, dy), costa)
                if n > mejor[2]:
                    mejor = (dx, dy, n)
    return mejor


def mejor_correccion(costa: Image.Image, bordes: Image.Image, dx0: int, dy0: int,
                     ventana: int = 6) -> tuple[int, int, float]:
    """El desplazamiento que mas costa cubre, buscando alrededor de la pista.

    La busqueda de bordes (`registrar`) localiza la zona rapido, pero cuenta
    todos los bordes de la imagen, relieve incluido, asi que puede apuntar un
    pixel o dos equivocado. Aqui, alrededor de ahi, se prueba con la medida
    buena, que es la cobertura. Se incluye siempre el desplazamiento cero como
    candidato y, a igualdad, se prefiere: si la imagen ya esta en su sitio, el
    verificador no debe inventarle un error de un pixel.
    """
    # El margen se calcula una sola vez: separarlo antes de mover es lo mismo
    # que moverlo antes de separarlo, y asi el bucle va en C y no en minutos.
    cerca = bordes.filter(ImageFilter.MaxFilter(5))
    mejor = (0, 0, 0.0)
    for dy in range(-ventana, ventana + 1):
        for dx in range(-ventana, ventana + 1):
            n = solape(ImageChops.offset(cerca, dx0 + dx, dy0 + dy), costa)
            if n > mejor[2]:
                mejor = (dx0 + dx, dy0 + dy, n)
    return mejor[0], mejor[1], 100.0 * mejor[2] / max(1, contar_claros(costa))


def cobertura_costa(costa: Image.Image, bordes: Image.Image, dx: int, dy: int,
                    radio: int = 2) -> float:
    """Porcentaje de la costa real que tiene un borde de la imagen al lado.

    Se separa el borde de la imagen y se cuenta cuantos pixeles de la costa real
    quedan encima. El margen de 2 px es para la costa que va en diagonal, que se
    queda a un pixel del sitio: 2 px son 0,4° de longitud, asi que sigue siendo
    una medida muy fina.
    """
    lado = radio * 2 + 1
    cerca = bordes.filter(ImageFilter.MaxFilter(lado))
    n = solape(ImageChops.offset(cerca, dx, dy), costa)
    return 100.0 * n / max(1, contar_claros(costa))


def superponer(imagen: Image.Image, salida: Path) -> Path:
    """Pone la costa de referencia en rojo sobre la imagen recibida."""
    ancho, alto = imagen.size
    capa = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
    lienzo = ImageDraw.Draw(capa)
    grosor = max(2, round(ancho / 900))
    for anillo in cargar_anillos():
        puntos = proyectar(Proyeccion(LIMITES, float(ancho), float(alto)), anillo)
        lienzo.line(puntos + [puntos[0]], fill=(255, 40, 40, 210),
                    width=grosor, joint="curve")
    fondo = imagen.convert("RGBA")
    fondo.alpha_composite(capa)

    barra = Image.new("RGB", (ancho, max(26, alto // 34)), (18, 18, 18))
    d = ImageDraw.Draw(barra)
    d.text((8, barra.height // 2 - 6),
           f"la linea roja es la costa real (Natural Earth) | imagen {ancho}x{alto} px",
           fill=(235, 235, 235), font=ImageFont.load_default())
    montada = Image.new("RGB", (ancho, alto + barra.height), (0, 0, 0))
    montada.paste(fondo.convert("RGB"), (0, 0))
    montada.paste(barra, (0, alto))
    montada.save(salida)
    return salida


def apta(proporcion_ok: bool, desplazamiento: int, cobertura: float) -> bool:
    """Veredicto, en un sitio solo para que se pueda probar.

    Las tres cosas tienen que cumplirse: la lamina tiene que ser de la
    proporcion del mapa, la imagen no puede estar corrida, y la costa real tiene
    que verse en ella. Falla una y no sirve.
    """
    return proporcion_ok and desplazamiento <= TOLERANCIA_PX \
        and cobertura >= COBERTURA_MINIMA


def cobertura_minima_texto() -> str:
    return (f"se busca al menos {COBERTURA_MINIMA:.0f} %; por debajo, las lineas "
            f"del mapa se ven separadas de la imagen")


def main() -> int:
    analizador = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    analizador.add_argument("--imagen", type=Path, required=True,
                            help="imagen de fondo recibida")
    analizador.add_argument("--alcance", type=int, default=40,
                            help="desplazamientos a probar, en px (por defecto 40)")
    analizador.add_argument("--salida", type=Path, default=None,
                            help="donde escribir la comparacion "
                                 "(por defecto, en referencias/)")
    argumentos = analizador.parse_args()

    if not argumentos.imagen.exists():
        print(f"No existe {argumentos.imagen}", file=sys.stderr)
        return 1

    with Image.open(argumentos.imagen) as abierta:
        imagen = abierta.convert("RGB")
    ancho, alto = imagen.size
    alto_ideal = round(ancho * ALTO_POR_ANCHO)
    px_por_grado_lon = ancho / 360.0
    px_por_grado_lat = alto / 180.0

    print(f"Imagen: {argumentos.imagen.name}  {ancho} x {alto} px")
    print(f"Proporcion pedida: {ancho} x {alto_ideal} px "
          f"(alto/ancho {ALTO_POR_ANCHO:.5f})")
    proporcion_ok = alto == alto_ideal
    if not proporcion_ok:
        print(f"  AVISO: el alto no cuadra; sobran o faltan "
              f"{abs(alto - alto_ideal)} px. Una lamina estirada en vertical "
              f"descuadra las lineas arriba y abajo y no por mas que se "
              f"desplace. Mejor pedirla a {ancho} x {alto_ideal} px.")
    else:
        print(f"  Proporcion correcta: 1 px = {360.0 / ancho:.3f}° de longitud "
              f"y {180.0 / alto:.3f}° de latitud")
    print()

    costa = mapa_de_costa(mascara_tierra(ancho, alto))
    largo_costa = contar_claros(costa)
    bordes, umbral = bordes_calibrados(imagen, largo_costa)
    print(f"Referencia: {largo_costa:,} px de costa real")
    print(f"Imagen:     {contar_claros(bordes):,} px de borde detectados "
          f"(umbral {umbral:.1f} de gris)")
    print()

    cobertura = cobertura_costa(costa, bordes, 0, 0)
    print(f"Costa real con borde pegado, sin mover nada: {cobertura:.2f} %")
    print(f"  {cobertura_minima_texto()}")
    print()

    dx_pista, dy_pista, _ = registrar(costa, bordes, argumentos.alcance)
    dx, dy, cobertura_final = mejor_correccion(costa, bordes, dx_pista, dy_pista)
    desplazamiento = max(abs(dx), abs(dy))
    print(f"Correccion que habria que aplicarle a la imagen: {dx:+d} px en "
          f"horizontal y {dy:+d} px en vertical")
    print(f"  o sea {dx / px_por_grado_lon:+.2f}° de longitud y "
          f"{-dy / px_por_grado_lat:+.2f}° de latitud")
    if desplazamiento == 0:
        print("  No hay que moverla: ya esta en su sitio.")
    elif desplazamiento <= TOLERANCIA_PX:
        print("  Despreciable: menos de un pixel y medio de margen, se deja igual.")
    elif desplazamiento <= 4 * max(px_por_grado_lon, px_por_grado_lat):
        print(f"  Es poco: se puede pedir el recorte desplazado {dx:+d},{dy:+d} px.")
    else:
        print("  Es mucho: la imagen se hizo con otra proyeccion o con otro "
              "recorte. Moverla no la arregla; hay que volver a pedirla.")
    print()

    if desplazamiento > 0 and cobertura_final > cobertura:
        print(f"Moviendola asi la cobertura de la costa sube de "
              f"{cobertura:.2f} % a {cobertura_final:.2f} %.")
    elif desplazamiento > 0:
        print(f"Eveno moviendola asi la cobertura baja a "
              f"{cobertura_final:.2f} %, asi que el problema no es la posicion.")
    print()

    destino = argumentos.salida or (RAIZ / "referencias" /
                                     f"comparacion_{argumentos.imagen.stem}.png")
    destino.parent.mkdir(parents=True, exist_ok=True)
    superponer(imagen, destino)
    print(f"Comparacion escrita en {destino.relative_to(RAIZ)}")
    print("  las lineas rojas son las costas reales: si siguen a la imagen, encaja")

    if not proporcion_ok:
        print("\nVEREDICTO: no sirve, la proporcion no es la del mapa.")
    elif apta(True, desplazamiento, max(cobertura, cobertura_final)):
        print("\nVEREDICTO: apta como fondo del mapa.")
        return 0
    else:
        print("\nVEREDICTO: todavia no sirve como fondo del mapa.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
