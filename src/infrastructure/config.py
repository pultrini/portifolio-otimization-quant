"""Configuração da aplicação lida de variáveis de ambiente e do arquivo `.env`."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações de runtime.

    Nunca hardcodar chaves ou URLs. Apenas a `anon key` é usada na apresentação.
    """

    # Lê variáveis de ambiente e, se existir, o `.env` da pasta onde o app é iniciado.
    # `extra="ignore"` deixa o `.env` ter chaves usadas por outros scripts (ex.: service_role).
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Default vazio em vez de obrigatório: os testes importam o módulo sem `.env`, e o
    # `app.py` mostra uma mensagem clara na tela quando as chaves estão faltando.
    supabase_url: str = ""
    supabase_anon_key: str = ""
    log_level: str = "INFO"

    # Raiz das camadas bronze/silver/gold (fora do git). Relativa à pasta de execução.
    data_dir: Path = Path("data")
    # Horizonte de histórico de preços baixado pelo pipeline.
    market_history_years: int = Field(default=5, ge=1, le=25)
