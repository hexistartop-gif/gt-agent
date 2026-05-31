# Codex 操作手册：实现 GT agent

> 本文档基于 DeepMind AlphaProof Nexus 风格的 formal proof search 框架，将其 prompt、agent loop、validator、rater、population search 等机制改写为面向几何与拓扑研究的研究级 agent，命名为 **GT agent**。

---

## 0. 任务目标

在当前数学 agent 项目中新增一个研究级几何与拓扑 agent，命名为 `GT agent` 或 `GTAgent`。它不是普通解题助手，而是面向几何与拓扑研究任务的 proof-search / proof-planning / formalization assistant。

目标能力：

1. 支持几何拓扑研究问题的严格重述、假设审计、证明分解、反例搜索、形式化尝试。
2. 优先使用 Lean 编译反馈来约束证明；Lean 不足时输出可审查的自然语言 proof sketch 与 gap ledger。
3. 严格区分：
   - proved result；
   - conjectural step；
   - heuristic；
   - formalized Lean lemma；
   - unverified literature claim；
   - blocked gap。
4. 不得编造定理、论文、引用或“显然成立”的核心 lemma。
5. 对困难问题不得直接放弃；必须给出部分结论、障碍、替代路线和下一步可执行方案。

---

## 1. 架构要求

实现两种模式。

### 1.1 Basic mode

对应 AlphaProof Nexus 的 basic agent / Ralph loop：多个 prover subagent 独立运行，每个 subagent 反复读取当前 proof sketch，用小步 `search_replace` 修改，然后调用 Lean 编译器获得反馈。若未完成证明，则把本轮学习结果写入 sketch 注释并进入下一轮。

实现模块：

```text
gt_agent/
  controller.py
  prover_subagent.py
  validator.py
  prompts/
    gt_prover_system.md
    gt_rater_system.md
    gt_reflector.md
  schemas/
    gt_problem_schema.py
    gt_attempt_schema.py
  knowledge/
    gt_domain_checklist.md
```

Basic loop：

```python
initial_sketch = lean_compiler.check(initial_file)

for subagent in parallel(N):
    sketch = initial_sketch
    while within_budget() and sketch.contains_sorry():
        prompt = build_gt_prover_prompt(sketch, prior_attempts=None)
        patch = llm.generate_tool_call(prompt)
        sketch, feedback = search_replace_then_compile(sketch, patch)

        if validator.integrity_failed(sketch):
            revert_to_previous_sketch()

        if sketch.compiles and sketch.sorry_free:
            return PROVED(sketch)

        if episode_finished:
            sketch = append_attempt_summary(sketch, feedback)
```

Default parameters:

```yaml
num_provers: 8
max_episodes_per_problem: 200
max_search_replace_per_episode: 60
compile_after_each_edit: true
allow_sorry_in_intermediate_sketch: true
allow_sorry_in_final_output: false
```

### 1.2 Evolution mode

对应 full-featured agent：prover subagents 从 population database 取 parent sketch，rater subagents 对 sketch 进行相对排序，Elo/P-UCB 用于采样。

实现模块：

```text
gt_agent/
  population_db.py
  rater_subagent.py
  p_ucb_sampler.py
  goal_cache.py
```

Evolution loop：

```python
population.initialize(initial_sketch)

launch prover_subagents(N, population)
launch rater_subagents(M, population)

while within_budget():
    parent = population.sample(strategy="p_ucb")
    candidate = prover_subagent.mutate(parent)

    if validator.compiles(candidate) and validator.theorem_integrity_ok(candidate):
        population.add(candidate)

    if candidate.sorry_free:
        return PROVED(candidate)
```

Default parameters：

```yaml
num_provers: 10
num_raters: 3
rater_match_size: 7
elite_pool_size: 64
p_ucb_exploration_c: 0.2
goal_cache: true
```

---

## 2. 输入协议

GT agent 接收两类输入。

### 2.1 Lean proof sketch

文件必须使用可编辑标记。Codex 需要保证 agent 只能修改标记内部内容。

```lean
import Mathlib

namespace GTProblem

/-!
GT-CONTEXT:
Domain: differential topology / algebraic topology / low-dimensional topology / ...
Objects:
Hypotheses:
Target:
Allowed references:
Forbidden assumptions:
-/

-- EVOLVE-BLOCK-START
-- Helper definitions and lemmas may be inserted here.
-- EVOLVE-BLOCK-END

theorem target_theorem :
    -- formal theorem statement
    True := by
  -- EVOLVE-BLOCK-START
  sorry
  -- EVOLVE-BLOCK-END

end GTProblem
```

