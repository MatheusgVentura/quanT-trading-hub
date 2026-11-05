# Especificação Técnica 01: Módulo de Ingestão e Padronização de Dados (`src/data/`)

**Status:** 🟡 Proposta / Aguardando Alinhamento do Usuário  
**Data:** 05/11/2026  
**Autor:** Antigravity & Matheus Ventura  
**Fase:** 1  

---

## 1. Visão Geral e Motivação

O sucesso e a confiabilidade de qualquer motor de trading quantitativo dependem diretamente da qualidade dos dados brutos. Se os dados possuírem falhas (ex.: *MultiIndex* corrompido, valores nulos, preços negativos ou ausência de tratamento de fuso horário), as estratégias e o motor de backtest gerarão cálculos errôneos (*Garbage in, Garbage out*).

O objetivo da Fase 1 é construir a fundação de dados do **quanT-trading-hub**, garantindo que qualquer estratégia consuma dados de preços e volumes padronizados, com tipagem estrita, livres de inconsistências e com suporte a cache local para alta performance em testes repetitivos.

---

## 2. Requisitos Funcionais (RF)

* **RF01 - Download de Dados Históricos:** Capacidade de buscar dados OHLCV (Open, High, Low, Close, Volume) para ações e índices (com suporte nativo a tickers da B3, ex.: `ITUB4.SA`, `PETR4.SA`, `^BVSP`).
* **RF02 - Sanitização e Achatamento de Estrutura:** Tratar automaticamente a estrutura de retorno do `yfinance` (remover MultiIndex quando múltiplos níveis forem retornados, garantir índices ordenados cronologicamente).
* **RF03 - Validação de Consistência (Data Quality Gate):**
  * Verificar se todas as colunas obrigatórias existem (`Open`, `High`, `Low`, `Close`, `Volume`).
  * Validar consistência de preços: $High \ge Low$, $High \ge Open$, $High \ge Close$, $Low \le Open$, $Low \le Close$, $Close > 0$.
  * Validar consistência de volume: $Volume \ge 0$.
  * Tratar valores ausentes (NaNs) de forma determinística e explícita.
* **RF04 - Cache Local (Otimização):** Opção de salvar os dados localmente em formato colunar eficiente (`Parquet` ou `CSV`) para evitar requisições redundantes à rede durante sessões de backtest e desenvolvimento.
* **RF05 - Desacoplamento via Interface (Protocol / ABC):** A camada de estratégias e backtest não deve depender diretamente do `yfinance`. Uma interface abstrata permitirá trocar a fonte de dados (ex.: MetaTrader 5, AlphaVantage, CCXT) no futuro sem alterar o restante do sistema.

---

## 3. Requisitos Não Funcionais (RNF)

* **RNF01 - Tipagem Estrita:** 100% das funções e classes anotadas com `typing` e aprovadas no `mypy`.
* **RNF02 - Testabilidade:** Cobertura de testes unitários mínima de 85% com `pytest`, utilizando *mocks* para chamadas externas à internet.
* **RNF03 - Desempenho:** Ingestão de 3 anos de dados diários e conversão para DataFrame validado em menos de 100ms após o recebimento dos dados brutos.
* **RNF04 - Tratamento de Erros Resiliente:** Exceções customizadas com mensagens claras em português quando um ticker for inválido ou não houver dados.

---

## 4. Arquitetura e Contratos de Interface

### 4.1 Estrutura de Pastas Proposta

```text
src/
├── data/
│   ├── __init__.py
│   ├── exceptions.py          # Exceções customizadas (DataDownloadError, DataValidationError)
│   ├── interfaces.py          # Protocolo/ABC da fonte de dados
│   ├── yfinance_provider.py   # Implementação concreta usando yfinance
│   ├── validator.py           # Validação e sanitização das séries OHLCV
│   └── cache.py               # Gerenciador de cache local (arquivos em .cache/)
```

### 4.2 Definição de Interfaces e Classes Principais

#### `src/data/exceptions.py`
```python
class DataError(Exception):
    """Exceção base para o módulo de dados."""
    pass

class DataDownloadError(DataError):
    """Falha ao baixar dados da fonte externa."""
    pass

class DataValidationError(DataError):
    """Falha nos testes de integridade dos dados (preços negativos, high < low, etc.)."""
    pass

class TickerNotFoundError(DataError):
    """Ticker informado não possui dados ou não foi localizado."""
    pass
```

#### `src/data/interfaces.py`
```python
from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd

class IDataProvider(ABC):
    """Interface abstrata para provedores de dados de mercado."""

    @abstractmethod
    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: Optional[str] = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Recupera série temporal OHLCV padronizada e validada.
        
        Retorno esperado:
            pd.DataFrame com índice DatetimeIndex ordenado e colunas:
            ['Open', 'High', 'Low', 'Close', 'Volume']
        """
        pass
```

#### `src/data/validator.py`
```python
class OHLCVValidator:
    """Validador e sanitizador de DataFrames OHLCV."""

    REQUIRED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

    @classmethod
    def validate_and_clean(cls, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        # 1. Verifica presença das colunas obrigatórias
        # 2. Converte tipos para float64 (preços) e int64/float64 (volume)
        # 3. Valida High >= Low e preços > 0
        # 4. Remove ou interpola NaNs residuais
        # 5. Garante ordenação cronológica estrita
        pass
```

#### `src/data/yfinance_provider.py`
```python
class YFinanceDataProvider(IDataProvider):
    """Implementação concreta de IDataProvider utilizando yfinance."""

    def __init__(self, cache_manager: Optional[DataCacheManager] = None):
        self.cache = cache_manager

    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: Optional[str] = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        # 1. Checa cache local se configurado
        # 2. Chama yf.download() com tratamento de timeout/erro
        # 3. Descompacta MultiIndex se houver
        # 4. Aciona OHLCVValidator.validate_and_clean()
        # 5. Salva no cache e retorna
        pass
```

---

## 5. Plano de Testes (TDD / Unit Tests)

Os testes ficarão em `tests/unit/test_data/` e cobrirão:

1. **`test_download_success`:** Simular retorno válido do yfinance (mock) e validar se o DataFrame final tem colunas e tipos corretos.
2. **`test_multiindex_flattening`:** Simular o comportamento do yfinance que retorna colunas MultiIndex e garantir que o provedor achate corretamente para índice simples.
3. **`test_empty_data_raises_error`:** Simular ticker inexistente (retorno vazio) e garantir que `TickerNotFoundError` é disparada.
4. **`test_invalid_prices_detected`:** Injetar dados corrompidos (ex.: `High < Low` ou `Close < 0`) e garantir que `DataValidationError` é disparada.
5. **`test_cache_hit_and_miss`:** Validar que uma segunda chamada com os mesmos parâmetros consome do cache em disco sem bater na API externa.

---

## 6. Setup do Ambiente Inicial (Entregável da Fase 1)

* Criação do `requirements.txt` inicial:
  * `pandas>=2.0.0`
  * `numpy>=1.24.0`
  * `yfinance>=0.2.35`
  * `pyarrow>=14.0.0` (para persistência rápida de cache parquet)
  * `pytest>=8.0.0`
  * `pytest-cov>=4.1.0`
  * `mypy>=1.8.0`
* Criação do ambiente virtual com Python 3.10.

---

## 7. Critérios de Aceite para Aprovação

- [ ] Todas as interfaces e classes estão claras e atendem à necessidade do hub?
- [ ] O tratamento de dados OHLCV e cache faz sentido para você?
- [ ] O modelo de testes unitários com mocks atende à governança?

*Aguardando alinhamento do usuário antes de iniciar qualquer código de implementação.*

