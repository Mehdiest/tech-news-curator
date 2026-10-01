---
title: "TechTally - 2026-09-27 | Mehdi Esteghlal"
date: 2026-09-27
items: 8
sources: [Dev.to]
cover: "https://media2.dev.to/dynamic/image/width=800%2Cheight=%2Cfit=scale-down%2Cgravity=auto%2Cformat=auto/https%3A%2F%2Fdev-to-uploads.s3.us-east-2.amazonaws.com%2Fuploads%2Farticles%2Fd6uc1opq3kmertbnvha9.png"
lang: en
dir: ltr
og_locale: en_US
translations:
  - {code: fa, name: "فارسی", file: "posts/2026-09-27-tech-digest-fa.html"}
  - {code: fr, name: "Français", file: "posts/2026-09-27-tech-digest-fr.html"}
  - {code: de, name: "Deutsch", file: "posts/2026-09-27-tech-digest-de.html"}
  - {code: es, name: "Español", file: "posts/2026-09-27-tech-digest-es.html"}
  - {code: zh, name: "中文", file: "posts/2026-09-27-tech-digest-zh.html"}
  - {code: hi, name: "हिन्दी", file: "posts/2026-09-27-tech-digest-hi.html"}
  - {code: ru, name: "Русский", file: "posts/2026-09-27-tech-digest-ru.html"}
  - {code: ar, name: "العربية", file: "posts/2026-09-27-tech-digest-ar.html"}
author: "Mehdi Esteghlal"
description: "TechTally daily digest for 2026-09-27: the day's top tech stories summarized with expert commentary, curated by Mehdi Esteghlal."
generator: techtally
---

# TechTally - 2026-09-27

_8 stories from 1 source, ranked by coverage, community signal, and recency._

