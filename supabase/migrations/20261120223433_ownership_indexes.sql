-- Índices para as chaves estrangeiras de posse e para os filtros do RLS.
--
-- O RLS acrescenta `user_id = auth.uid()` a toda consulta: sem índice em
-- portfolios.user_id e trades.user_id, cada leitura varre a tabela inteira.
-- As FKs compostas (portfolio_id, user_id) também ganham índice exato, para que
-- apagar uma carteira (on delete cascade) não precise de varredura nas filhas.

create index if not exists portfolios_user_idx on public.portfolios (user_id);
create index if not exists trades_user_idx on public.trades (user_id);

create index if not exists positions_portfolio_owner_idx
    on public.positions (portfolio_id, user_id);
create index if not exists trades_portfolio_owner_idx
    on public.trades (portfolio_id, user_id);
create index if not exists allocation_targets_portfolio_owner_idx
    on public.allocation_targets (portfolio_id, user_id);
