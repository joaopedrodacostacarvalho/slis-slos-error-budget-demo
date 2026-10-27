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
