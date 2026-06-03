# GT Agent

GT Agent 是一个面向几何与拓扑研究的智能代理，重点用于证明审计、问题拆解，以及有文献依据的检索与分析。

它支持：

- 面向 Lean 的证明工作流与校验
- 本地 Web UI 研究控制台
- 支持可选 PDF 落地的 arXiv 检索
- `PROVED`、`PARTIAL`、`BLOCKED` 等结构化状态输出

## 近期工具更新

最近一次工具链更新主要聚焦在让 arXiv 检索更稳定，并减少“只拿到摘要”的情况：

- `arxiv_search` 现在支持精确 arXiv ID 查询，例如 `2606.02478` 或 `https://arxiv.org/abs/2606.02478`
- 会自动补全摘要页元数据，以提高标题、作者、日期和 PDF 信息的稳定性
- PDF 下载支持 `curl`、`curl.exe`、`wget`，并带 `urllib` 回退
- 下载后的 PDF 可通过 `pypdf` 本地预览，因此摘要和总结可以基于全文而不只是短摘要
- 当 PDF 可用时，直接 arXiv 查询结果中可以返回本地 PDF 路径和 PDF 预览文本

相关环境变量：

```text
GT_ARXIV_MAX_DOWNLOADS=2
GT_ARXIV_DOWNLOAD_DIR=C:\path\to\arxiv_papers
```

常见提示词示例：

```text
Download arXiv 2606.02478 PDF and summarize the full paper.
Find arXiv paper 2501.01234v2 and give me the local PDF path.
Search arXiv for recent math.AT papers and return the links.
```

## 环境要求

- Python 3.10 或更高版本
- Windows、macOS 或 Linux
- 一个兼容 OpenAI API 的模型服务，用于研究模式

检查 Python：

```powershell
python --version
```

## 安装

安装项目：

```powershell
python -m pip install -e .
```

如需测试依赖：

```powershell
python -m pip install -e ".[test]"
```

运行测试：

```powershell
python -m pytest
```

## 运行模式

- `basic`：独立证明循环，结合 Lean 反馈与 GTValidator 校验
- `evolution`：带本地候选池、评分器与 P-UCB 采样的演化模式

## 输入格式

推荐使用带 `EVOLVE-BLOCK` / `EVOLVE-VALUE` 标记的 Lean 证明草稿，可选搭配 `gt_context.md`。

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

也支持自然语言 `.md` 输入用于审计和拆解，但本地适配器不会将这类输入标记为 `PROVED`。

## CLI 用法

```powershell
python -m gt_agent.run --problem path\to\problem.lean --mode basic
python -m gt_agent.run --problem path\to\problem.lean --mode evolution
```

输出目录位于 `gt_agent_runs/<problem>_<mode>/`，通常包括：

- `final.lean` 或 `final.md`
- `summary.md`
- `gap_ledger.md`
- `assumption_audit.md`
- `rater_report.md`
- `result.json`

## Web UI

启动本地研究控制台：

```powershell
python -m gt_agent.web_app --host 127.0.0.1 --port 8765
```

然后在浏览器中打开：

```text
http://127.0.0.1:8765
```

如果希望同一局域网内其他设备访问本机 UI：

```powershell
python -m gt_agent.web_app --host 0.0.0.0 --port 8765
```

终端会输出可访问地址，例如：

```text
GT Agent UI running at http://127.0.0.1:8765
GT Agent UI running at http://192.168.1.20:8765
```

现在也可以直接双击根目录下的启动脚本：

```text
start_gt_agent_ui.bat
```

它会自动启动本地 Web UI 并打开浏览器，不需要每次手动输入 PowerShell 命令。

后端接口为：

```text
POST /api/research
```

该接口会先用 GT Agent 的研究提示词、本地假设审计和 gap ledger 包装问题，再调用配置好的模型。

## 模型配置

启动 Web UI 前可设置以下环境变量：

```powershell
$env:GT_MODEL_BASE_URL="https://api.openai.com/v1"
$env:GT_MODEL="gpt-4.1"
$env:GT_MODEL_API_KEY="your-api-key"
$env:GT_MODEL_TEMPERATURE="0.2"
$env:GT_MODEL_MAX_TOKENS="4096"
```

如果使用代理或其他兼容 OpenAI 的服务：

```powershell
$env:GT_MODEL_BASE_URL="https://example.com/v1"
$env:GT_MODEL="your-model-name"
$env:GT_MODEL_API_KEY="your-api-key"
```

如果使用本地模型服务，例如 LM Studio、兼容 Ollama 的端点或 vLLM：

```powershell
$env:GT_MODEL_BASE_URL="http://127.0.0.1:1234/v1"
$env:GT_MODEL="your-local-model-name"
$env:GT_MODEL_API_KEY="any-non-empty-value-required-by-the-server"
```

