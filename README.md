# Agentic SDLC Runtime

Runtime compartilhado e funcional para os agentes da [Agentic SDLC Reference Architecture](https://github.com/leandrosflora/agentic-sdlc-reference-architecture).

Os papéis Product, Architecture, Developer, Test, Security, Reviewer, Release e Incident são definições declarativas executadas por este runtime. Eles não precisam operar como oito serviços persistentes.

## Capacidades implementadas

- registry de definições declarativas JSON;
- Context Builder com classificação, proveniência, redaction por escopo, limites e hashes;
- Fake Model Gateway determinístico;
- gateway HTTP real compatível com OpenAI, proxies corporativos e vLLM;
- MCP fake com grants por agente;
- runtime com tool loop limitado;
- eventos compatíveis com agent-event.schema.json;
- evidence bundles persistidos com SHA-256;
- checkpoints atômicos;
- retomada sem repetir chamada ao modelo;
- CLI e golden path;
- testes em Python 3.11 e 3.12.

## Arquitetura

~~~mermaid
flowchart LR
  D["Agent Definition"] --> R["Shared Runtime"]
  C["Context Builder"] --> R
  R --> M["Model Gateway"]
  R --> T["MCP Gateway"]
  R --> E["Events e Evidence"]
  R --> P["Checkpoint"]
  P -->|resume| R
~~~

## Instalação e demo

~~~bash
pip install -e ".[dev]"
pytest
python examples/run_demo.py
~~~

Ou use a CLI:

~~~bash
agentic-sdlc \
  --agent product \
  --project payments \
  --change CHG-1001 \
  --objective "Refine payment API requirement"
~~~

Por padrão a CLI usa o modelo fake. Para um endpoint OpenAI-compatible:

~~~bash
export MODEL_BASE_URL="https://api.openai.com/v1"
export MODEL_API_KEY="..."
export MODEL_NAME="..."
agentic-sdlc --real-model --agent product --project payments \
  --change CHG-1001 --objective "Refine requirement"
~~~

Credenciais são lidas do ambiente e nunca entram no contexto ou nas evidências.

## Definição de agente

~~~json
{
  "role": "product",
  "version": "1.0.0",
  "system_prompt": "Return a governed JSON response.",
  "allowed_tools": ["project.read", "requirements.write"],
  "limits": {
    "max_steps": 8,
    "max_input_chars": 32000,
    "max_output_chars": 8000
  }
}
~~~

## Estado durável

Cada execução persiste:

~~~text
.runtime/
├── checkpoints/<change_id>/<role>.json
├── evidence/<change_id>/<run_id>/*.json
└── events/<change_id>/*.json
~~~

Uma falha após a resposta do modelo preserva o checkpoint. A execução com --resume reutiliza a resposta persistida e continua no tool call, evitando custo e efeito duplicados.

## Workflow ponta a ponta

O runtime implementa uma jornada durável completa:

~~~text
Product → Architecture → Developer → Test → Security → Reviewer
→ awaiting_human_approval
→ Release → demo deployment → observation
→ completed ou rolled_back
~~~

A aprovação humana é obrigatória, independente do autor e vinculada ao digest exato. O ambiente demo mantém digest atual, anterior e histórico de deploy, observação e rollback.

~~~bash
python examples/end_to_end_demo.py
python examples/end_to_end_demo.py --unhealthy
~~~

O primeiro comando termina em completed. O segundo viola o guardrail de observação e restaura o digest estável anterior.


## P6 — integração real controlada

O P6 conecta uma Issue real ao workflow e mantém os adapters fake para testes:

~~~text
Issue → agentes → pytest + secret scan → Check + comentário
→ dispatch humano protegido pelo Environment demo
→ deploy do digest aprovado → health check HTTP
→ completed ou rollback → Check + comentário + evidências
~~~

### Configuração do repositório

1. Crie o Environment `demo` e habilite **Required reviewers**. O autor da Issue não pode ser o aprovador.
2. Configure as variables:
   - `MODEL_BASE_URL` e `MODEL_NAME` para o Model Gateway real;
   - `P6_DEPLOY_COMMAND`: array JSON, por exemplo `["python","ops/deploy.py"]`;
   - `P6_ROLLBACK_COMMAND`: array JSON, por exemplo `["python","ops/rollback.py"]`;
   - `P6_HEALTH_URL`: endpoint HTTP/HTTPS do ambiente demo.
3. Configure o secret `MODEL_API_KEY`. Sem ele, a preparação usa o modelo fake determinístico.
4. Abra uma Issue ou aplique o label `agentic-sdlc`. O workflow **P6 prepare** publica o digest e preserva o checkpoint como artifact.
5. Execute manualmente **P6 release demo** informando Issue, run ID da preparação e o digest exato. O Environment pausa o job para aprovação.

Os comandos são arrays JSON, nunca strings de shell. Somente executáveis permitidos são aceitos e credenciais não são copiadas para contexto, logs ou evidence bundles.

A implementação usa:

- `GitHubClient` para Issues, comentários e Checks;
- `GovernedCommandRunner` para gates e operações;
- `ExternalDemoEnvironment` para deploy e rollback;
- `HttpHealthObserver` para a decisão pós-release;
- `P6Integration` para correlação, digest e feedback.


## Developer Agent conectado ao GitHub

O `DeveloperAgentService` transforma uma Issue em um draft PR no repositório alvo:

1. solicita ao Model Gateway uma alteração JSON estruturada;
2. restringe arquivos a `src/`, `tests/` e `docs/`;
3. bloqueia traversal, workflows, policy e arquivos sensíveis;
4. cria `agent/issue-<número>-<resumo>`;
5. grava arquivos pela API do GitHub;
6. abre draft PR e comenta na Issue;
7. nunca faz merge.

~~~bash
python scripts/developer_action.py \
  --repository leandrosflora/agentic-sdlc-demo-app \
  --issue 2
~~~

## P7 — produção e governança

O runtime inclui adapters testáveis e substituíveis para:

| Capacidade | Implementação |
|---|---|
| OPA/PDP | `OPAPolicyDecisionPoint`, HTTP e fail-closed |
| Workload identity | `GitHubOIDCIdentityProvider`, token OIDC de curta duração |
| Evidência durável | `S3EvidenceStore`, conteúdo endereçado por SHA-256 |
| Assinatura/SBOM | `SupplyChainAttestor`, Syft + Cosign |
| OpenTelemetry | `OTLPHTTPExporter` |
| Budgets | `BudgetLedger`, bloqueio antes do excesso |
| Filas/workers | fila SQLite local e adapter SQS |
| Sandbox | Docker sem rede, read-only, cap-drop e limites |
| Change Set | ordenação topológica multi-repositório |
| SLO/recuperação | decisão objetiva de continuar ou rollback |

O manifesto Kubernetes em `deploy/kubernetes/worker.yaml` demonstra workers replicáveis, ServiceAccount para workload identity, filesystem read-only, non-root, seccomp e NetworkPolicy deny-by-default.

Dependências de providers são opcionais:

~~~bash
pip install -e ".[production]"
~~~

Antes de produção, configure Object Lock/versionamento no bucket de evidências, KMS/keyless signing, allowlist de egress, backend remoto de budget e DLQ da fila.

## Limites desta versão

- o gateway MCP incluído é fake e voltado a testes; integrações GitHub, comandos e health check já possuem adapters reais;
- o gateway real de modelo usa o contrato chat completions OpenAI-compatible;
- persistência local demonstra os contratos; produção deve usar storage durável/WORM;
- policy OPA permanece no repositório de referência e será integrada como PDP remoto ou sidecar.
