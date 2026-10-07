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

前提のセットアップ後、リポジトリのルートで一括起動スクリプトを実行できます。4つのA2Aサービスとゲスト向けWeb UIが起動し、Ctrl+Cでまとめて停止します。

```sh
./scripts/start_demo.sh
```

ゲスト向けWeb UIの既定ポート8000を変更する場合は、たとえば次のように指定します。

```sh
GUEST_UI_PORT=8010 ./scripts/start_demo.sh
```

各Agentを別ターミナルから個別に起動する場合は、以下のコマンドを使います。4つのAgentは別プロセスのA2Aサービスとして動き、Guest UIはADK Runnerを通じてFront Desk Agentを呼び出します。

Front Desk A2AサービスとGuest UIは同じAgent定義をそれぞれ独立したプロセスで読み込みます。ゲストとの会話はGuest UIプロセス内のFront Deskインスタンスが処理します。ポート8000が使用中の場合は、Guest UIの`--port`を空いているポート（例: 8010）に変更してください。

| ターミナル | Agent / 画面 | 起動コマンド | ポート |
| --- | --- | --- | ---: |
| 1 | Maintenance Agent | `uv run uvicorn agents.maintenance_agent.agent:a2a_app --host 127.0.0.1 --port 8001` | 8001 |
| 2 | Housekeeping Agent | `uv run uvicorn agents.housekeeping_agent.agent:a2a_app --host 127.0.0.1 --port 8002` | 8002 |
| 3 | Restaurant Agent | `uv run uvicorn agents.restaurant_agent.agent:a2a_app --host 127.0.0.1 --port 8003` | 8003 |
| 4 | Front Desk A2Aサービス | `uv run uvicorn agents.front_desk_agent.agent:a2a_app --host 127.0.0.1 --port 8004` | 8004 |
| 5 | Guest UI | `uv run uvicorn hotel_ui.app:app --host 127.0.0.1 --port 8000` | 8000 |

Guest UIを開き、起動ログに表示されるURLでゲスト会話を開始します（既定ポートでは`http://127.0.0.1:8000`）。部署AgentのA2A Agent Cardはそれぞれ`http://localhost:8001/.well-known/agent-card.json`、`http://localhost:8002/.well-known/agent-card.json`、`http://localhost:8003/.well-known/agent-card.json`で確認できます。Front DeskのAgent Cardはポート8004で公開されます。

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

Guest UIは起動ログに表示されるローカルURLへアクセスします。各Agentを個別に起動できるため、障害時は該当するターミナルのログを確認できます。

## E2Eシナリオ

4つのAgentサービスとOllamaが起動した状態で実行します。

```sh
uv run python -m scripts.e2e_demo
```

このシナリオは、3部署への委譲、同じ会話での20時への承認、Maintenance Agentへの接続を失敗させた場合の部分回答を順に確認します。予約状態はRestaurant Agentのプロセス内メモリにあるため、開始時刻が19時でない場合はRestaurant Agentを再起動してから実行してください。障害確認ではMaintenance Agentの停止状態をポート8799への接続失敗で再現し、実際のサービスプロセスには触れません。

## 参考資料

