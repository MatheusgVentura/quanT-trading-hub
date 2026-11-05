# Manual Mestre: Do Capital Inicial na XP à Engenharia de Bots e Backtesting

Este documento reúne a arquitetura completa para quem possui formação em Engenharia de Software e deseja entrar no mercado financeiro com rigor estatístico, custos controlados e sistemas automatizados, utilizando R\$ 100 reais como laboratório empírico.

## 1. Operando com R\$ 100 na XP Investimentos: Regras e Riscos Operacionais

Operar capital real é um marco importante para calibrar a psicologia, mas uma conta de R\$ 100 na bolsa brasileira (B3) possui restrições severas de custos que um desenvolvedor precisa blindar no modelo operacional.

### 1.1 Checklist Obrigatório Antes da Primeira Ordem

1. **Ativação do RLP (Retail Liquidity Provider):**

   * *O que é:* Um sistema que permite à corretora atuar como contraparte da sua ordem em ações e derivativos.

   * *Impacto financeiro:* Garante **taxa de corretagem ZERO** na XP para ações. Sem o RLP ativo, a corretora pode cobrar taxas fixas por ordem executada, o que inviabilizaria operações com R\$ 100.

2. **Mercado Fracionário (Obrigatório Sufixo 'F'):**

   * No mercado à vista padrão da B3, os ativos são negociados em lotes de 100 em 100 ações. Comprar 1 lote padrão de `ITUB4` a R\$ 39,60 exige R$ 3.960,00.

   * Para comprar 1, 2 ou 3 ações com seus R\$ 100, você **deve digitar o código com a letra F** ao final: `ITUB4F`, `PETR4F`, `WEGE3F`.

3. **Custo da B3 (Emolumentos e Liquidação):**

   * A B3 cobra uma taxa percentual de liquidação e negociação em torno de **\~0,03%** do volume negociado.

   * Em uma compra de R\$ 79,00 (2 ações), o custo da B3 gira em torno de **R\$ 0,02**, perfeitamente suportável para uma conta pequena.

### 1.2 O Risco Fatal: Multa de Zepagem Compulsória (Mesa de Risco)

* **A Armadilha do Day Trade:** Se você abrir uma posição como "Day Trade" na corretora e esquecer de encerrar antes do fechamento do pregão (por volta das 17h55), o motor de risco da XP zera sua posição à força no leilão de fechamento.

* **O Prejuízo:** A zeragem compulsória pela mesa não utiliza o benefício da corretagem zero do RLP. A taxa de intervenção manual da mesa de risco costuma ser de **R\$ 20,00 a R$ 45,00 por ordem**. Um único esquecimento elimina 40% da sua conta de R\$ 100.

* **Regra de Ouro Inicial:** Opere no modo **Swing Trade / Posição (Custódia)**. Comprando as ações para swing trade, os papéis tornam-se de fato seus, você pode mantê-los por dias sem risco de liquidação compulsória e o risco de multas operacionais é zero.

### 1.3 Tributação e DARF (Simplificado)

* **Swing Trade (Ações):** Vendas mensais de até R\$ 20.000,00 no mercado de ações são **isentas de Imposto de Renda** sobre o ganho de capital para pessoas físicas. Com R\$ 100 em swing trade, você não tem dor de cabeça com guias de DARF.

* **Day Trade (Ações):** Não possui isenção. Qualquer R\$ 1,00 de lucro no mesmo dia deve recolher 20% de IR via emissão manual de DARF no mês subsequente.

## 2. A Pilha Tecnológica Quantitativa (100% Custo Zero)

Você não precisa pagar assinaturas de plataformas como Profit Pro, feeds caros da B3 ou ferramentas pagas de gráficos para criar e rodar sistemas analíticos.

```
┌────────────────────────────────────────────────────────┐
│                   A Stack Gratuita                     │
├──────────────────────────┬─────────────────────────────┤
│ Camada                   │ Ferramenta / Biblioteca     │
├──────────────────────────┼─────────────────────────────┤
│ Linguagem Principal      │ Python 3.10+ / 3.11+        │
│ Manipulação de Dados     │ Pandas, NumPy               │
│ Coleta Histórica B3      │ yfinance (sem chaves / API) │
│ Visualização & Plots     │ Matplotlib, Seaborn         │
│ Backtesting Vetorizado   │ Script nativo / VectorBT    │
│ Ambientes de Teste Bot   │ Binance Testnet, Alpaca API │
│ IDE & Controle de Versão │ VS Code, Git, GitHub        │
└──────────────────────────┴─────────────────────────────┘


```