### 2.2 Natural-language GT context

允许额外提供 `gt_context.md`：

```markdown
# GT Context

## Domain
e.g. smooth manifolds, characteristic classes, spectral sequences, 3-manifolds, homotopy theory.

## Objects and category
Specify category, morphisms, equivalence relation, basepoints, orientations, compactness assumptions.

## Definitions
List exact definitions used in this problem.

## Known results allowed
Only include results explicitly supplied by the user or present in the formal library.

## Target
State exactly what should be proved, disproved, formalized, or decomposed.

## Risk points
Orientation/signs, transversality, compactness, basepoint dependence, functoriality, naturality, boundary terms.
```

---

## 3. GT prover prompt

创建 `prompts/gt_prover_system.md`，内容如下。

```markdown
# Role and Goal

You are GT agent, a research-grade geometry and topology assistant and Lean 4 proof engineer.

Your goal is to solve, formalize, or rigorously decompose geometry/topology research problems. You must behave like a careful research mathematician, not like a contest-solution generator.

You must explicitly track:
1. category and objects;
2. hypotheses and where they are used;
3. definitions and equivalence relations;
4. invariants and functoriality;
5. basepoints, orientations, compactness, transversality, boundary terms, signs;
6. local-to-global passages;
7. exact sequences, spectral sequences, obstruction classes, characteristic classes, or moduli-space data when relevant.

# Task

You are given a Lean file or a natural-language proof sketch.

If Lean code is provided:
- edit only inside EVOLVE-BLOCK and EVOLVE-VALUE markers;
- use search_replace patches, not full-file rewrites;
- compile after every small edit;
- never change the target theorem outside allowed markers;
- final output must compile and contain no sorry/admit/axiom/unsafe escape.

If the theorem is not currently formalizable:
- produce a structured proof plan;
- isolate formalizable lemmas;
- label every gap as routine / technical / strategic / currently unsupported by library;
- do not claim the theorem is proved unless all strategic gaps are closed.

# Geometry/Topology Discipline

Before proving, run this checklist:

1. Identify the category:
   Top, SmoothManifold, AlgebraicTopological spaces, CW complexes, spectra, schemes/stacks, symplectic/contact manifolds, etc.

2. Identify morphisms:
   continuous maps, smooth maps, embeddings, submersions, homotopies, isotopies, bundle maps, maps preserving extra structure.

3. Identify equivalence:
   homeomorphism, diffeomorphism, homotopy equivalence, weak equivalence, cobordism, isotopy, concordance, quasi-isomorphism.

4. Audit hypotheses:
   compactness, connectedness, orientability, boundary/non-boundary, paracompactness, Hausdorff, second countable, basepointedness, transversality, genericity.

5. Audit constructions:
   pullback/pushforward, fiber product, quotient, gluing, collar neighborhood, classifying map, obstruction class, spectral sequence page, differential, filtration.

6. Audit signs and orientations:
   boundary orientation, intersection sign, cap/cup product convention, Poincare duality convention.

7. Search for counterexamples:
   check low-dimensional cases, non-orientable cases, disconnected cases, boundary cases, non-compact cases.

# Proof Construction Rules

- Prefer decomposing into named helper lemmas with exact statements.
- Never hide the main theorem inside one helper lemma with sorry.
- A good gap is local, technical, and independently checkable.
- A bad gap is circular, equivalent to the target, or contains the core geometric insight.
- If a named theorem is used, state whether it is:
  supplied by user / in Lean library / standard but unformalized / conjectural.
- Do not invent references or claim literature support without supplied evidence.
- If Lean fails, use the error message to simplify the goal, reduce context, or split the statement.
- Prefer small lemmas:
  definitions first, coercions second, algebraic/topological identities third, final theorem last.

# Tool Policy

Use search_replace for all code edits.
After each edit, compile.
If compilation fails, repair before ending the session.
If unable to finish, leave a compiling sketch with structured comments:

/-
GT_ATTEMPT_SUMMARY:
Status:
Main idea:
Closed lemmas:
Remaining gaps:
Why the current obstruction is nontrivial:
Next suggested step:
-/

# Output Contract

Return one of:

PROVED:
  Lean proof compiles, no sorry, theorem unchanged.

PARTIAL:
  Compiling sketch with explicit gap ledger.

MISFORMALIZED:
  The Lean theorem does not match the natural-language target; explain the mismatch.

COUNTEREXAMPLE:
  Provide exact counterexample and verify all assumptions.

BLOCKED:
  Explain the precise obstruction and the next executable formalization step.
```

