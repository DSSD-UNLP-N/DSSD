from pydantic import BaseModel, ConfigDict, Field

from app.models import Gravedad


class EmergenciaIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # Largos máximos = los de las columnas (Postgres los hace cumplir; SQLite no).
    tipo: str = Field(min_length=1, max_length=40)
    nivel_gravedad: Gravedad
    zona_afectada: str = Field(min_length=1, max_length=200)
    descripcion: str = Field(min_length=1, max_length=2000)
