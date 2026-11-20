-- Registro atômico de uma operação e da posição resultante.
--
-- O cálculo do preço médio é regra de domínio e roda em Python. O banco só garante que
-- a operação e a nova posição sejam gravadas juntas (tudo ou nada) e que a posição não
-- tenha mudado entre a leitura feita pela aplicação e a gravação (controle otimista).

create or replace function public.record_trade(
    p_portfolio_id uuid,
    p_ticker text,
    p_asset_class public.asset_class,
    p_side public.trade_side,
    p_strategy public.strategy_type,
    p_traded_at timestamptz,
    p_quantity numeric,
    p_price numeric,
    p_costs numeric,
    p_expected_quantity numeric,      -- quantidade que a aplicação leu (null = sem posição)
    p_new_quantity numeric,
    p_new_average_price numeric,
    p_new_manual_override boolean
)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_user_id uuid := (select auth.uid());
    v_current_quantity numeric;
    v_trade_id uuid;
begin
    -- Trava a carteira: operações da mesma carteira passam a ser gravadas em fila.
    -- Sem isso, duas primeiras compras simultâneas do mesmo ativo leriam "sem posição"
    -- e a segunda sobrescreveria a primeira.
    perform 1 from public.portfolios where id = p_portfolio_id for update;
    if not found then
        raise exception 'Carteira % não encontrada.', p_portfolio_id using errcode = 'P0002';
    end if;

    select quantity into v_current_quantity
    from public.positions
    where portfolio_id = p_portfolio_id and ticker = p_ticker;

    -- `is distinct from` trata null corretamente (null = null é desconhecido, não true).
    if v_current_quantity is distinct from p_expected_quantity then
        raise exception 'A posição de % mudou desde a leitura (esperado %, atual %).',
            p_ticker, p_expected_quantity, v_current_quantity
            using errcode = '40001';
    end if;

    insert into public.trades (
        user_id, portfolio_id, ticker, side, strategy, traded_at, quantity, price, costs
    )
    values (
        v_user_id, p_portfolio_id, p_ticker, p_side, p_strategy, p_traded_at,
        p_quantity, p_price, p_costs
    )
    returning id into v_trade_id;

    -- Na atualização a classe de ativo não muda: o usuário pode tê-la corrigido à mão.
    insert into public.positions (
        user_id, portfolio_id, ticker, asset_class, quantity, average_price, manual_override
    )
    values (
        v_user_id, p_portfolio_id, p_ticker, p_asset_class,
        p_new_quantity, p_new_average_price, p_new_manual_override
    )
    on conflict (portfolio_id, ticker) do update
        set quantity = excluded.quantity,
            average_price = excluded.average_price,
            manual_override = excluded.manual_override;

    return v_trade_id;
end;
$$;

revoke execute on function public.record_trade(
    uuid, text, public.asset_class, public.trade_side, public.strategy_type, timestamptz,
    numeric, numeric, numeric, numeric, numeric, numeric, boolean
) from public, anon;

grant execute on function public.record_trade(
    uuid, text, public.asset_class, public.trade_side, public.strategy_type, timestamptz,
    numeric, numeric, numeric, numeric, numeric, numeric, boolean
) to authenticated;