---

## 4. GT rater prompt

创建 `prompts/gt_rater_system.md`。

```markdown
# Role

You are GTRater, a strict judge of geometry/topology proof sketches and Lean formalization attempts.

# Objective

Rank competing sketches from best to worst. Favor sketches that make real mathematical progress, expose assumptions, and decompose hard geometry/topology arguments into checkable lemmas.

# Criteria, in priority order

1. Logical soundness
Reject circular reasoning, false statements, theorem-statement tampering, fake references, or hidden uses of the target theorem.

2. Geometry/topology correctness
Check category, hypotheses, functoriality, naturality, basepoints, compactness, orientations, boundary terms, transversality, signs, and low-dimensional exceptions.

3. Decomposition quality
Good gaps are local, routine, and checkable.
Bad gaps restate the theorem, contain the core construction, or assume the main invariant behaves as needed without proof.

4. Formalization viability
Prefer sketches closer to Lean verification, with small lemmas and stable definitions.

5. Strategic novelty
Reward genuinely different routes: obstruction-theoretic, homological, spectral sequence, surgery/cobordism, local model, reduction to known formal library.

# Required Output

1. Summary of each sketch.
2. Critical flaw analysis.
3. Gap quality analysis.
4. Final ranking.

Use exact final format:

<decision>2 > 1 = 3</decision>
```

---

## 5. Validator 规则

实现 `GTValidator`，强制以下检查。

```yaml
forbidden_final_tokens:
  - sorry
  - admit
  - axiom
  - unsafe
  - by
    native_decide # only forbid when it proves non-computational theorem by abuse
  - set_option maxHeartbeats 0

integrity_checks:
  theorem_statement_unchanged: true
  edits_only_inside_evolve_markers: true
  imports_unchanged_unless_config_allows: true
  namespace_preserved: true
  no_new_axioms: true
  no_environment_exploit: true
  final_lean_compile: true
```

失败时返回：

```json
{
  "status": "REJECTED",
  "reason": "theorem statement changed outside EVOLVE markers",
  "repair_hint": "revert theorem signature and only add helper lemmas inside EVOLVE-BLOCK"
}
```

---

## 6. GT-specific knowledge bundle

新增 `knowledge/gt_domain_checklist.md`，供 prompt builder 注入。不要一次性塞满上下文，只按任务领域检索相关部分。

内容分区：

```text
1. General topology
   compactness, Hausdorff, quotient maps, covering maps, local compactness.

2. Algebraic topology
   homotopy groups, long exact sequences, Hurewicz, universal coefficient, spectral sequences.

3. Differential topology
   manifolds with boundary, transversality, Sard, tubular neighborhoods, orientations, degree.

4. Fiber bundles and characteristic classes
   principal bundles, associated bundles, obstruction theory, Chern/Stiefel-Whitney/Euler classes.

5. Low-dimensional topology
   surfaces, 3-manifolds, Heegaard splittings, Dehn surgery, mapping class groups.

6. Symplectic/contact topology
   Hamiltonian isotopy, Floer-type caveats, compactness and bubbling warnings.

7. Algebraic/log geometry interface
   schemes/stacks, divisors, log structures, moduli spaces, virtual classes.
```

---

## 7. Prompt builder

实现 `build_gt_prover_prompt()`：

```python
def build_gt_prover_prompt(problem, sketch, prior_attempts, lean_feedback, domain_context):
    return render(
        "gt_prover_system.md",
        code=sketch.code,
        prior_attempts=format_prior_attempts(prior_attempts),
        lean_feedback=lean_feedback,
        domain_context=select_gt_context(domain_context),
        gap_ledger=extract_gap_ledger(sketch),
        allowed_references=problem.allowed_references,
        forbidden_assumptions=problem.forbidden_assumptions,
    )
```

Prior attempts 格式：

```markdown
# Prior Attempts

Attempt 1
Status: PARTIAL
Elo: 1432
Main idea:
Closed lemmas:
Remaining gaps:
Rater criticism:
Lean feedback:
```

---

## 8. Gap ledger

每个 partial sketch 必须写入 gap ledger。

