# ArbiRadar AR

ArbiRadar AR busca evaluar circuitos de arbitraje con capital de referencia de $1.000.000 ARS. La fase 1 entrega un motor de cálculo para rutas ingresadas por código, con un mínimo configurable de 1% de rentabilidad neta.

## Cómo ejecutar las pruebas

Con Python 3.12 instalado, abre una terminal en la carpeta del proyecto y ejecuta:

```bash
python -m unittest discover -v
```

Los casos de prueba incluyen cotizaciones, fuentes y plataformas ficticias identificadas como ejemplos de prueba. El motor funciona sin conexión a internet. Con Docker disponible, el comando equivalente es `docker compose run --build --rm pruebas`.

## Cómo se organiza

- `backend/models/financial.py` define los activos por plataforma, cotizaciones, costos y evidencia.
- `backend/engine/financial.py` evalúa rutas completas aportadas como entrada.
- `backend/validators/circuits.py` comprueba vigencia, disponibilidad, restricciones, límites y redes.
- `tests/test_financial.py` contiene ejemplos reproducibles de uso y pruebas.
- [Plan y metodología](docs/ROADMAP.md).
