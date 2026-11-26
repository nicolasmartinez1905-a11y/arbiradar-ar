"""Evalúa un circuito suministrado, sin descubrir rutas ni operar fondos."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, localcontext

from backend.models.financial import (
    ONE, ZERO, Estado, Nodo, Operacion, OrigenDatos, Paso, validar_decimal, validar_fecha,
)
from backend.validators.circuits import validar_paso

CAPITAL_REFERENCIA = Decimal("1000000")
RENTABILIDAD_MINIMA = Decimal("1")
ACTUALIZACION_OBJETIVO_SEGUNDOS = 5
ZONA_HORARIA = "America/Argentina/Buenos_Aires"


@dataclass(frozen=True, slots=True)
class ResultadoPaso:
    paso: Paso
    entrada: Decimal | None
    salida_bruta: Decimal | None
    salida_neta: Decimal | None


@dataclass(frozen=True, slots=True)
class Resultado:
    estado: Estado
    capital_inicial: Decimal
    capital_final: Decimal | None = None
    ganancia_bruta: Decimal | None = None
    costos_totales: Decimal | None = None
    ganancia_neta: Decimal | None = None
    rentabilidad: Decimal | None = None
    margen_seguridad_pp: Decimal | None = None
    segundos_estimados: int | None = None
    pasos: tuple[ResultadoPaso, ...] = ()
    observaciones: tuple[str, ...] = ()

    @property
    def apta_para_revision_manual(self) -> bool:
        return self.estado == Estado.VALIDADA


def evaluar_circuito(
    inicio: Nodo,
    ruta: tuple[Paso, ...],
    capital: Decimal = CAPITAL_REFERENCIA,
    *,
    minimo_porcentual: Decimal = RENTABILIDAD_MINIMA,
    max_operaciones: int = 8,
    ahora: datetime | None = None,
    antiguedad: timedelta = timedelta(seconds=15),
    vigencia_revision: timedelta = timedelta(days=1),
) -> Resultado:
    validar_decimal(capital, "capital")
    validar_decimal(minimo_porcentual, "rentabilidad mínima")
    if capital <= ZERO or capital % inicio.unidad != ZERO:
        raise ValueError("El capital debe ser positivo y respetar la precisión inicial")
    if type(max_operaciones) is not int or max_operaciones < 2:
        raise ValueError("El máximo de operaciones debe ser un entero mayor o igual a 2")
    if antiguedad <= timedelta(0) or vigencia_revision <= timedelta(0):
        raise ValueError("Las ventanas de vigencia deben ser positivas")
    ahora = ahora if ahora is not None else datetime.now(timezone.utc)
    validar_fecha(ahora)

    if (
        not 2 <= len(ruta) <= max_operaciones
        or ruta[0].origen != inicio
        or ruta[-1].destino != inicio
        or any(anterior.destino != siguiente.origen for anterior, siguiente in zip(ruta, ruta[1:]))
    ):
        return Resultado(Estado.DESCARTADA, capital, observaciones=(
            "El circuito debe ser continuo y regresar al mismo activo y plataforma",
        ))

    errores, pendientes, vencimientos = [], [], []
    resultados = []
    neto = bruto = capital
    for indice, paso in enumerate(ruta, 1):
        if paso.operacion in (
            Operacion.TRANSFERENCIA_BANCARIA, Operacion.TRANSFERENCIA_BLOCKCHAIN,
            Operacion.DEPOSITO, Operacion.RETIRO,
        ) and (paso.origen.activo != paso.destino.activo or paso.tasa != ONE):
            errores.append(f"Paso {indice}. El traslado debe conservar el activo y usar tasa 1")
        entrada = neto
        validacion = validar_paso(paso, entrada, ahora, antiguedad, vigencia_revision)
        for destino, motivos in zip((errores, pendientes, vencimientos), validacion):
            destino.extend(f"Paso {indice}. {motivo}" for motivo in motivos)

        with localcontext() as contexto:
            contexto.prec = 80
            salida_bruta = (
                (entrada * paso.tasa).quantize(paso.destino.unidad, rounding=ROUND_DOWN)
                if entrada is not None else None
            )
            bruto = (bruto * paso.tasa).quantize(paso.destino.unidad, rounding=ROUND_DOWN)
            costos = paso.costos
            if not costos.completos:
                pendientes.append(f"Paso {indice}. Costos incompletos")
                neto = None
            elif neto is not None:
                salida = entrada * paso.tasa * (ONE - costos.slippage)
                salida *= (ONE - costos.comision) * (ONE - costos.impuestos)
                neto = (salida - costos.fijo).quantize(paso.destino.unidad, rounding=ROUND_DOWN)
                if neto <= ZERO:
                    errores.append(f"Paso {indice}. Los costos o el redondeo agotan el importe")
                    neto = None
        resultados.append(ResultadoPaso(paso, entrada, salida_bruta, neto))

    # La proyección bruta usa todas las tasas, incluso con costos desconocidos.
    with localcontext() as contexto:
        contexto.prec = 80
        ganancia_bruta = bruto - capital
        ganancia = neto - capital if neto is not None else None
        rentabilidad = ganancia / capital * Decimal("100") if ganancia is not None else None
        margen = rentabilidad - minimo_porcentual if rentabilidad is not None else None
        costos_totales = bruto - neto if neto is not None else None

    if rentabilidad is not None and rentabilidad < minimo_porcentual:
        errores.append("Rentabilidad neta inferior al mínimo configurado")

    if errores:
        estado = Estado.DESCARTADA
    elif vencimientos:
        estado = Estado.EXPIRADA
    elif any(paso.cotizacion.origen == OrigenDatos.SIMULADO for paso in ruta):
        estado = Estado.SIMULADA
    elif neto is None:
        estado = Estado.TEORICA
    elif pendientes:
        estado = Estado.PENDIENTE
    else:
        estado = Estado.VALIDADA

    return Resultado(
        estado=estado,
        capital_inicial=capital,
        capital_final=neto,
        ganancia_bruta=ganancia_bruta,
        costos_totales=costos_totales,
        ganancia_neta=ganancia,
        rentabilidad=rentabilidad,
        margen_seguridad_pp=margen,
        segundos_estimados=sum(paso.segundos for paso in ruta)
        if all(paso.segundos is not None for paso in ruta) else None,
        pasos=tuple(resultados),
        observaciones=tuple(errores + vencimientos + pendientes),
    )
