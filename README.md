# Hotel A2A Demo

ホテルのゲスト対応を題材に、Front Desk AgentがMaintenance、Housekeeping、Restaurantの各AgentへA2Aで依頼するローカルデモです。Front Deskの依頼判断にはOllama上のローカルLLMを使い、部署Agentは固定ロジックで応答します。

## 必要なもの

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com/)
- Ollamaモデル `qwen3.5:latest`

## セットアップ

リポジトリのルートで実行します。

```sh
uv sync
ollama pull qwen3.5:latest
cp -n .env.example .env
```

Ollamaを起動します。Ollamaアプリがすでに起動していれば、この手順は不要です。CLIで起動する場合は別ターミナルで実行します。

```sh
ollama serve
```

接続を確認します。

```sh
uv run python scripts/check_ollama.py
```

成功すると`Ollama接続成功`と表示されます。.envの既定値ではOllamaは`http://localhost:11434`、モデルは`qwen3.5:latest`です。

## 起動

リポジトリのルートで、次の5つを**それぞれ別のターミナル**で実行します。

| ターミナル | サービス | コマンド |
| --- | --- | --- |
| 1 | Maintenance Agent | `uv run uvicorn agents.maintenance_agent.agent:a2a_app --host 127.0.0.1 --port 8001` |
| 2 | Housekeeping Agent | `uv run uvicorn agents.housekeeping_agent.agent:a2a_app --host 127.0.0.1 --port 8002` |
| 3 | Restaurant Agent | `uv run uvicorn agents.restaurant_agent.agent:a2a_app --host 127.0.0.1 --port 8003` |
| 4 | Front Desk A2Aサービス | `uv run uvicorn agents.front_desk_agent.agent:a2a_app --host 127.0.0.1 --port 8004` |
| 5 | ADK Web | `PYTHONPATH=. uv run adk web agents/front_desk_agent --host 127.0.0.1 --port 8000` |

ADK Webを開きます。

```text
http://127.0.0.1:8000
```

ADK WebはFront Desk Agentを読み込み、ゲストとの会話を処理します。Front Desk A2Aサービス（8004）はAgent Cardを公開する独立サービスです。ポート8000が使われている場合は、ADK Webのコマンドの`--port 8000`を空いているポート（例: `--port 8010`）に変更してください。

## デモシナリオ

ADK Webで、たとえば次のように入力します。

```text
部屋のエアコンが壊れていて、19時からレストランも予約しています
```

Front Deskが関連する部署へ依頼し、修理可否、代替部屋、レストランの20時への変更案をまとめます。レストラン予約は提案だけでは変更されません。会話の中で変更案を承認すると、模擬予約が更新されます。

## 起動確認と停止

各AgentのAgent Cardを確認できます。

```sh
curl --fail http://localhost:8001/.well-known/agent-card.json
curl --fail http://localhost:8002/.well-known/agent-card.json
curl --fail http://localhost:8003/.well-known/agent-card.json
curl --fail http://localhost:8004/.well-known/agent-card.json
```

終了するときは、起動した各ターミナルで`Ctrl+C`を押します。サーバーはローカル開発用です。`127.0.0.1`にバインドし、外部ネットワークへ公開しないでください。

## E2Eシナリオ

4つのAgentサービスとOllamaを起動した状態で実行します。

```sh
uv run python -m scripts.e2e_demo
```

3部署への委譲、同じ会話での変更承認、Maintenance Agentに接続できない場合の部分回答を確認します。Restaurant Agentの予約状態はプロセス内メモリにあります。開始時に予約が19時でない場合は、Restaurant Agentを再起動して状態を初期化してください。

## 詳細

- [開発手順](docs/development.md)
- [設計書](docs/DESIGN.md)
