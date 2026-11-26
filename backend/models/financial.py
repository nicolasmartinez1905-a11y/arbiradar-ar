"""Contratos de entrada para evaluar circuitos manuales."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

ZERO = Decimal("0")
ONE = Decimal("1")


def validar_decimal(valor: Decimal, campo: str) -> None:
    if not isinstance(valor, Decimal) or not valor.is_finite() or valor < ZERO:
        raise ValueError(f"{campo} debe ser un Decimal finito y no negativo")


def validar_fecha(valor: datetime) -> None:
    if valor.utcoffset() is None:
        raise ValueError("La fecha debe incluir zona horaria")


class Operacion(StrEnum):
    COMPRA = "compra"
    VENTA = "venta"
    CONVERSION = "conversión"
    TRANSFERENCIA_BANCARIA = "transferencia bancaria"
    TRANSFERENCIA_BLOCKCHAIN = "transferencia blockchain"
    DEPOSITO = "depósito"
    RETIRO = "retiro"


class OrigenDatos(StrEnum):
    AUTOMATICO = "automático"
    MANUAL = "manual"
    SIMULADO = "simulado"


class Estado(StrEnum):
    TEORICA = "Brecha teórica"
    PENDIENTE = "Pendiente de validación"
    VALIDADA = "Validada con los datos disponibles"
    SIMULADA = "Simulada"
    DESCARTADA = "Descartada"
    EXPIRADA = "Expirada"


@dataclass(frozen=True, slots=True)
class Nodo:
    plataforma: str
    activo: str
    decimales: int = 2

    def __post_init__(self) -> None:
        if not self.plataforma.strip() or not self.activo.strip():
            raise ValueError("La plataforma y el activo son obligatorios")
        if type(self.decimales) is not int or not 0 <= self.decimales <= 18:
            raise ValueError("La precisión debe estar entre 0 y 18 decimales")

    @property
    def unidad(self) -> Decimal:
        return ONE.scaleb(-self.decimales)


@dataclass(frozen=True, slots=True)
class Cotizacion:
    fuente: str
    origen: OrigenDatos
    recibida: datetime
    publicada: datetime | None = None
    disponible: bool = True

    def __post_init__(self) -> None:
        if not self.fuente.strip() or not isinstance(self.origen, OrigenDatos):
            raise ValueError("La fuente y el origen de datos son obligatorios")
        validar_fecha(self.recibida)
        if self.publicada is not None:
            validar_fecha(self.publicada)
            if self.publicada > self.recibida:
                raise ValueError("La publicación es posterior a la recepción")

    @property
    def fecha_efectiva(self) -> datetime:
        return self.publicada or self.recibida


@dataclass(frozen=True, slots=True)
class Costos:
    """Importe fijo en activo de destino. Fracciones entre 0 y 1."""
    fijo: Decimal | None = None
    comision: Decimal | None = None
    slippage: Decimal | None = None
    impuestos: Decimal | None = None

    def __post_init__(self) -> None:
        for campo in ("fijo", "comision", "slippage", "impuestos"):
            valor = getattr(self, campo)
            if valor is not None:
                validar_decimal(valor, campo)
                if campo != "fijo" and valor >= ONE:
                    raise ValueError(f"{campo} debe ser inferior a 1")

    @property
    def completos(self) -> bool:
        return None not in (self.fijo, self.comision, self.slippage, self.impuestos)


@dataclass(frozen=True, slots=True)
class Evidencia:
    """Cada confirmación requiere revisión aplicable a la operación concreta."""
    operacion_permitida: bool | None = None
    pagos_compatibles: bool | None = None
    titularidad_compatible: bool | None = None
    normativa_compatible: bool | None = None
    fuente_operativa: str = ""
    fuente_normativa: str = ""
    revisada: datetime | None = None

    def __post_init__(self) -> None:
        if self.revisada is not None:
            validar_fecha(self.revisada)


@dataclass(frozen=True, slots=True)
class Paso:
    origen: Nodo
    destino: Nodo
    operacion: Operacion
    tasa: Decimal
    cotizacion: Cotizacion
    costos: Costos = Costos()
    minimo: Decimal | None = None
    maximo: Decimal | None = None
    liquidez: Decimal | None = None
    segundos: int | None = None
    red_origen: str | None = None
    red_destino: str | None = None
    evidencia: Evidencia = Evidencia()

    def __post_init__(self) -> None:
        validar_decimal(self.tasa, "tasa")
        if self.tasa == ZERO or self.origen == self.destino:
            raise ValueError("El paso requiere una tasa positiva y dos nodos distintos")
        if not isinstance(self.operacion, Operacion):
            raise ValueError("Operación inválida")
        for campo in ("minimo", "maximo", "liquidez"):
            valor = getattr(self, campo)
            if valor is not None:
                validar_decimal(valor, campo)
        if self.minimo is not None and self.maximo is not None and self.minimo > self.maximo:
            raise ValueError("El mínimo supera el máximo")
        if self.segundos is not None and (type(self.segundos) is not int or self.segundos < 0):
            raise ValueError("La demora debe ser un entero no negativo")
