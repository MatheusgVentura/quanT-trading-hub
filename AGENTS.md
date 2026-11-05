# AGENTS.md - Repository Standards, Rules, and Conventions

Documento de referência permanente contendo regras estáveis, convenções de arquitetura, padrões de engenharia e comandos úteis para o repositório **quanT-trading-hub**.

---

## 1. Fluxo de Desenvolvimento de Funcionalidades (Spec-Driven Development)

1. **Spec Obrigatória:** Toda funcionalidade inicia em `specs/<NNN-nome>/spec.md` contendo:
   * Objetivo (*Objective*)
   * Fora de escopo (*Out of Scope*)
   * Critérios de aceite numerados e verificáveis (*Acceptance Criteria*)
   * Casos de borda (*Edge Cases*)
   * Contratos e modelos de dados (*Contracts / Data Models*)
   * Riscos de abuso e segurança (*Abuse & Security Risks*)
   * Perguntas em aberto (*Open Questions*)
   * Suposições assumidas (*Assumptions Made*)
2. **Plano e Decomposição:**
   * `specs/<NNN-nome>/plan.md`: Decisões técnicas e alternativas descartadas.
   * `specs/<NNN-nome>/tasks.md`: Lista ordenada de tarefas pequenas, cada uma vinculada a um ou mais critérios de aceite.
3. **Aprovação Explícita:** Apresentar suposições e dúvidas e **PARAR**. O desenvolvimento só inicia quando o usuário responder estritamente `"aprovado"`.
4. **Implementação Guiada por Testes:** Executar uma tarefa por vez do `tasks.md`, derivando os testes diretamente dos critérios de aceite.
5. **Fechamento Atômico:** Uma entrega = uma tarefa do `tasks.md` concluída. Atualizar `tasks.md` e `PROGRESS.md` editando apenas o necessário.

---

## 2. Regras de Conduta e Governança

* **Ajuste de Spec em Voo:** Se a spec estiver errada ou incompleta durante a implementação, **PARE**, descreva a divergência, proponha o ajuste e aguarde aprovação. Nunca contorne limitações da spec silenciosamente no código.
* **Isolamento de Escopo:** Não altere arquivos ou comportamentos fora do escopo estrito da tarefa atual. Apontamentos adicionais devem ser registrados no `PROGRESS.md`.
* **Ambiguidade:** Pergunte explicitamente antes de assumir premissas não documentadas.
* **Ajuste Trivial:** Alterações mínimas (correção de typo, ajuste de 1 linha de config) devem ser descritas em 2-3 linhas e executadas diretamente.

---

## 3. Padrões de Qualidade e Stack Tecnológica

### 3.1 Stack
* **Python:** 3.10+
* **Core Científico:** `pandas`, `numpy`, `yfinance`, `pyarrow`
* **Qualidade e Testes:** `pytest`, `pytest-cov`, `mypy`, `ruff`

### 3.2 Critérios de Conclusão de Tarefa
Uma tarefa só é considerada concluída após rodar e exibir a saída de:
1. Formatação e Linting: `ruff check .` e `ruff format --check .`
2. Tipagem Estática Estrita: `mypy --strict src tests`
3. Testes Unitários: `pytest --cov=src -v`
* **Vínculo Teste-Critério:** Cada critério de aceite deve ter pelo menos um teste unitário correspondente, referenciando o número do critério no nome ou docstring (ex: `test_ac01_...`).

---

## 4. Segurança e Variáveis de Ambiente

* **Zero Segredos:** Nenhuma chave, credencial ou segredo pode ser versionado no código ou em mensagens de commit.
* **Gestão de Ambiente:** Variáveis de ambiente sensíveis residem em `.env` (ignorado no `.gitignore`). Usar `.env.example` como gabarito público.
* **Sanitização de Dados:** Toda entrada externa (APIs, feeds de rede, arquivos em disco) deve passar por validação de formato e limites antes de entrar na camada de domínio.

---

## 5. Convenções de Idioma e Git

* **Comunicação:** Conversas e alinhamentos em **Português (BR)**.
* **Artefatos Técnicos:** Código-fonte, docstrings, nomes de testes, commits e arquivos dentro de `specs/` estritamente em **Inglês**.
* **Padrão de Commits (Conventional Commits):**
  * `feat(scope): ...`
  * `test(scope): ...`
  * `chore(scope): ...`
  * `docs(scope): ...`
  * `fix(scope): ...`

---

## 6. Comandos Úteis (PowerShell / Windows)

```powershell
# Ativação do ambiente virtual
.\venv\Scripts\Activate.ps1

# Formatação e Linting
.\venv\Scripts\ruff check .
.\venv\Scripts\ruff format .

# Verificação de Tipagem Estrita
.\venv\Scripts\mypy --strict src tests

# Suíte de Testes com Cobertura
.\venv\Scripts\pytest --cov=src -v
```
