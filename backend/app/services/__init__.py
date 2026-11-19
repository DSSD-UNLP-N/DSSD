class ServicioError(Exception):
    """Error de un servicio que la API devuelve tal cual: `{"detail": mensaje}` con `status` (main.py)."""

    status = 400

    def __init__(self, mensaje: str, status: int | None = None):
        super().__init__(mensaje)
        if status is not None:
            self.status = status
