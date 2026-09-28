"""
ihc.telemetria - Medicion de la eficiencia de las trayectorias.

El objetivo de la practica pide "comparar la eficiencia de trayectorias
automaticas frente al control manual". Para que esa comparacion sea defendible
hay que medir las mismas magnitudes en los dos modos:

    distancia recorrida (km, geodesica), tiempo de vuelo (s), numero de
    tramos, numero de acciones de usuario y numero de correcciones.

Cada ejecucion se guarda como una `Medicion`. El `Registro` permite comparar N
ejecuciones (media y desviacion) y exportar a CSV, que es la tabla que se
incluye en el manual.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Iterable, Literal

Modo = Literal["AUTO", "MANUAL"]


@dataclass
class Medicion:
    """Una ejecucion completa (un vuelo automatico o un intento manual)."""

    modo: Modo
    distancia_km: float = 0.0
    tiempo_s: float = 0.0
    tramos: int = 0
    acciones: int = 0          # pulsaciones de tecla + arrastres
    correcciones: int = 0      # cambios de rumbo/deriva del usuario
    ruta: list[str] = field(default_factory=list)
    inicio: float = field(default_factory=time.time)

    @property
    def velocidad_kmh(self) -> float:
        return self.distancia_km / self.tiempo_s if self.tiempo_s > 0 else 0.0

    @property
    def eficiencia(self) -> float:
        """Segundos por 1000 km: menor es mejor. 0 si no se recorrio nada."""
        if self.distancia_km <= 0:
            return 0.0
        return self.tiempo_s / self.distancia_km * 1000.0

    def duracion(self) -> str:
        return f"{self.tiempo_s:.1f} s"


@dataclass
class Cronometro:
    """Reloj monotono: no se altera si el usuario cambia la hora del sistema."""

    inicio: float = field(default_factory=time.monotonic)
    pausado: float = 0.0
    acumulado: float = 0.0
    activo: bool = False

    def iniciar(self) -> None:
        if not self.activo:
            self.inicio = time.monotonic()
            self.activo = True

    def pausar(self) -> None:
        if self.activo:
            self.acumulado += time.monotonic() - self.inicio
            self.activo = False

    def reiniciar(self) -> None:
        self.inicio = time.monotonic()
        self.acumulado = 0.0
        self.activo = False

    @property
    def transcurrido(self) -> float:
        total = self.acumulado + (time.monotonic() - self.inicio if self.activo else 0.0)
        return total


class Registro:
    """Coleccion de mediciones, con estadisticos y exportacion."""

    def __init__(self) -> None:
        self.mediciones: list[Medicion] = []

    def agregar(self, medicion: Medicion) -> None:
        self.mediciones.append(medicion)

    def reiniciar(self) -> None:
        self.mediciones.clear()

    def por_modo(self, modo: Modo) -> list[Medicion]:
        return [m for m in self.mediciones if m.modo == modo]

    def estadistico(self, modo: Modo, campo: str = "eficiencia") -> dict[str, float]:
        valores = [getattr(m, campo) for m in self.por_modo(modo) if getattr(m, campo)]
        if not valores:
            return {"n": 0, "media": 0.0, "desviacion": 0.0, "min": 0.0, "max": 0.0}
        return {
            "n": float(len(valores)),
            "media": statistics.fmean(valores),
            "desviacion": statistics.pstdev(valores) if len(valores) > 1 else 0.0,
            "min": min(valores),
            "max": max(valores),
        }

    def comparativa(self) -> dict[str, float] | None:
        """Diferencia porcentual de eficiencia: cuanto tarda mas el modo manual."""
        auto = self.estadistico("AUTO")
        manual = self.estadistico("MANUAL")
        if not auto["n"] or not manual["n"] or auto["media"] <= 0:
            return None
        return {
            "auto_s_por_1000km": auto["media"],
            "manual_s_por_1000km": manual["media"],
            "manual_es_x_mas_lento": manual["media"] / auto["media"],
            "ventaja_automatica_pct": (1.0 - auto["media"] / manual["media"]) * 100.0,
        }

    def como_filas(self) -> Iterable[dict]:
        for medicion in self.mediciones:
            datos = asdict(medicion)
            datos["velocidad_kmh"] = round(medicion.velocidad_kmh, 2)
            datos.pop("inicio", None)
            yield datos
