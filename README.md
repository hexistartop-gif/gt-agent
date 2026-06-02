# GT Agent

GT Agent is a geometry/topology research agent for proof-oriented auditing, decomposition, and grounded literature retrieval.

It supports:

- Lean-oriented proof workflows and validation
- a local Web UI for research and retrieval
- arXiv search with optional PDF grounding
- structured status reporting such as `PROVED`, `PARTIAL`, and `BLOCKED`

## Recent Tool Updates

The latest toolchain update focused on making arXiv retrieval more reliable and less abstract-only:

- `arxiv_search` now supports exact arXiv ID lookup, such as `2606.02478` or `https://arxiv.org/abs/2606.02478`
- abstract-page enrichment is used to stabilize title, author, date, and PDF metadata
- PDF download now works through `curl`, `curl.exe`, or `wget`, with `urllib` fallback
- downloaded PDFs can be previewed locally with `pypdf`, so the agent can ground summaries in the paper itself instead of only the brief abstract
- direct arXiv answers can now include the local PDF path and PDF preview text when available

Relevant environment variables:

```text
GT_ARXIV_MAX_DOWNLOADS=2
GT_ARXIV_DOWNLOAD_DIR=C:\path\to\arxiv_papers
```

Typical prompts:

```text
Download arXiv 2606.02478 PDF and summarize the full paper.
Find arXiv paper 2501.01234v2 and give me the local PDF path.
Search arXiv for recent math.AT papers and return the links.
```

## Requirements

- Python 3.10 or newer
- Windows, macOS, or Linux
- an OpenAI-compatible API for model-backed research mode

Check Python:

```powershell
python --version
```

## Installation

Install the project:

```powershell
python -m pip install -e .
```

Install test dependencies when needed:

```powershell
python -m pip install -e ".[test]"
```

Run the test suite:

```powershell
python -m pytest
```

## Modes

- `basic`: independent prover loop with Lean feedback and GTValidator checks
- `evolution`: local population database with rater and P-UCB sampling

## Input

Use a Lean proof sketch with `EVOLVE-BLOCK` / `EVOLVE-VALUE` markers, plus optional `gt_context.md`.

```lean
import Mathlib

namespace GTProblem

/-!
GT-CONTEXT:
Domain:
Objects:
Hypotheses:
Target:
Allowed references:
Forbidden assumptions:
-/

-- EVOLVE-BLOCK-START
-- Helper definitions and lemmas may be inserted here.
-- EVOLVE-BLOCK-END

theorem target_theorem : True := by
  -- EVOLVE-BLOCK-START
  sorry
  -- EVOLVE-BLOCK-END

end GTProblem
```

Natural-language `.md` inputs are accepted for audit and decomposition, but the local adapter will not mark them `PROVED`.

## CLI Usage

```powershell
python -m gt_agent.run --problem path\to\problem.lean --mode basic
python -m gt_agent.run --problem path\to\problem.lean --mode evolution
```

Outputs are written under `gt_agent_runs/<problem>_<mode>/`:

- `final.lean` or `final.md`
- `summary.md`
- `gap_ledger.md`
- `assumption_audit.md`
- `rater_report.md`
- `result.json`

## Web UI

Start the local research console:

```powershell
python -m gt_agent.web_app --host 127.0.0.1 --port 8765
```

Then open:

```text
http://127.0.0.1:8765
```

If you want other devices on the same LAN to access the UI running on this machine:

```powershell
python -m gt_agent.web_app --host 0.0.0.0 --port 8765
```

The terminal will print the reachable addresses, for example:

```text
GT Agent UI running at http://127.0.0.1:8765
GT Agent UI running at http://192.168.1.20:8765
```

The backend endpoint is:

```text
POST /api/research
```

It wraps the problem with GT Agent's research prompt, local hypothesis audit, and gap ledger before calling the configured model.

## Model Configuration

Set environment variables before starting the Web UI:

```powershell
$env:GT_MODEL_BASE_URL="https://api.openai.com/v1"
$env:GT_MODEL="gpt-4.1"
$env:GT_MODEL_API_KEY="your-api-key"
$env:GT_MODEL_TEMPERATURE="0.2"
$env:GT_MODEL_MAX_TOKENS="4096"
```

For a proxy or another OpenAI-compatible service:

```powershell
$env:GT_MODEL_BASE_URL="https://example.com/v1"
$env:GT_MODEL="your-model-name"
$env:GT_MODEL_API_KEY="your-api-key"
```