```markdown
# GT Gap Ledger

## Gap G1
Statement:
Type: routine / technical / strategic / library-missing / conjectural
Depends on:
Why needed:
Current evidence:
Lean status:
Risk:
Next step:

## Gap G2
...
```

Rater 必须惩罚以下 bad gaps：

```text
- lemma essentially restates target theorem;
- lemma assumes existence of object whose construction is the core problem;
- lemma invokes unverified “standard theorem” without exact statement;
- lemma hides compactness/transversality/orientation assumptions;
- lemma changes category silently;
- proof uses a stronger hypothesis not present in target.
```

---

## 9. 输出协议

GT agent 的最终结果统一为：

```json
{
  "status": "PROVED | PARTIAL | MISFORMALIZED | COUNTEREXAMPLE | BLOCKED",
  "formal_artifact": "path/to/final.lean",
  "natural_language_summary": "path/to/summary.md",
  "gap_ledger": "path/to/gap_ledger.md",
  "assumption_audit": "path/to/assumption_audit.md",
  "rater_report": "path/to/rater_report.md"
}
```

`summary.md` 模板：

```markdown
# GT Agent Result

## Status

## Formal theorem

## Natural-language theorem

## Match between formal and informal statement

## Proof strategy

## Closed components

## Remaining gaps

## Geometry/topology assumption audit

## Potential counterexamples checked

## Next executable steps
```

---

## 10. 测试要求

Codex 完成后必须添加最小测试集。

### 10.1 Marker integrity test

输入一个 Lean 文件，在 theorem statement 外诱导 agent 修改目标。期望：validator 拒绝。

### 10.2 No fake theorem test

给出自然语言提示：“使用不存在的 Smith–Jones compactness theorem”。期望：GT agent 标记为 unverified claim，不得当作已证定理使用。

### 10.3 Bad gap test

输入 partial proof：

```lean
lemma main_hidden_gap : target_statement := by
  sorry
```

期望：rater 判定为 bad strategic gap。

### 10.4 Geometry hypothesis audit test

输入命题：“任意非紧定向流形上 Poincare duality 成立。”期望：agent 指出缺少 compact support / closed manifold / finite type 等条件，返回 `MISFORMALIZED` 或 `PARTIAL`，不得直接证明。

### 10.5 Lean smoke test

构造一个简单可证 theorem，要求 agent 生成 sorry-free proof，并通过 validator。

---

## 11. Codex 实施顺序

按以下顺序改仓库：

```text
1. 新增 gt_agent/ 目录和 prompt 文件。
2. 实现 GTValidator：先做 theorem integrity、marker integrity、sorry-free final check。
3. 实现 GTProverSubagent：复用现有 LLM + search_replace + compile loop。
4. 实现 basic GTController。
5. 实现 gap ledger 解析与 attempt summary 写回。
6. 实现 GTRaterSubagent。
7. 实现 population_db 和 P-UCB sampler。
8. 增加 CLI：
   python -m gt_agent.run --problem path/to/problem.lean --mode basic
   python -m gt_agent.run --problem path/to/problem.lean --mode evolution
9. 加测试。
10. 写 README_GT_AGENT.md。
```

---

## 12. README_GT_AGENT.md 必须说明

```markdown
# GT Agent

GT Agent is a geometry/topology research agent inspired by AlphaProof Nexus-style formal proof search.

## Modes
- basic: independent prover loops with Lean feedback.
- evolution: population database + rater + P-UCB sampling.

## Input
Lean proof sketch with EVOLVE-BLOCK / EVOLVE-VALUE markers, plus optional gt_context.md.

## Output
PROVED / PARTIAL / MISFORMALIZED / COUNTEREXAMPLE / BLOCKED.

## Soundness policy
The final theorem must compile without sorry/admit/axiom/unsafe.
Natural-language claims must be labeled by verification status.

## Geometry/topology policy
Always audit category, hypotheses, basepoints, orientations, compactness, boundary, transversality, functoriality, and local-to-global steps.
```

---

## 13. 实现重点

这份手册的实现重点不是复刻 DeepMind 的 AlphaProof，而是抽取它的可落地结构：

```text
proof sketch
+ 小步修改
+ 编译反馈
+ validator
+ rater
+ population search
```

几何拓扑版的关键增强是：把范畴、假设、方向、紧性、边界、横截性、自然性、函子性和反例检查变成 agent 的硬约束，而不是事后评论。
