"""Use case: atualizar dados de mercado da carteira (roda o pipeline medalhão)."""

from collections.abc import Sequence

from pydantic import BaseModel

from domain.repositories.market_data_repository import MarketDataRefresher
from domain.repositories.position_repository import PositionRepository
from domain.value_objects.ticker import Ticker


class RefreshMarketDataResponse(BaseModel):
    tickers: list[str]
    rows_by_layer: dict[str, int]
    failed_tickers: dict[str, str]


class RefreshMarketData:
    """Baixa e processa cotações dos ativos da carteira e das séries de referência."""

    def __init__(
        self, refresher: MarketDataRefresher, positions: PositionRepository, years: int
    ) -> None:
        self._refresher = refresher
        self._positions = positions
        self._years = years

    def execute(
        self, portfolio_id: str, extra_tickers: Sequence[str] = ()
    ) -> RefreshMarketDataResponse:
        """Atualiza os tickers da carteira mais os extras informados.

        Benchmarks, CDI, T-Bill e câmbio entram sempre (o pipeline os inclui sozinho).
        """
        tickers = {p.ticker for p in self._positions.list_positions(portfolio_id)}
        tickers |= {Ticker.parse(t) for t in extra_tickers}
        ordered = sorted(tickers)
        report = self._refresher.refresh(ordered, self._years)
        return RefreshMarketDataResponse(
            tickers=[t.symbol for t in ordered],
            rows_by_layer=report.rows_by_layer,
            failed_tickers=report.failed_tickers,
        )
