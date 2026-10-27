from pydantic import BaseModel


class MetricasLocalesOut(BaseModel):
    proyectos_finalizados: int
    suministros_movilizados: int
    porcentaje_consorcios: float