For a local model server such as LM Studio, Ollama-compatible endpoints, or vLLM:

```powershell
$env:GT_MODEL_BASE_URL="http://127.0.0.1:1234/v1"
$env:GT_MODEL="your-local-model-name"
$env:GT_MODEL_API_KEY="any-non-empty-value-required-by-the-server"
```

Note that `127.0.0.1` and `localhost` always refer to the current machine. If you move the project to another computer, that second computer's `127.0.0.1` will not point at the original machine's model server.

## Web UI Fields

The UI accepts:

- provider URL, such as `https://api.openai.com/v1` or `http://127.0.0.1:1234/v1`
- model name, such as `gpt-4.1` or a local OpenAI-compatible model name
- API key, passed only with the current request and not written to disk
- geometry/topology problem text and optional domain context
- temperature and max-token settings

## Output Status

- `PROVED`: Lean proof compiles, contains no `sorry` / `admit` / `axiom` / `unsafe`, and the theorem outside evolve markers is unchanged
- `PARTIAL`: auditable progress or decomposition with explicit gaps
- `MISFORMALIZED`: formal or informal statement appears to miss required hypotheses or mismatch the intended claim
- `COUNTEREXAMPLE`: exact counterexample identified
- `BLOCKED`: precise obstruction and next executable step are reported

## Soundness Policy

The final theorem must compile without `sorry`, `admit`, `axiom`, `unsafe`, or environment escapes. GTValidator enforces:

- theorem statement unchanged outside evolve markers
- edits only inside evolve markers
- imports unchanged unless configured
- namespace preserved
- no new axioms or unsafe declarations
- final Lean compile when accepting `PROVED`

Natural-language claims must be labeled by verification status. Named results not supplied by the user or Lean library are treated as unverified claims.

## Geometry/Topology Policy

GT Agent always audits category, hypotheses, basepoints, orientations, compactness, boundary, transversality, functoriality, and local-to-global steps. The local audit catches common risk patterns such as overbroad Poincare duality statements on non-compact manifolds.

## Implementation Boundary

Complete local implementation:

- `gt_agent/` package
- GT prover and rater prompts
- `GTValidator`
- basic mode controller
- gap ledger rendering and extraction
- attempt summary schema
- CLI
- deterministic local rater
- pytest smoke and policy tests

Adapter or stub boundary:

- LLM proof proposal is represented by `GTProverSubagent.propose_next_code`; the built-in version only performs conservative local repairs such as `True := by sorry` to `trivial`
- model research calls use `OpenAICompatibleClient`, a small `/chat/completions` adapter that supports OpenAI and compatible providers through `base_url`, `model`, and `api_key`
- Lean integration uses a thin `LeanCompiler` adapter; if `lean` is unavailable, final proofs are not accepted as `PROVED`
- evolution mode is an in-memory, single-process interface with population, rater, and P-UCB sampling; it is intentionally not a distributed search system

## Troubleshooting

### WinError 10061 / connection refused

This usually means the provider URL points to a service that is not running, is listening on a different port, or is running on a different machine than the one you think it is. It is usually not an API-key formatting issue.

Things to check:

- for cloud APIs, verify the URL really ends in something like `https://.../v1`
- for local models, start the local model server before launching GT Agent
- if the model server is on another machine, do not use `127.0.0.1`; use that machine's LAN IP instead, for example `http://192.168.1.20:1234/v1`
- make sure the serving machine allows inbound traffic on the chosen port

### Browser cannot open the Web UI

Things to check:

- for same-machine use, run `--host 127.0.0.1` and open `http://127.0.0.1:8765`
- for LAN access, run `--host 0.0.0.0` and open the printed LAN address
- if the port is occupied, switch to another one, for example `--port 8777`

### The command returns immediately to PowerShell

Under normal conditions, the Web UI command keeps running and prints `GT Agent UI running at ...`.

If it exits immediately:

- make sure you are running from the project root
- rerun `python -m pip install -e .`
- make sure the full command is `python -m gt_agent.web_app --host 127.0.0.1 --port 8765`
- do not run only the argument fragment such as `--host 127.0.0.1 --port 8765`

## Repository Note

This README now replaces the old split between `README.md` and `README_GT_AGENT.md`, so setup, runtime, troubleshooting, and tool-update notes live in one place.
