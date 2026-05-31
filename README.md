# GT Agent 中文运行说明

GT Agent 是一个几何/拓扑研究辅助工具，提供命令行模式和本地 Web UI。把项目发到另一台电脑后，需要在那台电脑上重新安装 Python 依赖，并重新配置模型 API。

## 1. 环境要求

- Windows 10/11、macOS 或 Linux；
- Python 3.10 或更高版本；
- 一个 OpenAI 兼容的模型 API：例如 OpenAI 官方接口、第三方中转接口，或本机/局域网里的 OpenAI-compatible 服务。

在 PowerShell 中检查 Python：

```powershell
python --version
```

进入项目目录，例如：

```powershell
cd D:\agentgt
```

安装项目：

```powershell
python -m pip install -e .
```

如需运行测试：

```powershell
python -m pip install -e ".[test]"
python -m pytest
```

## 2. 配置模型 API

推荐在启动 Web UI 前设置环境变量。下面命令只对当前 PowerShell 窗口有效：

```powershell
$env:GT_MODEL_BASE_URL="https://api.openai.com/v1"
$env:GT_MODEL="gpt-4.1"
$env:GT_MODEL_API_KEY="你的 API Key"
```

如果使用第三方中转，把 `GT_MODEL_BASE_URL` 改成中转提供的 OpenAI-compatible 地址，例如：

```powershell
$env:GT_MODEL_BASE_URL="https://example.com/v1"
$env:GT_MODEL="你的模型名"
$env:GT_MODEL_API_KEY="你的 API Key"
```

如果使用本机模型服务，例如 LM Studio、Ollama OpenAI-compatible、vLLM 等，必须确认那个服务已经启动，并且地址和端口正确：

```powershell
$env:GT_MODEL_BASE_URL="http://127.0.0.1:1234/v1"
$env:GT_MODEL="本机服务里的模型名"
$env:GT_MODEL_API_KEY="任意非空字符串或服务要求的 key"
```

注意：`127.0.0.1` 和 `localhost` 永远表示“当前这台电脑”。如果把项目发给别人，别人电脑上的 `127.0.0.1:1234` 不会自动连接到你电脑上的模型服务。

## 3. 启动 Web UI

只在当前电脑浏览器里使用：

```powershell
python -m gt_agent.web_app --host 127.0.0.1 --port 8765
```

然后打开：

```text
http://127.0.0.1:8765
```

如果希望同一局域网里的其他设备访问这台电脑上的 Web UI：

```powershell
python -m gt_agent.web_app --host 0.0.0.0 --port 8765
```

启动后终端会打印可访问地址，例如：

```text
GT Agent UI running at http://127.0.0.1:8765
GT Agent UI running at http://192.168.1.20:8765
```

其他设备打开第二个局域网地址即可。Windows 防火墙可能会询问是否允许 Python 访问网络，请允许专用网络访问；如果没有弹窗，需要手动放行端口 `8765`。

不要把下面这一段单独输入 PowerShell：

```powershell
--host 127.0.0.1 --port 8765
```

它只是 `python -m gt_agent.web_app` 的参数，单独运行会出现 PowerShell 解析错误。

## 4. Web UI 中的填写方式

- `Provider URL`：模型 API 的基础地址，例如 `https://api.openai.com/v1` 或 `http://127.0.0.1:1234/v1`；
- `Model`：模型名，必须和你的 API 服务支持的模型名一致；
- `API Key`：如果已经设置了 `GT_MODEL_API_KEY`，这里可以留空；否则在这里填写；
- `Temperature`：一般保持 `0.2` 即可。

API Key 只会随当前请求发送给后端，不会被 Web UI 写入磁盘。

## 5. 常见错误

### WinError 10061 / connection refused

含义：目标地址拒绝连接。通常不是 API Key 错，而是 `Provider URL` 指向的服务没有启动、端口写错，或 `127.0.0.1` 用在了错误的电脑上。

处理方式：

- 使用云端 API 时，确认地址是完整的 `https://.../v1`；
- 使用本机模型时，先启动本机模型服务，再运行 GT Agent；
- 使用另一台电脑上的模型服务时，不要写 `127.0.0.1`，要写那台电脑的局域网 IP，例如 `http://192.168.1.20:1234/v1`；
- 确认提供模型服务的电脑已经放行对应端口。

### 浏览器打不开 Web UI

- 如果只在本机访问，使用 `--host 127.0.0.1`，打开 `http://127.0.0.1:8765`；
- 如果其他设备访问，使用 `--host 0.0.0.0`，打开终端打印的局域网地址；
- 检查端口是否被占用，可以换一个端口，例如 `--port 8777`。

### 运行命令后马上回到 PowerShell 提示符

正常情况下，启动 Web UI 后终端会停在运行状态，并打印 `GT Agent UI running at ...`。如果命令立刻结束：

- 确认你在项目根目录运行命令；
- 重新执行 `python -m pip install -e .`；
- 确认运行的是 `python -m gt_agent.web_app --host 127.0.0.1 --port 8765`，不要只运行参数部分。
