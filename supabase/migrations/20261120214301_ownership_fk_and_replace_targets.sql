-- Correções de revisão do schema inicial.
--
-- 1) Posse da carteira garantida pelo banco.
--    O RLS das tabelas filhas só checa `user_id = auth.uid()`. Uma FK simples para
--    `portfolios(id)` é validada SEM RLS, então um usuário poderia gravar linhas com o
--    próprio user_id apontando para a carteira de outra pessoa (e, em `allocation_targets`,
--    ocupar a PK `(portfolio_id, asset_class)` da carteira alheia). Com a FK composta
--    `(portfolio_id, user_id) -> portfolios(id, user_id)`, a linha filha só existe se a
--    carteira pertencer ao mesmo usuário.

alter table public.portfolios
    add constraint portfolios_id_user_id_key unique (id, user_id);

alter table public.positions
    drop constraint positions_portfolio_id_fkey,
    add constraint positions_portfolio_owner_fkey
        foreign key (portfolio_id, user_id)
        references public.portfolios (id, user_id) on delete cascade;

alter table public.trades
    drop constraint trades_portfolio_id_fkey,
    add constraint trades_portfolio_owner_fkey
        foreign key (portfolio_id, user_id)
        references public.portfolios (id, user_id) on delete cascade;

alter table public.allocation_targets
    drop constraint allocation_targets_portfolio_id_fkey,
    add constraint allocation_targets_portfolio_owner_fkey
        foreign key (portfolio_id, user_id)
        references public.portfolios (id, user_id) on delete cascade;

-- 2) `updated_at` mantido automaticamente em toda atualização.

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

create trigger portfolios_set_updated_at
    before update on public.portfolios
    for each row execute function public.set_updated_at();

create trigger positions_set_updated_at
    before update on public.positions
    for each row execute function public.set_updated_at();

-- 3) Substituição atômica do perfil de alocação alvo.
--    Um upsert simples não remove classes que deixaram de existir no perfil, e a soma
--    de 100% deixaria de valer. A função apaga e reinsere na mesma transação.
--    `security invoker`: roda com as permissões de quem chama, então o RLS continua valendo.
--    O dono vem de `auth.uid()`, nunca de um parâmetro enviado pelo cliente.

create or replace function public.replace_allocation_targets(
    p_portfolio_id uuid,
    p_targets jsonb
)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
begin
    -- O RLS restringe o delete às linhas do próprio usuário.
    delete from public.allocation_targets
    where portfolio_id = p_portfolio_id;

    -- `p_targets` é um objeto {"BR_EQUITY": 60, ...}. Carteira de outro usuário falha
    -- na FK composta, e classe inválida falha no cast para o enum.
    insert into public.allocation_targets (user_id, portfolio_id, asset_class, target_pct)
    select
        (select auth.uid()),
        p_portfolio_id,
        t.key::public.asset_class,
        t.value::numeric(5, 2)
    from jsonb_each_text(p_targets) as t (key, value);
end;
$$;

revoke execute on function public.replace_allocation_targets(uuid, jsonb) from public, anon;
grant execute on function public.replace_allocation_targets(uuid, jsonb) to authenticated;
