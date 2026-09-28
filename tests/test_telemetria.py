"""
Pruebas de la telemetria (ihc.telemetria).

La comparacion auto vs manual es el resultado de aprendizaje de la practica,
asi que la medicion debe ser coherente: eficiencia, estadisticos y comparativa.
"""

import pytest

from ihc.telemetria import Cronometro, Medicion, Registro


def medicion(modo: str, km: float, s: float) -> Medicion:
    return Medicion(modo=modo, distancia_km=km, tiempo_s=s, tramos=3, ruta=["UIO", "MAD"])


def test_velocidad():
    m = medicion("AUTO", 8700.0, 10.0)
    assert m.velocidad_kmh == pytest.approx(870.0)


def test_eficiencia_segundos_por_1000_km():
    """El manual tarda 3600 s en 1000 km -> 3600 s/1000 km."""
    m = medicion("MANUAL", 1000.0, 3600.0)
    assert m.eficiencia == pytest.approx(3600.0)
    rapido = medicion("AUTO", 1000.0, 600.0)
    assert rapido.eficiencia == pytest.approx(600.0)


def test_eficiencia_cero_sin_recorrido():
    assert Medicion(modo="AUTO").eficiencia == 0.0
    assert Medicion(modo="AUTO").velocidad_kmh == 0.0


def test_cronometro_arranca_pausa_y_reinicia():
    reloj = Cronometro()
    assert reloj.transcurrido < 0.5
    reloj.iniciar()
    reloj.pausar()
    pausado = reloj.transcurrido
    assert reloj.activo is False
    reloj.reiniciar()
    assert reloj.transcurrido < 0.5
    assert pausado >= 0.0


def test_registro_agrupa_por_modo():
    registro = Registro()
    registro.agregar(medicion("AUTO", 1000, 600))
    registro.agregar(medicion("MANUAL", 1000, 3600))
    assert len(registro.por_modo("AUTO")) == 1
    assert len(registro.por_modo("MANUAL")) == 1


def test_comparativa_calcula_ventaja():
    registro = Registro()
    registro.agregar(medicion("AUTO", 1000, 600))
    registro.agregar(medicion("MANUAL", 1000, 3600))
    comparativa = registro.comparativa()
    assert comparativa["manual_es_x_mas_lento"] == pytest.approx(6.0)
    assert comparativa["ventaja_automatica_pct"] == pytest.approx(83.33, abs=0.1)


def test_comparativa_requiere_los_dos_modos():
    registro = Registro()
    registro.agregar(medicion("AUTO", 1000, 600))
    assert registro.comparativa() is None


def test_estadistico_calcula_desviacion():
    registro = Registro()
    registro.agregar(medicion("AUTO", 1000, 600))
    registro.agregar(medicion("AUTO", 1000, 800))
    est = registro.estadistico("AUTO")
    assert est["n"] == 2
    assert est["media"] == pytest.approx(700.0)
    assert est["desviacion"] == pytest.approx(100.0)
