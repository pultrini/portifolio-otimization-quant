-- Schema inicial: carteiras, posições, operações e perfil de alocação alvo.
-- Todas as tabelas têm RLS habilitado e o usuário só acessa as próprias linhas.
-- Valores monetários usam numeric (nunca float). Timestamps em UTC (timestamptz).

create type public.asset_class as enum (
    'BR_EQUITY',
    'INTL_EQUITY',
    'BR_FIXED_INCOME',
    'INTL_FIXED_INCOME',
    'CRYPTO'
);

create type public.strategy_type as enum (
    'BUY_AND_HOLD',
    'SWING_TRADE',
    'DAY_TRADE',
    'POSITION_TRADE',
    'ARBITRAGE',
    'HEDGE_OPTIONS'
);

create type public.trade_side as enum ('BUY', 'SELL');

create table public.portfolios (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    name text not null check (char_length(name) between 1 and 80),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table public.positions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    portfolio_id uuid not null references public.portfolios (id) on delete cascade,
    ticker text not null check (char_length(ticker) between 1 and 20),
    asset_class public.asset_class not null,
    quantity numeric(20, 8) not null check (quantity >= 0),
    average_price numeric(20, 8) not null check (average_price >= 0),
    -- Edição manual do preço médio sobrescreve o valor calculado (CLAUDE.md 5.3).
    manual_override boolean not null default false,
    updated_at timestamptz not null default now(),
    unique (portfolio_id, ticker)
);

create table public.trades (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    portfolio_id uuid not null references public.portfolios (id) on delete cascade,
    ticker text not null check (char_length(ticker) between 1 and 20),
    side public.trade_side not null,
    strategy public.strategy_type not null,
    traded_at timestamptz not null,
    quantity numeric(20, 8) not null check (quantity > 0),
    price numeric(20, 8) not null check (price >= 0),
    costs numeric(20, 8) not null default 0 check (costs >= 0),
    created_at timestamptz not null default now()
);

create table public.allocation_targets (
    user_id uuid not null references auth.users (id) on delete cascade,
    portfolio_id uuid not null references public.portfolios (id) on delete cascade,
    asset_class public.asset_class not null,
    -- Percentual alvo (0-100). A soma por carteira é validada no Domain (tolerância 0.01 p.p.).
    target_pct numeric(5, 2) not null check (target_pct >= 0 and target_pct <= 100),
    primary key (portfolio_id, asset_class)
);

create index positions_user_idx on public.positions (user_id);
create index trades_portfolio_idx on public.trades (portfolio_id, traded_at);
create index allocation_targets_user_idx on public.allocation_targets (user_id);

alter table public.portfolios enable row level security;
alter table public.positions enable row level security;
alter table public.trades enable row level security;
alter table public.allocation_targets enable row level security;

create policy "portfolios_own_rows" on public.portfolios
    for all
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy "positions_own_rows" on public.positions
    for all
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy "trades_own_rows" on public.trades
    for all
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy "allocation_targets_own_rows" on public.allocation_targets
    for all
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);
