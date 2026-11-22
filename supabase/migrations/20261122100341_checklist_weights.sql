-- Postura do usuário no checklist: quanto vale cada "Sim" e quanto desconta cada "Não".
--
-- nota = max(0, (Sim x yes_weight - Não x no_weight) / (total x yes_weight)).
-- Padrão (1; 0) = fração de "Sim". no_weight > 0 deixa a nota mais conservadora.
-- Uma linha por usuário; sem linha, vale o padrão.

create table public.checklist_weights (
    user_id uuid primary key references auth.users (id) on delete cascade,
    yes_weight numeric(4, 2) not null default 1 check (yes_weight > 0 and yes_weight <= 3),
    no_weight numeric(4, 2) not null default 0 check (no_weight >= 0 and no_weight <= 5),
    updated_at timestamptz not null default now()
);

alter table public.checklist_weights enable row level security;

create policy "checklist_weights_own_rows" on public.checklist_weights
    for all
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create trigger checklist_weights_set_updated_at
    before update on public.checklist_weights
    for each row execute function public.set_updated_at();
