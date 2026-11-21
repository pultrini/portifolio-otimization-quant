-- Objetivos de poupança com foco em constância (desafio 1, 2, 3... ou valor fixo).
--
-- Um objetivo tem N passos numerados; cada depósito marca um passo. A FK composta
-- (goal_id, user_id) garante que um depósito só aponta para objetivo do mesmo usuário,
-- e a unicidade (goal_id, step) impede depositar o mesmo passo duas vezes.

create table public.savings_goals (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    name text not null check (char_length(name) between 1 and 80),
    mode text not null check (mode in ('PROGRESSIVE', 'FIXED')),
    frequency text not null check (frequency in ('DAILY', 'WEEKLY')),
    unit_amount numeric(20, 2) not null check (unit_amount > 0),
    step_count integer not null check (step_count between 1 and 100000),
    start_date date not null,
    end_date date not null,
    created_at timestamptz not null default now(),
    check (end_date >= start_date),
    unique (id, user_id)
);

create table public.goal_deposits (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    goal_id uuid not null,
    step integer not null check (step >= 1),
    amount numeric(20, 2) not null check (amount > 0),
    deposited_on date not null,
    created_at timestamptz not null default now(),
    unique (goal_id, step),
    foreign key (goal_id, user_id) references public.savings_goals (id, user_id) on delete cascade
);

create index savings_goals_user_idx on public.savings_goals (user_id);
create index goal_deposits_owner_idx on public.goal_deposits (goal_id, user_id);
create index goal_deposits_user_idx on public.goal_deposits (user_id);

alter table public.savings_goals enable row level security;
alter table public.goal_deposits enable row level security;

create policy "savings_goals_own_rows" on public.savings_goals
    for all
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create policy "goal_deposits_own_rows" on public.goal_deposits
    for all
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);
