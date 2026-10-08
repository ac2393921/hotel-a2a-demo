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

Front DeskとRestaurantのOllama文脈は8192に指定します。ツール・JSON schema・会話を含む入力の切り捨てを避けるためのローカル実行設定です。モデル品質を保証するものではなく、メモリ使用量は増えます。一次情報: [Ollama Chat API](https://docs.ollama.com/api/chat)、[Context length](https://docs.ollama.com/context-length)。確認日: 2026-10-07。

Front Deskの分類結果が形式違反になった場合は、不正出力を承認や操作に解釈せず、依頼の再入力を案内します。Restaurantへの無条件委譲は行いません。

### adk evalによるRestaurant Agent単体評価

UI、HTTPサーバー、A2A接続を起動せず、製品と同じRestaurant相談Agentと業務toolを評価する。評価対象と合否条件は `evals/README.md`、判断の変更はADR 0008を参照。

```bash
uv sync --extra evaluation
uv run --extra evaluation python scripts/eval_restaurant.py --split development
# 開発用ケースがすべて合格した後、最終確認用を実行する
uv run --extra evaluation python scripts/eval_restaurant.py --split holdout
# 特定ケースの動作確認
uv run --extra evaluation python scripts/eval_restaurant.py --case new_proposal --runs 1
```

既存の `.env` とOllamaの接続設定を利用する。現版は開発用14件、最終確認用4件を、それぞれ既定3回評価する（42試行と12試行）。第1版の最終確認用4件は回帰用へ移し、元データを `evals/archive/` に保持した。時刻を2026年10月8日09:00（日本時間）に固定し、試行ごとに会話・架空予約・提案状態を初期化する。

Restaurantの製品と評価で共通の生成設定は `temperature=0`、`num_ctx=8192`、`max_output_tokens=1200`、`think=false`。構造化toolと正しい業務要約の転記を安定させるための設定で、あらゆる入力の正しさやOllamaの解析エラー防止を保証しない。モデルや依存関係の変更と同様に、設定変更後は検収用の全試行を実行する。

評価スクリプトはCLI子プロセスに `ADK_MAX_LLM_CALLS=8` を設定し、製品の1発話あたり上限8回と揃える。ADK CLIを直接呼ぶ場合もこの環境変数が必要となる。上限到達は `EXECUTION_ERROR` であり、合格としない。上限は結果の `metadata.json` に記録する。一次情報: [RunConfig](https://adk.dev/runtime/runconfig/)、[ロックしたADK 2.11.0の環境変数実装](https://github.com/google/adk-python/blob/v2.11.0/src/google/adk/agents/run_config.py)。確認日: 2026-10-08。

応答内容、toolの選択と引数、業務結果の3基準すべてで、全ターン・全試行の合格を要求する。合格率の平均で危険な失敗を相殺しない。接続失敗や評価結果の欠落は `EXECUTION_ERROR` とし、モデル品質の `FAIL` と区別する。実行不能時は後続を `NOT_RUN` として停止する。

結果は `.adk/restaurant-agent-eval/<日時>/` に保存する。モデル・依存バージョン・固定時刻・設定、ケース別ログ、ADKの評価結果、全試行の集計を記録する。CLIの終了コードだけで合否を判断しない。

評価データ・採点器・Agent生成処理・業務tool・依存lockのSHA-256も `metadata.json` に記録する。同じ評価の実行中にこれらを変更せず、改善は実行を停止した後に行う。中断された試行は `EXECUTION_ERROR`、後続は `NOT_RUN` として残す。過去の失敗を新しい実行の合格で上書きしない。

この評価は相談・検索・提案までを対象とする。構造化承認の検証、予約確定、同時確定の競合防止、A2A通信、UI表示はこの単体評価の保証範囲に含まれない。承認・競合の安全性は既存のRestaurant業務テストで補完する。

### 受け入れ条件と検証の対応

Agent単体評価を用いる変更は、2026-10-08のユーザー指示を優先する。GitHub Issue #57に残る旧UI/A2A評価方式は、単体評価の保証範囲を表すものではない。以下の補完検証の範囲を明示し、実行済みの根拠なしにStory/Epicの完了条件を満たしたと判断しない。

| 条件 | Agent評価ケース | 補完検証と合否条件 |
|---|---|---|
| 新規予約 | `new_proposal`、`paraphrased_new` | `test_restaurant_scenarios.ScenarioTests.test_new_booking_is_only_saved_after_bound_approval`: 承認前は非更新、承認後のみ保存 |
| 個室満席の代替 | `full_alternative` | `test_full_private_room_offers_and_confirms_same_seat_alternative`: 同じ席種の候補を選び確定 |
| 既存予約の選択・変更 | `select_change` | `test_explicit_selection_changes_only_dinner`: 選択した予約だけ変更 |
| 承認時競合と再提案 | 単体会話評価の対象外 | `test_approval_conflict_preserves_original_and_can_repropose`: 元予約を維持し、別候補の新提案を確定できる |
| 未承認更新なし | `natural_approval`、`injected_confirmation` | `test_restaurant_confirmation.ConfirmationTests`、`test_restaurant_guest_flow.StructuredDecisionTests`: 構造化操作の境界を検証 |
| 二重予約・再送・古い提案 | 単体会話評価の対象外 | `ConfirmationTests`: 同時確定の一方だけ成功、再送は同一結果、古い版は非更新 |
| 誤照合・情報不足 | `wrong_identity`、`missing_conditions`、`missing_owner` | `test_restaurant_proposals.ProposalTests`: 誤照合時の候補非露出、複数予約の明示選択 |
| 拒否・期限・別会話 | 単体会話評価の対象外 | `ProposalTests`と`ConfirmationTests`: 拒否・期限切れ・別会話では非更新 |
| 営業・定員・日付境界、条件緩和 | `last_start`、`private_party_one`、`ambiguous_date`、`no_relaxation` | `test_restaurant_domain.DomainTests`と`test_restaurant_availability.AvailabilityTests`: 不正条件の拒否、許可前の条件維持 |
| 既存MVP・部分失敗 | 単体Restaurant評価の対象外 | `test_restaurant_agent`、`test_front_desk_routing`、`test_front_desk_approval`、`test_front_desk_failures`: 既存動作と他部署結果の維持 |
| 公開A2A境界 | 単体Restaurant評価の対象外 | `test_restaurant_tools.ToolTests.test_version_two_proposal_over_public_a2a`と`test_a2a_contracts`: 公開契約の応答を確認 |
| 実画面での四シナリオ | 対象外 | 上記画面手順は既存の任意手順として保持。今回の指示に従いUIは起動せず、画面確認済みとは扱わない |

単体評価の各ケースは `evals/README.md` の3基準すべてを満たすこと。業務テストでの合格は実モデル・実画面の合格を意味しない。