注意：`127.0.0.1` 和 `localhost` 永远指向当前这台机器。如果你把项目移到另一台电脑上，那么第二台电脑的 `127.0.0.1` 不会指回原来的模型服务。

## Web UI 字段说明

当前 UI 支持输入：

- Provider URL，例如 `https://api.openai.com/v1` 或 `http://127.0.0.1:1234/v1`
- 模型名称，例如 `gpt-4.1` 或本地兼容 OpenAI 的模型名
- API Key，仅随当前请求发送，不会写入磁盘
- 几何 / 拓扑问题正文，以及可选的领域上下文
- temperature 和 max-token 参数

## 输出状态说明

- `PROVED`：Lean 证明可编译，且不含 `sorry` / `admit` / `axiom` / `unsafe`，并且 evolve 标记外的定理未被改动
- `PARTIAL`：有可审计的进展或拆解结果，并明确列出尚未填补的缺口
- `MISFORMALIZED`：形式化或自然语言陈述缺少必要假设，或与原意不匹配
- `COUNTEREXAMPLE`：找到了明确反例
- `BLOCKED`：精确说明了阻塞点和下一步可执行动作

## 可靠性策略

最终定理必须在没有 `sorry`、`admit`、`axiom`、`unsafe` 或环境逃逸的情况下编译通过。GTValidator 会强制校验：

- 定理陈述在 evolve 标记外保持不变
- 编辑仅发生在 evolve 标记内部
- import 不变，除非另有配置
- namespace 保持不变
- 不允许新增公理或 unsafe 声明
- 只有最终 Lean 编译通过时才接受 `PROVED`

自然语言结论必须带验证状态。凡是用户或 Lean 库未明确提供的命名结论，都视作未验证主张。

## 几何 / 拓扑审计策略

GT Agent 会持续审查范畴、假设、基点、定向、紧致性、边界、横截性、函子性，以及局部到整体的推理步骤。该本地审计尤其擅长捕捉一些常见高风险模式，例如在非紧流形上过度泛化 Poincare 对偶。

## 实现边界

当前本地已完整实现的部分包括：

- `gt_agent/` 包
- GT prover 与 rater 提示词
- `GTValidator`
- basic 模式控制器
- gap ledger 渲染与抽取
- attempt summary 结构
- CLI
- 确定性的本地 rater
- pytest 烟雾测试与策略测试

适配器或占位实现的部分包括：

- LLM 证明提议通过 `GTProverSubagent.propose_next_code` 表示；内置版本目前只做保守型本地修补，例如把 `True := by sorry` 修成 `trivial`
- 模型研究调用通过 `OpenAICompatibleClient` 完成，这是一个小型 `/chat/completions` 适配器，支持 OpenAI 和兼容服务
- Lean 集成通过薄封装 `LeanCompiler` 完成；如果系统里没有 `lean`，最终结果不会被接受为 `PROVED`
- evolution 模式目前是单进程、内存态的候选池 + rater + P-UCB 接口，并不是分布式搜索系统

## 故障排查

### WinError 10061 / connection refused

这通常表示 Provider URL 指向的服务没有启动、监听端口不对，或者服务运行在另一台机器上，而不是 API Key 格式问题。

建议检查：

- 如果是云端 API，确认 URL 的结尾确实像 `https://.../v1`
- 如果是本地模型，先启动模型服务，再启动 GT Agent
- 如果模型服务在另一台机器上，不要使用 `127.0.0.1`，而要用那台机器的局域网 IP，例如 `http://192.168.1.20:1234/v1`
- 确认服务端机器允许该端口的入站访问

### 浏览器打不开 Web UI

建议检查：

- 本机访问时，使用 `--host 127.0.0.1`，然后打开 `http://127.0.0.1:8765`
- 局域网访问时，使用 `--host 0.0.0.0`，然后打开终端输出的局域网地址
- 如果端口被占用，换一个端口，例如 `--port 8777`

### 命令一运行就直接回到 PowerShell

正常情况下，Web UI 命令会持续运行，并输出 `GT Agent UI running at ...`。

如果它立即退出：

- 确认你是在项目根目录运行命令
- 重新执行 `python -m pip install -e .`
- 确认完整命令是 `python -m gt_agent.web_app --host 127.0.0.1 --port 8765`
- 不要只运行参数片段，例如单独输入 `--host 127.0.0.1 --port 8765`

## 仓库说明

现在这份 `README.md` 已替代原先拆分的 `README.md` 与 `README_GT_AGENT.md` 说明方式，因此安装、运行、故障排查和工具更新说明都集中维护在这里。