- [ADK公式: A2A Agentの公開](https://adk.dev/a2a/quickstart-exposing/)
- [ADK公式: Web UIの起動](https://adk.dev/runtime/web-interface/)

## Restaurant予約相談の検証

RestaurantはローカルOllamaで条件の聞き取りとtool選択を行い、空席・照合・提案・確定はヘキサゴナル構成の業務層で判断します。確定toolをLLMに渡しません。Guest UIの「予約案を承認」「予約案を拒否」は提案ID付きの操作です。「はい」と入力するだけでは確定しません。

### 初期データとリセット

Restaurant起動日の翌日（Asia/Tokyo）に、すべて架空の次の予約を生成します。

| 部屋番号・氏名 | 予約ID | 開始 | 人数・席種 |
| --- | --- | --- | --- |
| 101・デモ花子 | demo-lunch | 12:00 | 2名・通常テーブル |
| 101・デモ花子 | demo-dinner | 19:00 | 4名・通常テーブル |
| 202・架空太郎 | demo-private | 18:30 | 4名・個室 |

90分利用です。個室は1卓なので翌日19:00は満席、20:00は代替候補になります。新規予約に実在する個人情報を使わないでください。

RestaurantをCtrl+Cで停止し同じ起動コマンドで再起動すると、予約・提案・Restaurant会話が初期化されます。Guest UIも再起動し、新しい会話を作ってください。Guest UI内の承認資格と会話は同じプロセス内だけに保持され、永続化されません。提案は10分で失効し、空席を仮押さえしません。日付が変わった場合も両方を再起動してから検証します。

旧MVPの固定19時→20時の互換予約は、今回の複数予約データと独立しています。`scripts.e2e_demo`の前にもRestaurantを再起動してください。

### 自動検証

```sh
uv run python -m unittest discover -s tests
node --check hotel_ui/static/app.js
```

ドメイン境界、営業日時・定員、誤照合、拒否、期限・元予約の版、同時確定、再送、保存失敗のロールバック、token非露出を検証します。`test_restaurant_scenarios`は四つの業務フローをtoolからFront Deskの承認境界まで通し、未承認での非更新・同一卓の重複なし・変更元維持を確認します。LLMの自然文解釈と画面操作はこの検証の対象外です。

### 実モデルと公開A2Aを通すHTTP E2E

OllamaとRestaurantとGuest UIを起動し、初期化済みの状態で実行します。既定以外のGuest UIポートには`--url`を指定します。

```sh
uv run python -m scripts.e2e_restaurant --url http://127.0.0.1:8000
```

順序は新規→個室満席の代替→対象を選んだ変更→承認時競合と変更元の再照合・再提案です。最後の競合では、翌々日の20:30と20:00に重なる個室の提案を二会話で作り、20:30を先に確定します。20:00の変更は失敗し、元の翌日20:30予約を維持します。代替の翌々日19:00を新たに選んで確定します。

このスクリプトはGuest UIのHTTP入口からFront Desk、公開A2A、Restaurant、実LLMを通します。プロセス内部の予約storeを直接操作しません。検索だけで終わった場合は同じ条件を明示的に選ぶゲスト発話を1回送ります。失敗時に自動承認・条件変更・無制限再試行は行わず、応答とassertionで停止します。モデル次第で結果や所要時間は変わります。原因を直して両プロセスをリセットしてから再実行してください。

### 画面での確認

Guest UIを開き、上記の順番と架空ゲストで次を確認します。HTTPの成功だけで画面確認済みとは扱いません。

1. 翌日18:00、2名、通常テーブル、101号室のデモ花子、窓際希望で相談。予約案に日時・人数・席種・90分・窓際非確約・未確定が表示される。「はい、承認します」を送っても提案は残り、承認ボタンで確定する。
2. 翌日19:00、4名、個室の空席を相談。満席と20:00の候補を確認し、20:00を選んで提案を承認する。席種変更・時間範囲拡大はチェック欄による明示許可なしに行わない。
3. 101号室のデモ花子を照合。複数の候補が出ることを確認し、demo-dinnerを翌日20:30の通常テーブルに変更する案を選ぶ。承認前は元予約が維持され、承認後だけ変更される。
4. 別会話で翌々日20:30の個室新規案を作り、さらに別会話でdemo-dinnerを翌々日20:00の個室へ変更する案を作る。前者を先に承認し、後者の承認では満席を表示する。元予約を再照合し、候補19:00を選んで新しい案を承認する。

拒否ボタンで非更新、期限切れ時の再相談、古い提案IDへの409、通信デバッグへの氏名・部屋番号・承認tokenの非露出も確認します。起動したサービスをCtrl+Cで停止し、使用したポートのlistenが残っていないことを確認してください。他の利用者が起動済みのサービスは停止しません。
