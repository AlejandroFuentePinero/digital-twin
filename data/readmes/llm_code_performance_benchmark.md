# LLM Code Performance Benchmark

**Source:** https://github.com/AlejandroFuentePinero/llm-engineering-lab/tree/main/llm_code_performance_benchmark

## What it is

A Python benchmark that compares LLMs on a practical "speedup" task: **translating a Python workload into high-performance C++** and measuring runtime improvement. Supports hosted models (OpenAI, Anthropic) and open-source models (Ollama local, OpenRouter hosted), with each model's generated C++ saved as a persistent artefact for inspection and reproducibility.

The point: when teams need to port hot Python paths to C++, LLMs can do it quickly — but performance and correctness vary by model and task. This is a **model-selection benchmark** for that workflow.

## Architecture

Per-task pipeline:

1. **Run Python baseline** — capture the computed `result` and measured `execution_time` from running the original Python.
2. **Per target LLM:**
   - Prompt the model with the Python source and a performance-first contract requesting only C++ code.
   - Save output to `{model}_main.cpp` (safe-filename-mapped) as a persistent artefact.
   - Compile the generated C++ binary.
   - Execute the binary; parse output for `Result: ...` and `Execution Time: ... seconds`.
3. **Report per-model:**
   - Status (`ok`, `llm_compile_error`, `llm_runtime_error`, `skipped_no_client`)
   - Parsed result and runtime when successful
   - **Speedup** = `python_runtime / cpp_runtime`

## Key engineering decisions

- **Failure modes are first-class outputs.** A "fast" model that fails often is not a good production choice. The benchmark distinguishes:
  - **`llm_compile_error`** — model produced invalid / non-compilable C++
  - **`llm_runtime_error`** — binary compiled but crashed or exited non-zero
  - These are separated from system errors (missing client, missing compiler). Failure attribution is part of the comparison.
- **Python is the reference for correctness.** Baseline behaviour defines what "correct" means; C++ outputs are validated against the Python result, not just timed.
- **Prompt-as-contract.** Models must return only C++ code, optimised for speed — no commentary, no Markdown wrapping, nothing that breaks the compile step downstream.
- **Artefact persistence.** Every model's C++ is saved so you can diff, audit, and reuse. Without persistence, the benchmark produces numbers; with persistence, it produces a portfolio of model behaviours you can study.
- **Per-task selection rather than a generic leaderboard.** Different optimisation tasks favour different models — the benchmark is meant to be re-run per workload type. The output is "for this task, this model wins"; not "this model wins everywhere."
- **Open-source models compared on equal footing.** Ollama (local) and OpenRouter (hosted-open) use OpenAI-compatible clients, so the same benchmarking code runs paid frontier models, open-source frontier models, and local open-source models on identical workloads. Useful for "paid vs local vs open" cost-vs-quality comparisons.

## Interface

`python_to_cpp_performance(models=[...], python="...", ui_launch=False) -> dict`

Returns:
- Python baseline result and runtime
- Per-model: status, parsed result/runtime when successful, speedup factor vs Python

## Demo

Gradio UI for interactive use: paste Python, select a model, generate the C++ port. Single-model conversion mode rather than the full benchmark loop.

- Entry point: `python_to_cpp_performance(ui_launch=True)`
- Run: from inside a `uv run python` session, requires `OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY`, plus optional `OPENROUTER_API_KEY`.

## Stack

Python · C++ (g++ or compatible) · OpenAI · Anthropic · Ollama · OpenRouter · Gradio
