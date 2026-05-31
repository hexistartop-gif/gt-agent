# GT Agent

GT Agent is a geometry/topology research agent inspired by AlphaProof Nexus-style formal proof search.

## Modes

- `basic`: independent prover loop with Lean feedback and GTValidator checks.
- `evolution`: local population database + rater + P-UCB sampling interface.

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

## Run

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

The UI accepts:

- OpenAI-compatible provider URL, such as `https://api.openai.com/v1`;
- model name, such as `gpt-4.1`, a proxy model, or a local OpenAI-compatible model;
- API key, passed only with the current request and not written to disk;
- geometry/topology problem text and optional domain context.

The backend endpoint is:

```text
POST /api/research
```

It wraps the problem with GT Agent's research prompt, local hypothesis audit, and gap ledger before calling the configured model.

## Output Status

- `PROVED`: Lean proof compiles, contains no `sorry` / `admit` / `axiom` / `unsafe`, and the theorem outside evolve markers is unchanged.
- `PARTIAL`: auditable progress or decomposition with explicit gaps.
- `MISFORMALIZED`: formal or informal statement appears to miss required hypotheses or mismatch the intended claim.
- `COUNTEREXAMPLE`: exact counterexample identified.
- `BLOCKED`: precise obstruction and next executable step are reported.

## Soundness Policy

The final theorem must compile without `sorry`, `admit`, `axiom`, `unsafe`, or environment escapes. GTValidator enforces:

- theorem statement unchanged outside evolve markers;
- edits only inside evolve markers;
- imports unchanged unless configured;
- namespace preserved;
- no new axioms or unsafe declarations;
- final Lean compile when accepting `PROVED`.

Natural-language claims must be labeled by verification status. Named results not supplied by the user or Lean library are treated as unverified claims.

## Geometry/Topology Policy

GT Agent always audits category, hypotheses, basepoints, orientations, compactness, boundary, transversality, functoriality, and local-to-global steps. The local audit catches common risk patterns such as overbroad Poincare duality statements on non-compact manifolds.

## Implementation Boundary

Complete local implementation:

- `gt_agent/` package;
- GT prover and rater prompts;
- `GTValidator`;
- basic mode controller;
- gap ledger rendering and extraction;
- attempt summary schema;
- CLI;
- deterministic local rater;
- pytest smoke and policy tests.

Adapter/stub boundary:

- LLM proof proposal is represented by `GTProverSubagent.propose_next_code`; the built-in version only performs conservative local repairs such as `True := by sorry` to `trivial`.
- Model research calls use `OpenAICompatibleClient`, a small `/chat/completions` adapter that supports OpenAI and compatible providers through `base_url`, `model`, and `api_key`.
- Lean integration uses a thin `LeanCompiler` adapter. If `lean` is unavailable, final proofs are not accepted as `PROVED`.
- Evolution mode is an in-memory, single-process interface with population, rater, and P-UCB sampling. It is intentionally not a distributed search system.

## Test

```powershell
pytest
```
