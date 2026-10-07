# Restaurant予約拡充の契約

- 状態: 実装契約（LLM追加は2026-10-07にユーザー承認）
- 対応: https://github.com/ac2393921/hotel-a2a-demo/issues/47
- 関連: [ADR 0005](../adr/0005-restaurant-reservation-hexagonal.md)

## 既存実装との差異

現行は構造化JSONを処理するBaseAgentで、RestaurantにLLMはない。Front Deskの会話stateに変更提案IDがあり、Guest UIの承認ボタンは自然文を送信する。このままでは、新規予約、候補選択、条件変更の許可、会話に結び付いた承認を十分表現できない。

## 合意済み境界

Front DeskはRestaurantの公開A2Aインターフェースだけを利用する。Restaurantの入力アダプターはアプリケーションAPIを呼び、業務ルールを再実装しない。予約・提案はRestaurantプロセス内だけに保持する。提案は仮押さえを行わず、承認時の再確認と更新を原子的に処理する。

## 実装方針

RestaurantへのLLM追加はユーザー承認済み。その他の詳細は既存の「おすすめで任せる」方針に基づき以下を採用する。実装は後続Taskで行う。

- 処理方式: RestaurantにLLMを追加して検索・提案toolを選ばせる。確定と拒否はLLMのtool一覧から分離し、構造化された承認経路で処理する。
- ホテル時刻: Asia/Tokyoを設定値として扱い、Clockポートから現在時刻を取得する。日付はISO形式、時刻はHH:MM。曖昧な日付・時刻は確認する。
- 候補順: 時刻差が小さい順、同距離なら早い時刻。卓は定員順、同定員なら卓ID順。候補は開始時刻単位で重複排除する。
- ゲスト情報: 新規と照合に架空の氏名・部屋番号を要求する。予約IDはサーバー生成。照合に失敗しても他ゲストの予約を返さない。
- 提案: サーバー生成ID、会話ID、所有者、予約条件、作成・期限時刻、状態、変更元予約の版を保持する。有効期限は10分とする。期限は仮押さえを意味しない。
- 確定: 会話に紐付く提案と明示承認を入力アダプターで検証する。LLMの生成したapprovedフラグは根拠にしない。確定済み提案の再送は同じ結果を返し、重複予約を作らない。
- 拒否: 提案を破棄し、元予約を維持する。未知・期限切れ・拒否済み・別会話の提案は確定できない。
- 競合: 変更元の版が変化していたら古い変更案を拒否する。空席競合時は元予約を維持して再検索を求める。
- 移行: 旧固定時刻契約を新規契約に黙って読み替えない。Front Desk・UI・E2Eを対応Taskで移行し、移行完了まで既存経路を維持する。

## 業務操作の契約

| 操作 | 主な入力 | 主な結果 |
|---|---|---|
| search_availability | 日付、希望時刻、人数、席種、許可された条件緩和 | 希望枠・最大3代替候補、追加確認、対応不可 |
| find_reservations | 会話ID、部屋番号、氏名 | 対象候補または該当なし。複数なら選択要求 |
| propose_reservation | 会話ID、ゲスト情報、選択条件、窓際希望 | 提案ID、期限、確認内容。席は未確保 |
| propose_reservation_change | 会話ID、照合済み予約ID、変更条件 | 提案ID、期限、変更前後の条件 |
| confirm_proposal | 会話ID、提案ID、明示承認経路の証拠 | 確定予約、再提案要求、期限切れ、競合、拒否 |
| reject_proposal | 会話ID、提案ID | 破棄結果。予約には影響しない |

## 通信と構造化結果

A2Aのメッセージ本文はJSONとし、次期契約には `version: 2` を必須にする。`conversation_id` はFront Deskがセッションから設定し、LLMの引数には含めない。ローカルの信頼されたFront Deskを境界とする。本番認証は対象外。

相談入力例:

```json
{"version":2,"action":"consult","conversation_id":"server-session-id","message":"明日19時に4人で個室を予約したい"}
```

承認入力例:

```json
{"version":2,"action":"confirm_proposal","conversation_id":"server-session-id","proposal_id":"server-generated-id","approval_token":"server-generated-capability"}
```

- Front DeskがGuest UIの構造化承認操作を受け、保管している提案ID・承認tokenを送る。tokenは提案作成時にRestaurantが生成してサーバー間だけで保持し、LLM、ブラウザー、通常ログへ渡さない。
- 自然文承認は確定せず構造化承認操作へ案内する。ADK Web利用時は提案までで、確定操作はGuest UIを使う。
- 確定・拒否のactionはRestaurantの入口で処理し、LLMを経由させない。LLMのtoolには検索・照合・新規提案・変更提案のみを公開する。
- toolは `date`（YYYY-MM-DD）、`time`（HH:MM）、`party_size`（1〜6の整数）、`seat_type`（table/private）、`window_preference`（真偽）を使う。新規・照合に `guest_name` と `room_number`、変更に照合済み `reservation_id` を用いる。
- 確約内容を変える相談は既存提案への承認に読み替えず、別提案を作成する。
- `status` は available / unavailable / clarification_required / proposed / confirmed / rejected / not_found / expired / conflict / invalid_request / failed。`message` は日本語。成功していない操作をconfirmedで返さない。
- 候補にはdate、time、party_size、seat_typeを含め、提案にはproposal_id、expires_at、summary、approval_requiredを含める。summaryは確定前に日付・時刻・人数・席種・90分利用・窓際非確約を説明する。
- 予約結果はreservation_idと確認条件を返す。照合応答は必要最小限の候補だけ返す。内部卓IDやゲスト情報は通常の会話応答に不要に露出させない。
- 明示許可がない場合は前後60分と元席種を維持する。許可された時間拡大は同じ営業枠全体まで。別席種検索も明示許可後に行い、人数は変えない。
- 予約区間は開始を含み終了を含まない。直前予約の終了と次の開始が一致する場合は重複としない。
- 期限切れ・拒否・競合で失効した提案は再確定しない。確定済み提案の同一会話・tokenでの再送だけは同じ結果を返す。

## 移行と検証

version未指定の旧操作は移行期間だけ既存の固定シナリオ用アダプターで扱う。Guest UIの一般予約と状態を混同せず、互換経路は非推奨と明記する。Task #56で新UIへ移行し、Task #57で既存E2Eを新しい確定境界へ移行する。旧経路の削除は互換影響を確認した別判断とする。

実装Taskでドメイン境界、誤照合、再承認、別会話、古い変更提案、同時確定、部分失敗を検証する。SDK利用はロックされたバージョンの公式実装とも照合する。

## 公式一次情報

- ADK Function tools: https://adk.dev/tools-custom/function-tools/ （2026-10-07確認。Python関数をtoolsに登録する方式とコンテキスト注入）
- ADK LiteLLM: https://adk.dev/agents/models/litellm/ （2026-10-07確認。既存Front Deskと同じ連携方式）
- ADK A2A公開: https://adk.dev/a2a/quickstart-exposing/ （2026-10-07確認。既存公開境界を維持）
