# SLO Demo — SLIs, SLOs e Error Budgets em Sistemas Distribuídos

Demonstração prática para o seminário de **Observabilidade em Sistemas Distribuídos** para a 23ª Semana Nacional de Ciência e Tecnologia (SNCT) do ano de 2026.
O objetivo dessa *demo* é mostra como uma equipe de SRE (Site Reliability Engineering ou Engenharia de Confiabilidade de Sites) para responder uma simples pergunta: *"o sistema está bom?"*, mas de uma maneira objetiva: definindo um **SLO** para medir o **consumo do error budget** via **burn rate** e, usando os dados (métricas -> traces -> logs) para **diagnosticar a causa** de uma degradação iminente, ou seja, que o serviço que está prestes a falhar, perder desempenho significativamente ou ficar indisponível.

> **Sobre a demo:** será um serviço `checkout` depende de um serviço `shipping`
> através de um proxy de caos. Em estado normal, o SLO de 99,5% de disponibilidade
> está dentro da meta. Ao injetar uma falha intermitente (30% de erro 503) no
> `shipping`, o **burn rate** dispara um alerta no Alertmanager **antes** de o
> SLO ser violado, e o diagnóstico conduzido pelos traces identifica o
> `shipping` como causa — não o `checkout`, que é o serviço medido.

## Sumário

- [Arquitetura](#arquitetura)
- [Pré-requisitos](#pré-requisitos)
- [Como rodar (comando único)](#como-rodar-comando-único)
- [Roteiro da demonstração](#roteiro-da-demonstração)
- [Onde ver cada sinal](#onde-ver-cada-sinal)
- [Como funciona por dentro](#como-funciona-por-dentro)
- [Limitações e trade-offs](#limitações-e-trade-offs)
- [Solução de problemas](#solução-de-problemas)
- [Referências](#referências)

## Arquitetura

```text
         tráfego de teste (curl loop)
                    │
                    ▼
          ┌───────────────────┐
          │   checkout :5000  │  ← serviço cujo SLI é medido
          └─────────┬─────────┘
                    │ HTTP
                    ▼
          ┌───────────────────┐
          │ chaos-proxy :8080 │  ← injeta 30% de erro 503 quando ativado
          └─────────┬─────────┘
                    │ HTTP (quando não injeta caos)
                    ▼
          ┌───────────────────┐
          │   shipping :5001  │  ← dependência instável
          └───────────────────┘

  Telemetria (OTLP gRPC :4317)
     checkout ─────┐
                   ▼
        ┌─────────────────────────┐
        │   otel-collector :8889  │─── métricas ───┐
        └────────────┬────────────┘                │
                     │                             ▼
                     │ traces              ┌──────────────────┐
                     ▼                     │ prometheus :9090 │── alertas ──┐
              ┌───────────────┐            └──────────────────┘              │
              │ jaeger :16686 │                     ▲                        ▼
              └───────────────┘                     │ regras SLO    ┌──────────────────┐
                                                    │ (geradas      │ alertmanager     │
                                                    │  pelo Sloth)  │ :9093            │
                                                    │               └──────────────────┘
                                                    │
                                              ┌──────────────┐
                                              │ grafana :3000│
                                              └──────────────┘
```

**Serviços (mínimo exigido: 2 se comunicando pela rede):**

| Serviço        | Porta  | Papel |
|----------------|--------|-------|
| `checkout`     | 5000   | Serviço medido pelo SLO; chama o `shipping` via proxy |
| `shipping`     | 5001   | Dependência do `checkout` |
| `chaos-proxy`  | 8080   | Injeção de falha controlada entre `checkout` e `shipping` |
| `otel-collector` | 4317, 8889 | Recebe OTLP e expõe métricas para o Prometheus; encaminha traces ao Jaeger |
| `prometheus`   | 9090   | Armazena métricas e avalia as regras de SLO |
| `alertmanager` | 9093   | Recebe alertas de burn rate |
| `grafana`      | 3000   | Dashboard de error budget e burn rate |
| `jaeger`       | 16686  | UI de traces distribuídos |

## Pré-requisitos

- **Docker** ≥ 20.10
- **Docker Compose** ≥ 2.0 (plugin `docker compose`, não o antigo `docker-compose`)
- **make** (opcional, mas recomendado, há também um `demo.sh` equivalente)
- ~2 GB de RAM livres
- Portas livres: `3000, 4317, 5000, 5001, 8080, 8889, 9090, 9093, 16686`

Nenhuma conta em nuvem é necessária. Tudo roda localmente.
