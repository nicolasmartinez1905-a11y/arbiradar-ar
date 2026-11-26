"""Cotizaciones normalizadas, separadas de la evidencia de un circuito."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from backend.models.financial import OrigenDatos, validar_decimal, validar_fecha


class Vigencia(StrEnum):
    ACTUAL = "actual"
    VENCIDA = "vencida"
    DESCONOCIDA = "sin fecha de origen"
    DESCONECTADA = "fuente desconectada"


@dataclass(frozen=True, slots=True)
class PrecioMercado:
    fuente: str
    mercado: str
    base: str
    contramoneda: str
    recibida: datetime
    compra_usuario: Decimal | None
    venta_usuario: Decimal | None
    publicada: datetime | None = None
    observada_por_fuente: datetime | None = None
    origen: OrigenDatos = OrigenDatos.AUTOMATICO
    solo_referencia: bool = True
    compra_con_costos: Decimal | None = None
    venta_con_costos: Decimal | None = None
    volumen_consultado: Decimal | None = None
    cantidad_compra: Decimal | None = None
    cantidad_venta: Decimal | None = None
    vencida_en_fuente: bool = False

    def __post_init__(self) -> None:
        if not all(valor.strip() for valor in (self.fuente, self.mercado, self.base, self.contramoneda)):
            raise ValueError("Faltan identificadores de la cotización")
        if self.base == self.contramoneda or not isinstance(self.origen, OrigenDatos):
            raise ValueError("Par u origen de datos inválido")
        validar_fecha(self.recibida)
        for fecha in (self.publicada, self.observada_por_fuente):
            if fecha is not None:
                validar_fecha(fecha)
                if fecha > self.recibida:
                    raise ValueError("La hora de origen es posterior a la recepción")
        campos = (self.compra_usuario, self.venta_usuario, self.compra_con_costos, self.venta_con_costos,
                  self.volumen_consultado, self.cantidad_compra, self.cantidad_venta)
        for valor in campos:
            if valor is not None:
                validar_decimal(valor, "importe de cotización")
                if not valor:
                    raise ValueError("Un importe de cotización debe ser positivo")
        if self.compra_usuario is None and self.venta_usuario is None:
            raise ValueError("Faltan ambos lados de la cotización")

    def antiguedad(self, ahora: datetime) -> timedelta | None:
        validar_fecha(ahora)
        return ahora - self.publicada if self.publicada is not None else None

    def vigencia(self, ahora: datetime, limite: timedelta, *, conectada: bool = True) -> Vigencia:
        edad = self.antiguedad(ahora)
        if self.vencida_en_fuente or (edad is not None and edad > limite):
            return Vigencia.VENCIDA
        if not conectada:
            return Vigencia.DESCONECTADA
        if edad is None or edad < timedelta(0):
            return Vigencia.DESCONOCIDA
        return Vigencia.ACTUAL
