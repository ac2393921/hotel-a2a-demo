# Restaurant Agent A2A契約

Restaurant Agentは`localhost:8003`でA2Aサービスとして動作する。業務判断は固定ロジックで、LLMや外部予約サービスは使わない。

リクエスト本文はUTF-8のJSONオブジェクトとする。

## 予約変更の照会

```json
{"action":"propose_change","requested_time":"20:00"}
```

Agentは変更案とランダムな`proposal_id`を返す。提案しただけでは予約時刻は変わらず、初期時刻の`19:00`を維持する。

## 提案の承認

```json
{"action":"approve_change","proposal_id":"提案応答に含まれるID"}
```

有効な提案IDを一度だけ受け付け、予約時刻を`20:00`に更新する。未知・期限切れ・すでに使ったIDでは更新しない。

## 提案の拒否

```json
{"action":"reject_change","proposal_id":"提案応答に含まれるID"}
```

提案を破棄し、予約時刻は維持する。

## 状態照会

```json
{"action":"get_status"}
```

現在の模擬予約時刻を返す。予約時刻と提案はプロセス内のメモリだけに保持され、再起動で初期状態に戻る。

Front Deskはゲスト本人の明示承認を確認してから`approve_change`を送る。Restaurant Agentは同意の推測や自然文の承認判断を行わず、構造化された承認コマンドだけで状態を更新する。

## 次期予約相談（version 2）

`{"version":2,"action":"consult","conversation_id":"Front Deskの会話ID","message":"ゲストの依頼"}` を受け付け、RestaurantのLLMが空席検索・予約照合・新規提案・変更提案toolを使う。会話IDはtool引数に含めず、サーバー側で束縛する。`expand_time_permitted` と `alternate_seat_permitted` はFront Deskがゲストの許可を確認して設定する真偽値で、既定はfalse。確定・拒否toolはLLMへ公開しない。

結果は業務toolの構造化結果を優先する。提案の承認tokenはLLMのtool応答と内部会話イベントに含めず、サーバー間の応答にのみ付ける。Front DeskとUIの対応はTask #56で接続する。version 2の確定・拒否はLLMを経由せず、conversation_id・proposal_id・approval_tokenを持つ構造化コマンドで処理する。既存version未指定の固定時刻デモは独立した互換状態を利用する。

公式確認（2026-10-07）:
- Function tools: https://adk.dev/tools-custom/function-tools/
- Runner: https://adk.dev/runtime/
- LiteLLM: https://adk.dev/agents/models/litellm/

ロックされたADKのRunner.run_async、InMemorySessionService、FunctionTool変換を模擬モデルで実行して確認する。実モデルでの予約相談とFront Desk/UIのE2Eは接続完了後に検証する。

確定時は会話・token・期限・変更元の版・空席を再確認する。競合時は元予約を維持し、再検索候補を返す。確定済み提案の同じ会話・tokenによる再送は同じ結果を返し、拒否済み・競合済み提案を再確定しない。予約更新と提案消費は一体のtransactionで処理する。

## Front Deskとゲスト画面

Guest UIの新しいセッションはversion 2予約相談を利用する。Front Deskは予約条件をRestaurantへ委譲し、Restaurantの追加質問・候補・照合結果をゲストへ返す。予約中の短い条件回答もRestaurantへ渡す。

ゲスト画面の予約案には確認内容を表示し、承認・拒否ボタンはdecisionとproposal_idを送る。Front Deskはサーバー内で保持するtokenを用いて公開A2Aへ構造化操作を送る。自然文の肯定・拒否だけではversion 2予約を更新しない。期限切れ・競合では提案を解除し、元予約を維持した再相談へ進む。

時間範囲と席種を広げる場合は画面の許可チェックを利用する。既定は未許可。照合情報と承認資格を含むRestaurant向け依頼本文は通信デバッグに表示しない。承認tokenはADKの会話stateにも保持しない。

Restaurantのツール定義と会話に必要な文脈を確保するため、Ollamaの`num_ctx`を8192に指定する。実環境の既定4096ではツール生成が不安定だったための調整であり、生成品質を保証するものではない。メモリ使用量は増える。一次情報: [Ollama Chat API](https://docs.ollama.com/api/chat)、[Context length](https://docs.ollama.com/context-length)、ADK/LiteLLMのロック済み実装。確認日: 2026-10-07。
