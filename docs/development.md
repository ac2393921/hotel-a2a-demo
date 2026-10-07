# 開発環境

## 前提

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com/)
- Ollamaモデル `qwen3.5:latest`

## セットアップ

```sh
uv sync
ollama pull qwen3.5:latest
cp .env.example .env
```

`.env`の既定値はOllamaを同じPCで動かす設定です。別のホストを使う場合は`OLLAMA_API_BASE`を変更してください。`.env`はGit管理対象外です。

ADKはLiteLLM経由でOllamaに接続します。モデル名には`ollama_chat/`を付け、Ollamaの接続先には`OLLAMA_API_BASE`を使います。ツール呼び出しを使うモデルでは、Ollamaモデルに`tools` capabilityがあることも確認してください。

## 接続確認

Ollamaを起動した状態で次を実行します。

```sh
uv run python scripts/check_ollama.py
```

成功するとモデルからの短い応答が表示されます。接続に失敗した場合は、Ollamaが稼働していること、`OLLAMA_API_BASE`が正しいこと、`ollama list`に`qwen3.5:latest`があることを確認してください。モデルがなければ`ollama pull qwen3.5:latest`で取得できます。

## 依存関係

`google-adk[a2a,extensions]`を利用します。依存バージョンは`uv.lock`に固定し、環境構築時は`uv sync`を使ってください。

## ローカルデモの起動

前提のセットアップ後、リポジトリのルートで各コマンドを別々のターミナルから実行します。4つのAgentは別プロセスのA2Aサービスとして動き、ADK WebはFront Desk Agentをゲスト画面として読み込みます。

Front Desk A2AサービスとADK Webは同じAgent定義をそれぞれ独立したプロセスで読み込みます。ゲストとの会話はADK Web側のFront Deskインスタンスが処理します。ポート8000が使用中の場合は、ADK Webの`--port`を空いているポート（例: 8010）に変更してください。

| ターミナル | Agent / 画面 | 起動コマンド | ポート |
| --- | --- | --- | ---: |
| 1 | Maintenance Agent | `uv run uvicorn agents.maintenance_agent.agent:a2a_app --host 127.0.0.1 --port 8001` | 8001 |
| 2 | Housekeeping Agent | `uv run uvicorn agents.housekeeping_agent.agent:a2a_app --host 127.0.0.1 --port 8002` | 8002 |
| 3 | Restaurant Agent | `uv run uvicorn agents.restaurant_agent.agent:a2a_app --host 127.0.0.1 --port 8003` | 8003 |
| 4 | Front Desk A2Aサービス | `uv run uvicorn agents.front_desk_agent.agent:a2a_app --host 127.0.0.1 --port 8004` | 8004 |
| 5 | ADK Web | `uv run adk web agents/front_desk_agent --host 127.0.0.1 --port 8000` | 8000 |

ADK Webを開き、起動ログに表示されるURLでFront Desk Agentとの会話を開始します（既定ポートでは`http://127.0.0.1:8000`）。部署AgentのA2A Agent Cardはそれぞれ`http://localhost:8001/.well-known/agent-card.json`、`http://localhost:8002/.well-known/agent-card.json`、`http://localhost:8003/.well-known/agent-card.json`で確認できます。Front DeskのAgent Cardはポート8004で公開されます。

停止するときは、起動した各ターミナルで`Ctrl+C`を押します。各サービスを別プロセスで起動しているため、停止対象を個別に選べます。

すべてローカル開発用です。各サーバーは`127.0.0.1`にだけバインドしてください。`0.0.0.0`で公開しないでください。

## 起動確認

A2Aサービスを起動したあと、別ターミナルからAgent Cardを確認できます。

```sh
curl --fail http://localhost:8001/.well-known/agent-card.json
curl --fail http://localhost:8002/.well-known/agent-card.json
curl --fail http://localhost:8003/.well-known/agent-card.json
curl --fail http://localhost:8004/.well-known/agent-card.json
```

ADK Webは起動ログに表示されるローカルURLへアクセスします。各Agentを個別に起動できるため、障害時は該当するターミナルのログを確認できます。

## E2Eシナリオ

4つのAgentサービスとOllamaが起動した状態で実行します。

```sh
uv run python -m scripts.e2e_demo
```

このシナリオは、3部署への委譲、同じ会話での20時への承認、Maintenance Agentへの接続を失敗させた場合の部分回答を順に確認します。予約状態はRestaurant Agentのプロセス内メモリにあるため、開始時刻が19時でない場合はRestaurant Agentを再起動してから実行してください。障害確認ではMaintenance Agentの停止状態をポート8799への接続失敗で再現し、実際のサービスプロセスには触れません。

## 参考資料

- [ADK公式: A2A Agentの公開](https://adk.dev/a2a/quickstart-exposing/)
- [ADK公式: Web UIの起動](https://adk.dev/runtime/web-interface/)