## 3. Arquitetura de Software para Bots de Trading

Um bot robusto nunca mistura a lógica de decisão estratégica com o envio de pacotes na rede. A arquitetura clássica divide-se em pipelines desacoplados:

```
 ┌──────────────────────┐
 │   Feed de Mercado    │ ── WebSocket (Cotações tick-a-tick / livros)
 └──────────┬───────────┘
            │ Evento
            ▼
 ┌──────────────────────┐
 │ Motor de Estratégia  │ ── Processa médias, estatística, desvios padrão
 └──────────┬───────────┘
            │ Sinal (Buy / Sell)
            ▼
 ┌──────────────────────┐
 │   Gestor de Risco    │ ── Kill-Switch, limites de perda diária, cálculo de lote
 └──────────┬───────────┘
            │ Ordem Validada
            ▼
 ┌──────────────────────┐
 │  Roteador de Ordens  │ ── Chamadas REST API autenticadas (HMAC-SHA256)
 └──────────────────────┘


```

### O Que o Engenheiro de Software Constrói no Bot:

1. **Reconexão Resiliente:** WebSockets caem. O bot deve implementar *exponential backoff* e sincronizar o estado da conta após cada reconexão.

2. **Kill-Switch (Disjuntor de Segurança):** Se a estratégia acumular perda de 2% no dia ou se a latência subir além de 500ms, o bot cancela todas as ordens abertas e encerra a execução com log de erro (`sys.exit(1)`).

3. **Idempotência de Ordens:** Evitar o envio de ordens duplicadas quando um endpoint REST sofrer timeout sem confirmação de status.

## 4. Código Completo: Motor de Backtesting Vetorizado

Este script pronto pode ser executado diretamente em seu computador. Ele baixa dados de `ITUB4.SA` (ou qualquer outro ativo), simula a estratégia de afastamento da média com desconto de custos da B3, gera relatório quantitativo institucional e exibe os gráficos de evolução patrimonial e drawdown.

### Instalação das Dependências

```
pip install pandas numpy yfinance matplotlib


```

### Código: `engine_quant_xp.py`

