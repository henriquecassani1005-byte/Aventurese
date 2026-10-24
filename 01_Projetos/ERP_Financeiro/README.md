# ERP Financeiro Local (MVP)

Gestão financeira pessoal 100% local: importa CSVs de bancos, consolida contas em **BRL e EUR**, projeta parcelamentos de cartão e cruza gastos com orçamento por categoria.

**Stack:** Python, Pandas, SQLite, Streamlit. Sem servidor, sem nuvem. Os dados ficam em `data/erp.db` (ignorado pelo git).

## Como rodar

```bash
cd 01_Projetos/ERP_Financeiro
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # ajuste BRL_PER_EUR
streamlit run app.py
```

Testes: `pip install pytest && pytest`

## Rotina semanal

| Passo | Onde | O que fazer |
|---|---|---|
| 1 | Cadastros | Criar as contas (uma vez) |
| 2 | Importar CSV | Escolher conta e perfil, subir o arquivo, conferir o preview, importar |
| 3 | Cadastros | Primeira vez: calibrar o saldo para igualar o do banco. Depois, conferir de tempos em tempos |
| 4 | Lançamentos | Classificar o que ficou sem categoria (ou criar regra em Cadastros) |
| 5 | Parcelamentos | Registrar compras novas no cartão |
| 6 | Dashboard | Ler Caixa Livre Real e Realizado vs. Orçado |

CSVs de teste em `samples/`. Perfis iniciais: `BR_Generico`, `EU_Generico`, `Exemplo_Debito_Credito`.

## Estrutura

```
ERP_Financeiro/
  app.py                  entrada do Streamlit (só monta abas)
  requirements.txt
  .env.example            taxa BRL por EUR e moeda padrão
  config/parsers.json     um perfil por banco (layout do CSV)
  samples/                CSVs de exemplo
  tests/                  pytest: motor de dados e smoke test do app
  erp/
    config.py             caminhos, moedas, defaults do .env
    database.py           SQLite: schema e todo o SQL (única camada com SQL)
    services.py           orquestra database + rules (importar, projetar, reaplicar regras)
    rules/                regras de negócio em Pandas, sem SQL e sem Streamlit
      parsers.py          leitura configurável de CSV
      etl.py              higienização e hash de deduplicação
      categorization.py   regras por palavra chave
      ledger.py           conversão BRL/EUR e consolidação de saldos
      installments.py     projeção de parcelas por mês
      cashflow.py         Caixa Livre Real e fluxo futuro
      budget.py           Realizado vs. Orçado
    ui/                   telas Streamlit, uma por aba
```

## Como cada módulo funciona

**Ingestão (ETL).** O perfil define delimitador, encoding, formato de data, separador decimal e milhar, e os nomes das colunas. Suporta coluna única de valor com sinal ou colunas separadas de débito e crédito, e `invert_sign` para extratos de cartão. Linhas com data ou valor ilegível são rejeitadas e contadas. A conta e o perfil precisam ter a mesma moeda.

**Deduplicação.** Cada transação recebe um hash de conta, data, valor e descrição normalizada (ou do ID do banco, se `id_col` estiver no perfil), mais um índice de ocorrência dentro do arquivo. Efeito: reimportar o mesmo arquivo ou extratos semanais sobrepostos não duplica, e duas compras idênticas no mesmo dia continuam sendo duas.

**Multimoeda.** Cada transação guarda a moeda original. A taxa é estática: o painel lateral tem prioridade sobre o `.env`. O seletor global converte patrimônio, faturas, orçamento e fluxo de caixa.

**Parcelamentos.** Valor total dividido em centavos exatos (a soma das parcelas é sempre igual ao total), alocado a partir do mês da primeira parcela, que você escolhe.

**Caixa Livre Real.** Saldo consolidado das contas menos as faturas projetadas do mês de referência (padrão: próximo mês).

**Orçamento.** Limite mensal por categoria, em qualquer moeda. Realizado do mês é a soma de lançamentos em conta e parcelas que vencem no mês. Categorias marcadas como não despesa (Receita, Transferência, Fatura Cartão) ficam fora.

## Premissas e limites conhecidos

| Tema | Premissa | Risco |
|---|---|---|
| Layouts dos bancos | Os perfis em `config/parsers.json` são genéricos | Ajuste nomes de colunas, encoding e formatos ao CSV real do seu banco |
| Taxa de câmbio | Estática, vale para todo o histórico | Patrimônio em outra moeda é uma aproximação, não valor de mercado |
| Fatura do mês corrente | Assume que já foi paga e debitada na conta | Se não foi, escolha o mês corrente como referência no Dashboard |
| Pagamento da fatura | Sai do banco como débito | Classifique como Fatura Cartão (regra FATURA já vem pronta) para não contar em dobro com as parcelas |
| Compras à vista no cartão | Não aparecem no CSV do banco até a fatura | Cadastre como parcelamento de 1 parcela |
| Transferências entre contas | Entram como saída em uma e entrada na outra | Classifique como Transferência, senão aparecem como gasto sem categoria |
| Dedup | Extrato cortado no meio de um dia com lançamentos idênticos | Pode gerar ou perder uma ocorrência. Extratos por dias completos evitam |
| Valores | Armazenados como REAL com 2 casas | Adequado ao MVP. Para contabilidade formal, migrar para centavos inteiros |
| Segurança | Banco local sem criptografia | Mantenha o disco cifrado. `data/*.db` e `.env` estão no `.gitignore` |
