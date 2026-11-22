-- Taxa contratada dos títulos do Tesouro, por carteira (marcação a mercado).
--
-- contracted_rate em fração (0.0645 = 6,45% a.a.; no IPCA+, acima do IPCA).
-- estimated = true quando a taxa foi calculada pelo preço médio e pela data da compra.
-- A FK composta (portfolio_id, user_id) garante que a linha só aponta para carteira
-- do próprio usuário, como em positions e trades.

create table public.bond_terms (
    user_id uuid not null references auth.users (id) on delete cascade,
    portfolio_id uuid not null,
    ticker text not null check (char_length(ticker) between 1 and 20),
    contracted_rate numeric(8, 6) not null check (contracted_rate between -0.05 and 0.5),
    purchase_date date,
    estimated boolean not null default false,
    updated_at timestamptz not null default now(),
    primary key (portfolio_id, ticker),
    foreign key (portfolio_id, user_id)
        references public.portfolios (id, user_id) on delete cascade
);

create index bond_terms_user_idx on public.bond_terms (user_id);

alter table public.bond_terms enable row level security;

create policy "bond_terms_own_rows" on public.bond_terms
    for all
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create trigger bond_terms_set_updated_at
    before update on public.bond_terms
    for each row execute function public.set_updated_at();