```
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt

def executar_backtest_quant(
    ticker: str = "ITUB4.SA",
    periodo: str = "3y",
    media_rapida: int = 9,
    media_lenta: int = 21,
    custo_b3_por_trade: float = 0.0003  # 0.03% (emolumentos + liquidação)
):
    print(f"[*] Conectando ao Yahoo Finance e baixando dados para {ticker}...")
    df = yf.download(ticker, period=periodo, interval="1d", progress=False)

    if df.empty:
        raise ValueError(f"Não foram encontrados dados para o ativo {ticker}.")

    # Tratamento de formato MultiIndex do yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df = df.xs(ticker, axis=1, level=1)

    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()

    # 1. Geração de Indicadores (Médias Móveis Exponenciais)
    df['EMA_Rapida'] = df['Close'].ewm(span=media_rapida, adjust=False).mean()
    df['EMA_Lenta'] = df['Close'].ewm(span=media_lenta, adjust=False).mean()

    # 2. Definição da Lógica (Sinal)
    # Compra quando a rápida cruza para cima; Encerra quando cruza para baixo
    df['Sinal'] = np.where(df['EMA_Rapida'] > df['EMA_Lenta'], 1, 0)

    # 3. Proteção Contra Look-Ahead Bias (Espiar o Futuro)
    # A decisão de fechamento do dia t só pode ser executada no dia t+1
    df['Posicao'] = df['Sinal'].shift(1).fillna(0)

    # 4. Cálculo de Retornos e Fricção de Custos da B3
    df['Retorno_Mercado'] = df['Close'].pct_change().fillna(0)
    
    # Identifica transição de posição (mudou de 0 para 1 ou de 1 para 0)
    df['Troca_Posicao'] = df['Posicao'].diff().abs().fillna(0)
    df['Custos_B3'] = df['Troca_Posicao'] * custo_b3_por_trade

    # Retorno líquido da estratégia
    df['Retorno_Estrategia'] = (df['Posicao'] * df['Retorno_Mercado']) - df['Custos_B3']

    # 5. Evolução Patrimonial Acumulada (Base Inicial: 1.0)
    df['Curva_Mercado'] = (1 + df['Retorno_Mercado']).cumprod()
    df['Curva_Estrategia'] = (1 + df['Retorno_Estrategia']).cumprod()

    # 6. Cálculo das Métricas Quantitativas Institucionais
    dias_uteis = len(df)
    anos = dias_uteis / 252.0

    retorno_acum_estrat = (df['Curva_Estrategia'].iloc[-1] - 1) * 100
    retorno_acum_hold = (df['Curva_Mercado'].iloc[-1] - 1) * 100

    cagr_estrat = ((df['Curva_Estrategia'].iloc[-1]) ** (1 / anos) - 1) * 100
    cagr_hold = ((df['Curva_Mercado'].iloc[-1]) ** (1 / anos) - 1) * 100

    volatilidade_anual = df['Retorno_Estrategia'].std() * np.sqrt(252) * 100
    sharpe_ratio = (df['Retorno_Estrategia'].mean() * 252) / (df['Retorno_Estrategia'].std() * np.sqrt(252) + 1e-9)

    # Drawdown Subaquático
    pico = df['Curva_Estrategia'].cummax()
    drawdown = (df['Curva_Estrategia'] - pico) / pico
    max_drawdown = drawdown.min() * 100

    # Profit Factor
    ganhos = df[df['Retorno_Estrategia'] > 0]['Retorno_Estrategia'].sum()
    perdas = df[df['Retorno_Estrategia'] < 0]['Retorno_Estrategia'].abs().sum()
    profit_factor = ganhos / (perdas + 1e-9)

    # 7. Relatório no Terminal
    print("\n" + "=" * 55)
    print(f"      RELATÓRIO QUANTITATIVO DE PERFORMANCE: {ticker}")
    print("=" * 55)
    print(f"Janela de Teste:            {periodo} (~{anos:.1f} anos de pregão)")
    print(f"Retorno Total Estratégia:   {retorno_acum_estrat:.2f}%")
    print(f"Retorno Total Buy & Hold:   {retorno_acum_hold:.2f}%")
    print(f"CAGR (Retorno Anualizado):  {cagr_estrat:.2f}% ao ano")
    print(f"Sharpe Ratio Anualizado:    {sharpe_ratio:.2f}")
    print(f"Volatilidade Anualizada:    {volatilidade_anual:.2f}%")
    print(f"Max Drawdown (Pior Queda):  {max_drawdown:.2f}%")
    print(f"Profit Factor:              {profit_factor:.2f}")
    print(f"Total de Transações (Giro): {int(df['Troca_Posicao'].sum())}")
    print("=" * 55)

    # 8. Gráfico Visual com Curva de Capital e Drawdown
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={'height_ratios': [3, 1]})

    ax1.plot(df.index, df['Curva_Estrategia'], label='Estratégia Quant (EMA)', color='#0052cc', lw=1.6)
    ax1.plot(df.index, df['Curva_Mercado'], label=f'Mercado Buy & Hold ({ticker})', color='#777777', linestyle='--', alpha=0.7)
    ax1.set_title(f'Desempenho Acumulado: {ticker}', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Evolução Patrimonial (Base 1.0)')
    ax1.legend(loc='upper left')
    ax1.grid(True, linestyle=':', alpha=0.6)

    ax2.fill_between(df.index, drawdown * 100, 0, color='#cc0000', alpha=0.3)
    ax2.plot(df.index, drawdown * 100, color='#cc0000', lw=1)
    ax2.set_title('Drawdown Subaquático (%)', fontsize=10)
    ax2.set_ylabel('Queda %')
    ax2.set_xlabel('Data')
    ax2.grid(True, linestyle=':', alpha=0.6)

    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    executar_backtest_quant()


```

## 5. Roteiro Prático de Ação para o Fim de Semana

1. **Na XP:**

   * Abra a conta e confirme a ativação do **RLP**.

   * Compre **1 ou 2 ações** no fracionário (`ITUB4F`) no modo Swing Trade / Custódia.

   * Não opere Day Trade nem mexa na boleta a cada 5 minutos; sinta a experiência de ter o ativo em carteira sem risco de zeragem de mesa.

2. **No Computador (Código):**

   * Crie uma pasta chamada `quant_lab` e configure um ambiente virtual Python (`python -m venv venv`).

   * Salve e execute o arquivo `engine_quant_xp.py`.

   * Mude o parâmetro `ticker` para testar outros ativos da B3 (ex: `PETR4.SA`, `VALE3.SA`, `WEGE3.SA`) e compare o Sharpe Ratio e o Drawdown de cada um.

3. **Próximo Nível (Automação):**

   * Cadastre-se em um ambiente de sandbox com API aberta (como Binance Testnet ou Alpaca Markets).

   * Crie um script de 50 linhas com a biblioteca `requests` ou `ccxt` que verifique seu saldo em conta e emita uma ordem limite simulada via endpoint REST.