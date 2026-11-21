-- Respostas manuais do checklist de aporte (prevalecem sobre as automáticas).
--
-- As respostas são do usuário, não da carteira: a opinião sobre a governança de uma
-- empresa vale para todas as carteiras dele. Uma linha por (usuário, ticker, pergunta).
-- `answer` null não é gravado: apagar a linha faz a resposta automática voltar a valer.

create table public.checklist_answers (
    user_id uuid not null references auth.users (id) on delete cascade,
    ticker text not null check (char_length(ticker) between 1 and 20),
    question_key text not null check (
        question_key in (
            'roe', 'cagr', 'dividends', 'research', 'age', 'leadership', 'perennial',
            'blue_chip', 'governance', 'independence', 'low_debt',
            'location', 'properties', 'price_to_book', 'reit_dividends', 'dependency',
            'sector_yield'
        )
    ),
    answer boolean not null,
    updated_at timestamptz not null default now(),
    primary key (user_id, ticker, question_key)
);

alter table public.checklist_answers enable row level security;

create policy "checklist_answers_own_rows" on public.checklist_answers
    for all
    to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create trigger checklist_answers_set_updated_at
    before update on public.checklist_answers
    for each row execute function public.set_updated_at();
