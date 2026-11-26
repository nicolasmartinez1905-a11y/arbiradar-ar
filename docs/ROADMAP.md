# Plan de implementación de ArbiRadar AR

| Fase | Alcance | Criterio de cierre |
| --- | --- | --- |
| 1 | Modelos, cálculo Decimal y validación básica de rutas aportadas | Pruebas locales del cálculo y del bloqueo ante evidencia insuficiente |
| 2 | Inventario de APIs públicas, CriptoYa y otras fuentes verificadas, caché y monitoreo asíncrono | Verificar fuentes y límites, manejar 429, reintentos, latencia, circuit breaker, WebSocket y caducidad con respuestas controladas |
| 3 | Grafo, búsqueda acotada, disponibilidad real, profundidad, costos completos y revisión normativa | Detectar circuitos de hasta ocho pasos por defecto, calcular capital máximo y precio de equilibrio bajo límites reales y bloquear toda ruta sin evidencia |
| 4 | API de consulta y dashboard responsive en español, con actualizaciones en tiempo real | Verificar todas las vistas, detalle de ruta, confirmación manual, recálculo y protección de endpoints |
| 5 | Historial, persistencia, simulación con demoras, precios históricos y alertas opcionales | Separar simulación y registro manual, medir resultados y verificar vencimientos y deduplicación |
| 6 | Pruebas de integración, seguridad, rendimiento y preparación cloud | Probar el frontend para Vercel y el proceso permanente por separado con despliegue sujeto a autorización |

## Metodología de la fase 1

Cada nodo combina plataforma, activo y precisión. La ruta debe ser continua y volver al nodo inicial. Una tasa expresa unidades del activo de destino por unidad de origen. Las tasas de compra y venta se entregan por separado. Por ejemplo, un precio de compra en ARS por USD debe convertirse previamente a USD por ARS para ingresarlo al motor. Un traslado conserva el activo y usa tasa uno. Una conversión entre USD y una stablecoin requiere su propia tasa.

En cada paso se aplica la tasa, luego slippage, comisión, impuestos y finalmente el costo fijo en moneda de destino. Los tres porcentajes se representan como fracciones y se aplican sucesivamente. La salida neta se redondea hacia abajo a la precisión del activo de destino. Los límites y la liquidez se expresan en el activo de entrada. Para registrar un costo cero, se aporta un cero explícito.

La proyección bruta calcula el mismo circuito sin costos. La diferencia entre esa proyección y el capital final estima el costo total en la moneda inicial. La ganancia neta es capital final menos capital inicial. La rentabilidad divide esa ganancia por el capital inicial y multiplica por 100. El margen de seguridad expresa la diferencia, en puntos porcentuales, frente al umbral configurado.

La antigüedad usa la fecha de publicación si está disponible y, como alternativa, la recepción. La ventana inicial de 15 segundos y la vigencia de revisión de un día son parámetros conservadores configurables para el motor local. El objetivo futuro de muestreo es de cinco segundos sujeto a las condiciones del proveedor. Las fechas incluyen zona horaria y la zona de presentación prevista es Argentina.

La evaluación requiere evidencia de operación permitida, medios de pago, titularidad y normativa aplicable, con fuentes y fecha de revisión. La fase 1 controla la presencia de esa evidencia y su vigencia local. La exactitud de la evidencia sigue a cargo de quien la aporta. Las fuentes oficiales y la normativa aplicable al circuito Mercado Pago, USD y stablecoins quedan pendientes de investigación. No hay fecha de revisión normativa real registrada.

## Alcance pendiente

- Profundidad del libro, comisiones por tramo, costos en activos externos, impuestos por situación fiscal y variación durante la acreditación. La proyección actual aplica tasas, liquidez y costos únicos por paso.
- Evaluación integral de la frescura durante la ejecución, verificación de compatibilidad real de redes y restricciones por cuenta.
- Descubrimiento de rutas, API de la aplicación, interfaz, historial, paper trading avanzado y alertas.
- Python 3.12 con biblioteca estándar para el núcleo. La fase 2 usa HTTPX y WebSockets. FastAPI, Pydantic y SQLAlchemy se incorporarán con sus respectivos componentes. SQLite queda previsto para desarrollo y PostgreSQL para persistencia, con Supabase como opción futura.
- El contenedor inicial ejecuta pruebas locales. El despliegue público requiere autenticación y autorización.

## Entrega de la fase 2

El proceso independiente consulta CriptoYa, DolarApi y ComparaDólar en paralelo e incorpora el canal público de Kraken. Conserva en memoria la última cotización por fuente, mercado y par. Calcula la vigencia al emitir cada instantánea y conserva los datos anteriores como desconectados durante interrupciones. Una sesión nueva de Kraken reconstruye su caché con los primeros datos recibidos.

El presupuesto de consultas se aplica por proveedor. CriptoYa procesa ocho pares de manera secuencial, con al menos un segundo entre peticiones y un minuto de pausa al completar el lote. Los fallos hacen visible la desconexión y activan una espera exponencial que respeta `Retry-After`. Después de tres fallos se abre el circuito y se deja pasar un intento de recuperación tras la pausa. La latencia HTTP mide el tiempo total de las solicitudes por lote. En Kraken se informa el mayor retraso entre publicación y recepción del último mensaje válido, sujeto a la sincronización de relojes.

El formato separa precio unitario, precio con costos publicado por la fuente, cantidad en punta de libro, volumen solicitado y hora de origen. Los importes salen como cadenas decimales. Cada precio se mantiene como referencia para el análisis. La fase 3 incorporará las reglas que convierten evidencia suficiente en pasos de circuitos. El [inventario de fuentes](FUENTES.md) registra la cobertura y restricciones.
