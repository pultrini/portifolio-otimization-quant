-- Classes imobiliárias: fundos imobiliários da B3 (FII) e REITs americanos.
-- Antes os FIIs ficavam em BR_EQUITY e os REITs em INTL_EQUITY; a reclassificação das
-- posições existentes é feita pelo app (botão na página Carteira), com prévia.
alter type public.asset_class add value if not exists 'BR_REAL_ESTATE';
alter type public.asset_class add value if not exists 'INTL_REAL_ESTATE';