_Curated by [Mehdi Esteghlal](https://ir.linkedin.com/in/mehdi-esteghlal-317a67100)_

**Read this digest in:** <a class="lang-pill" href="2026-09-27-tech-digest-fa.html">فارسی</a> <a class="lang-pill" href="2026-09-27-tech-digest-fr.html">Français</a> <a class="lang-pill" href="2026-09-27-tech-digest-de.html">Deutsch</a> <a class="lang-pill" href="2026-09-27-tech-digest-es.html">Español</a> <a class="lang-pill" href="2026-09-27-tech-digest-zh.html">中文</a> <a class="lang-pill" href="2026-09-27-tech-digest-hi.html">हिन्दी</a> <a class="lang-pill" href="2026-09-27-tech-digest-ru.html">Русский</a> <a class="lang-pill" href="2026-09-27-tech-digest-ar.html">العربية</a>

## 1. [Running a serverless AI code review agent on AWS Lambda with PR-Agent and CDK](https://dev.to/naorpeled/running-a-serverless-ai-code-review-agent-on-aws-lambda-with-pr-agent-and-cdk-40gd)

![Running a serverless AI code review agent on AWS Lambda with PR-Agent and CDK](https://media2.dev.to/dynamic/image/width=800%2Cheight=%2Cfit=scale-down%2Cgravity=auto%2Cformat=auto/https%3A%2F%2Fdev-to-uploads.s3.us-east-2.amazonaws.com%2Fuploads%2Farticles%2Fd6uc1opq3kmertbnvha9.png)

**Source:** Dev.to  |  **Topic:** dev  |  **Coverage:** 1 source

**Summary**

Naor Peled published a tutorial on Dev.to demonstrating how to deploy PR-Agent, an open-source AI code review tool, as a serverless application on AWS Lambda using the AWS CDK. PR-Agent integrates with Git providers to automatically review pull requests, update descriptions, and respond to slash commands, supporting various AI model providers including local models. The guide covers the complete infrastructure-as-code setup for self-hosting the agent, offering teams an alternative to SaaS code review services.

**My Take**

> Nothing says 'we take code quality seriously' like spinning up a Lambda function to have an LLM nitpick your variable names at 2 AM. Self-hosting PR-Agent on AWS is the infrastructure equivalent of hiring a robot intern who works for pennies but occasionally hallucinates a security vulnerability in your README. The CDK abstraction makes it deceptively easy to deploy, but remember: you're now responsible for the compute bill when the agent decides your 500-file monorepo PR needs a line-by-line haiku review. The real win here isn't the AI — it's owning the prompt engineering so your team's weird conventions don't leak into someone else's training data.

---

## 2. [I Built an AI Agent That Troubleshoots Docker Containers in Plain English (Here's How)](https://dev.to/nagarjuna155/i-built-an-ai-agent-that-troubleshoots-docker-containers-in-plain-english-heres-how-1c6p)

**Source:** Dev.to  |  **Topic:** dev  |  **Coverage:** 1 source

**Summary**

Dev.to author Nagarjuna built an AI agent that automates Docker container troubleshooting by accepting plain English queries like "why did the nginx container stop?" The agent executes the typical investigation loop — listing containers, inspecting logs, checking events — that developers normally perform manually at 2 AM. The post details the architecture, implementation challenges, and bugs encountered during development.

**My Take**

> Finally, an AI that does the 2 AM ssh dance so you don't have to — because nothing says 'senior engineer' like outsourcing your `docker logs --tail 200` typos to a language model. The real innovation here isn't the LLM wrapper, it's admitting that half of DevOps is just grepping through garbage logs while questioning your career choices. Just remember: the agent only knows what the containers tell it, and containers lie like politicians on a debate stage.

---

## 3. [We Ran 100 Microservices on a 16GB Laptop. No Kubernetes.](https://dev.to/mynameis0d3c53a3/we-ran-100-microservices-on-a-16gb-laptop-no-kubernetes-590e)

![We Ran 100 Microservices on a 16GB Laptop. No Kubernetes.](https://media2.dev.to/dynamic/image/width=800%2Cheight=%2Cfit=scale-down%2Cgravity=auto%2Cformat=auto/https%3A%2F%2Fdev-to-uploads.s3.us-east-2.amazonaws.com%2Fuploads%2Farticles%2Fy0016tm6dlqjhc9a19jr.png)

**Source:** Dev.to  |  **Topic:** dev  |  **Coverage:** 1 source

**Summary**

A team built TDK (Tilt Development Kit) to test running 100 microservices locally on a 16GB laptop without Kubernetes. They used a synthetic but realistic ERP system with seven business domains where each service declares itself in a small manifest. The experiment demonstrates how far local development can scale before requiring a cluster infrastructure.

**My Take**

> The industry spent a decade convincing us you need a $50k/month Kubernetes cluster just to run "Hello World" across three services, so watching 100 services hum on a laptop that costs less than a single AWS NAT gateway is the kind of heresy that makes platform engineers reach for their stress balls. TDK essentially said "hold my beer" to the entire CNCF landscape by treating service manifests like LEGO instructions instead of YAML theology. The grounded insight: local-first tooling that respects your RAM budget beats cluster-first dogma every time — especially when onboarding a new hire shouldn't require a PhD in distributed systems troubleshooting.

---

## 4. [From Messy Rows to Management Decisions: Building a Power BI Solution for JCars Logistics](https://dev.to/brian_mugo/-from-messy-rows-to-management-decisions-building-a-power-bi-solution-for-jcars-logistics-25jk)

![From Messy Rows to Management Decisions: Building a Power BI Solution for JCars Logistics](https://media2.dev.to/dynamic/image/width=800%2Cheight=%2Cfit=scale-down%2Cgravity=auto%2Cformat=auto/https%3A%2F%2Fdev-to-uploads.s3.us-east-2.amazonaws.com%2Fuploads%2Farticles%2Ffazx9vo075kfd51j4qny.png)

**Source:** Dev.to  |  **Topic:** dev  |  **Coverage:** 1 source

**Summary**

A developer documents the end-to-end process of building a Power BI solution for JCars Logistics, a Kenyan vehicle sales and delivery company. The project started with a deliberately corrupted CSV file containing 276 rows and 32 columns, requiring a full data pipeline including auditing, cleaning, validation, modeling, calculation, and visualization to produce an executive dashboard, detailed report, and data-backed recommendations.

**My Take**

> Nothing quite says 'welcome to data engineering' like receiving a CSV that's been sabotaged on purpose — it's the digital equivalent of a trust fall where the floor is also lying to you. The 276-row 'messy rows to management decisions' journey is basically every analyst's origin story: you don't analyze data, you negotiate with it until it confesses. The real skill isn't DAX or Power Query; it's developing the patience to ask 'what does this row even mean?' thirty-two times before lunch. Grounded insight: if your data dictionary is longer than your dataset, you're not building a dashboard — you're writing a mystery novel.

---

## 5. [Jev and the Problem With AI That Always Has an Answer](https://dev.to/999thelastpage/jev-and-the-problem-with-ai-that-always-has-an-answer-1k6f)

![Jev and the Problem With AI That Always Has an Answer](https://media2.dev.to/dynamic/image/width=800%2Cheight=%2Cfit=scale-down%2Cgravity=auto%2Cformat=auto/https%3A%2F%2Fdev-to-uploads.s3.us-east-2.amazonaws.com%2Fuploads%2Farticles%2F051cs2fef1kjqgbptwo3.png)

**Source:** Dev.to  |  **Topic:** dev  |  **Coverage:** 1 source

**Summary**

The developers of Jev, an AI-powered resume review tool, discovered that the biggest challenge wasn't getting the model to generate smart-sounding feedback, but teaching it to stay silent when uncertain. Their system previously assigned arbitrary scores like 62 out of 100 with generic advice such as 'strengthen your bullet points,' which proved unhelpful. The breakthrough came not from prompt engineering but from redesigning the system to withhold judgment when confidence was low.

**My Take**

> Turns out the smartest thing an AI can say is 'I don't know' — a phrase most LLMs treat like a forbidden spell. We've built an army of overconfident interns who'd rather hallucinate a 62/100 than admit they're clueless about your React hooks. Jev's real innovation is giving the model permission to shut up, which is the grown-up version of 'move fast and break things.' The grounded lesson: accuracy isn't about better answers, it's about knowing when not to answer at all.

---

## 6. [Weekly Challenge: The palindromic length](https://dev.to/simongreennet/weekly-challenge-the-palindromic-length-299i)

**Source:** Dev.to  |  **Topic:** dev  |  **Coverage:** 1 source

**Summary**

Dev.to contributor Simon Green published his solutions for Weekly Challenge 392, a recurring coding exercise series by Mohammad S. Anwar. The first task requires writing a script to convert a given string into a palindrome by prepending characters. Green implemented his solution in Python first, then translated it to Perl, and notes that no AI tools were used in the process.

**My Take**

> Nothing says 'I enjoy programming for fun' like voluntarily doing homework on weekends and then doing it again in a second language just to prove a point. The palindrome challenge is the coding equivalent of being told to make a sentence read the same backward — so you just staple 'racecar' to the front of everything and call it a day. Green's no-AI disclaimer is the modern developer's version of 'I built this bookshelf myself, no IKEA instructions.' The real insight: constraint-based practice like this builds the pattern-recognition muscle that no Copilot suggestion can replace.

---

## 7. [Heap vs Stack Memory in C](https://dev.to/codemaster_121482/heap-vs-stack-memory-in-c-4enh)

**Source:** Dev.to  |  **Topic:** dev  |  **Coverage:** 1 source

**Summary**

A Dev.to author publishing under the handle codemaster_121482 posted a beginner-friendly explainer contrasting stack and heap memory in C. The piece targets developers moving from managed runtimes like JavaScript and Node.js to manual memory management. It outlines stack allocation as automatic, fast, and scoped to function calls, while heap allocation requires explicit malloc/free and persists until freed. The article serves as a refresher on fundamentals that underpin performance and safety in systems programming.

**My Take**

> Nothing says 'welcome to C' like realizing the runtime won't tuck your variables in at night — you have to do it yourself, or watch the heap turn into a memory-leak landfill. The stack is a tidy butler who clears the table the moment you leave the room; the heap is a storage unit you rent, forget to pay for, and eventually get sued over. JavaScript developers treat GC like a cleaning service they never tip, then act surprised when C hands them a broom and a pointer. The grounded insight: understanding ownership and lifetime isn't academic — it's the difference between a program that runs and one that segfaults in production at 3 a.m.

---

## 8. [How to Build a Personal Agent Marketplace for Claude Code](https://dev.to/teppana88/how-to-build-a-personal-agent-marketplace-for-claude-code-17fp)

**Source:** Dev.to  |  **Topic:** dev  |  **Coverage:** 1 source

**Summary**

A developer shares their approach to managing over 40 AI agents and skills for Claude Code through a personal marketplace called awave-agents. The system uses a plugin architecture with aw-review as an example, allowing reusable components like reviewers, validators, scripts, and hooks to be maintained centrally and updated across projects. The author demonstrates how to start with a single skill and scale the marketplace as workflow needs grow.

**My Take**

> Congratulations, you've reinvented npm but for prompt engineering — because nothing says 'mature engineering discipline' like 40 bespoke agents named things like 'fix-my-typescript-sins' and 'please-god-make-this-compile.' The marketplace metaphor is cute until you realize you're now maintaining your own private registry of fragile prompt chains that break every time Anthropic sneezes. Grounded insight: treat these agents like internal libraries — version them, test them, and for the love of Turing, document what they actually do before you forget why 'review-pr-angry-mode' exists.

---

*Auto-generated by [TechTally](https://github.com/Mehdiest/techtally) on 2026-10-01 10:05 UTC.*

Curated by: **Mehdi Esteghlal** | [LinkedIn](https://ir.linkedin.com/in/mehdi-esteghlal-317a67100) | [GitHub](https://github.com/Mehdiest)
