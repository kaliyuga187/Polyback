# Monetization Strategy: Polyback

> **Tier:** 2 (High-potential, portfolio-grade project)
> **Last updated:** 2026-04-16

---

## Product Overview

Polyback enables users to run Claude Code locally using Qwen2.5-Coder via Ollama and LiteLLM. It provides a single deployment script (`openclaw.sh` / `server.sh`) that sets up the entire local AI coding assistant stack, eliminating the need for paid API keys. The project includes multiple bot versions (v6 through v13) exploring different strategies including Polymarket arbitrage. It is an early-stage project focused on making AI coding assistants accessible without ongoing API costs.

## Target Market

| Segment | Description |
|---------|-------------|
| **Cost-conscious developers** | Developers who want AI coding assistance without paying for API subscriptions |
| **Privacy-focused teams** | Organisations that need AI coding tools but cannot send code to external APIs |
| **Enterprise IT departments** | Teams evaluating local AI deployment for developer productivity |
| **AI enthusiasts / tinkerers** | Hobbyists who want to run and experiment with local LLMs |

## Revenue Streams

| Stream | Model | Price Point | Est. Monthly Revenue (Yr 1) | Priority |
|--------|-------|-------------|----------------------------|----------|
| Managed Hosting Service | Monthly subscription | A$29 - A$99/mo | A$2,000 - A$8,000 | HIGH |
| Enterprise Deployment Packages | One-time setup + support | A$2,000 - A$5,000 | A$4,000 - A$10,000 | HIGH |
| Course: "Run AI Coding Assistants Locally for Free" | One-time purchase | US$49 | A$500 - A$2,000 | MEDIUM |
| Template/Script Bundle | One-time purchase on Gumroad | US$19 | A$300 - A$1,000 | LOW |

## Go-Live Checklist

- [ ] **Managed Hosting Service (A$29-99/mo)**
  - [ ] Build cloud-hosted Ollama + LiteLLM instances provisioned per subscriber
  - [ ] Create tiered plans:
    - **Starter (A$29/mo):** Single model, 1 concurrent session
    - **Pro (A$59/mo):** Multiple models, 3 concurrent sessions, priority queue
    - **Team (A$99/mo):** Shared workspace, 10 sessions, admin dashboard
  - [ ] Implement user authentication and session management
  - [ ] Build usage metering and billing (Stripe integration)
  - [ ] Deploy on GPU-enabled cloud infrastructure (RunPod, Lambda, or similar)
  - [ ] Monitor and manage Ollama model caching for performance

- [ ] **Enterprise Deployment Packages (A$2,000-5,000)**
  - [ ] Create standardised deployment playbooks for:
    - On-premises Linux servers
    - AWS / GCP / Azure VMs with GPU
    - Air-gapped / restricted network environments
  - [ ] Build automated health-check and monitoring scripts
  - [ ] Include 30-day post-deployment support window
  - [ ] Draft service agreement and statement of work template
  - [ ] Create security hardening guide for enterprise environments

- [ ] **Course: "Run AI Coding Assistants Locally for Free" (US$49)**
  - [ ] Outline 6-10 module curriculum:
    - Module 1: Why local AI (cost, privacy, control)
    - Module 2: Ollama setup and model management
    - Module 3: LiteLLM as an API proxy
    - Module 4: Connecting Claude Code to local models
    - Module 5: Performance tuning and hardware optimisation
    - Module 6: Advanced configurations and multi-model setups
  - [ ] Record screencasts for each module
  - [ ] Host on Teachable or Gumroad (US$49)
  - [ ] Create companion GitHub repo with exercise files

- [ ] **Template/Script Bundle (US$19)**
  - [ ] Package deployment scripts (`openclaw.sh`, `server.sh`) with documentation
  - [ ] Add configuration templates for common setups (Mac, Linux, WSL)
  - [ ] Include model comparison guide (Qwen2.5 variants, CodeLlama, etc.)
  - [ ] List on Gumroad with clear feature description
  - [ ] Include support channel access (Discord or GitHub Discussions)

## Key Implementation Files

| File / Directory | Relevance |
|-----------------|-----------|
| `openclaw.sh` | Main deployment script for Ollama + LiteLLM setup |
| `server.sh` | Server startup and configuration script |
| `bot_v13_arb.py` | Latest bot version (Polymarket arbitrage) |
| `bot_v12.py` | Bot version 12 |
| `bot_v11.py` | Bot version 11 |
| `bot_v10.py` | Bot version 10 |
| `bot_v9.py` | Bot version 9 |
| `bot_v8.py` | Bot version 8 |
| `bot_v7.py` | Bot version 7 |
| `bot_v6.py` | Bot version 6 |
| `CLAUDE.md` | Project documentation and AI assistant guide |
| `README.md` | Project overview and setup instructions |

## Risk Notes

- **Hardware requirements:** Local LLM inference requires significant GPU resources. Managed hosting margins depend heavily on GPU compute costs. Monitor and optimise model quantisation (Q4, Q5, Q8) to balance quality vs. cost.
- **Model quality gap:** Qwen2.5-Coder, while capable, does not match Claude or GPT-4 in all coding tasks. Set clear expectations about model capabilities and position the product as a cost-effective alternative, not a full replacement.
- **Ollama / LiteLLM dependency:** Both are open-source projects that could change their APIs or licensing. Pin versions and maintain compatibility across releases.
- **Polymarket bot versions:** The arbitrage bots (v13) represent interesting IP but operate in a regulatory grey area. Keep Polymarket-specific functionality separate from the core local-AI product to avoid regulatory entanglement.
