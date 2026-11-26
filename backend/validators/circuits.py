"""Controles operativos que no consultan fuentes externas."""
from datetime import datetime, timedelta
from decimal import Decimal

from backend.models.financial import Operacion, Paso


def validar_paso(
    paso: Paso,
    importe: Decimal | None,
    ahora: datetime,
    antiguedad: timedelta,
    vigencia_revision: timedelta,
) -> tuple[list[str], list[str], list[str]]:
    errores, pendientes, vencimientos = [], [], []
    cotizacion = paso.cotizacion
    if not cotizacion.disponible:
        pendientes.append("Fuente desconectada")
    if cotizacion.recibida > ahora:
        pendientes.append("Recepción posterior a la hora de evaluación")
    if ahora - cotizacion.fecha_efectiva > antiguedad:
        vencimientos.append("Cotización desactualizada")

    for campo, etiqueta in (
        ("minimo", "mínimo"), ("maximo", "máximo"), ("liquidez", "liquidez"),
    ):
        limite = getattr(paso, campo)
        if limite is None:
            pendientes.append(f"Falta {etiqueta}")
        elif importe is not None and (importe < limite if campo == "minimo" else importe > limite):
            errores.append(f"El importe incumple {etiqueta}")

    if paso.segundos is None:
        pendientes.append("Demora desconocida")
    if paso.operacion == Operacion.TRANSFERENCIA_BLOCKCHAIN:
        if not paso.red_origen or not paso.red_destino:
            pendientes.append("Red blockchain desconocida")
        elif paso.red_origen != paso.red_destino:
            errores.append("Redes blockchain incompatibles")

    evidencia = paso.evidencia
    for comprobacion, etiqueta in (
        (evidencia.operacion_permitida, "operación permitida"),
        (evidencia.pagos_compatibles, "medios de pago"),
        (evidencia.titularidad_compatible, "titularidad"),
        (evidencia.normativa_compatible, "normativa"),
    ):
        if comprobacion is False:
            errores.append(f"Restricción confirmada de {etiqueta}")
        elif comprobacion is not True:
            pendientes.append(f"Falta confirmar {etiqueta}")
    if not evidencia.fuente_operativa.strip() or not evidencia.fuente_normativa.strip():
        pendientes.append("Faltan fuentes de la revisión")
    if (
        evidencia.revisada is None
        or evidencia.revisada > ahora
        or ahora - evidencia.revisada > vigencia_revision
    ):
        pendientes.append("Falta revisión operativa y normativa vigente")
    return errores, pendientes, vencimientos
