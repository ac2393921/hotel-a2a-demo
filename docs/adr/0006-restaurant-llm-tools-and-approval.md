# ADR 0006: RestaurantのLLMと業務tool、構造化承認の分離

- 状態: 承認済み
- 決定日: 2026-10-07
- 関連: ADR 0005、Task #47
- 置き換える判断: ADR 0002のRestaurantを固定ロジックのみとする判断、ADR 0005のLLM追加未決を置き換える。

## 背景

ユーザーがRestaurantへのLLM追加を明示承認した。希望条件の聞き取りと候補の説明をRestaurantが担う一方、LLMによる未承認の予約確定を防ぐ必要がある。

## 決定

- RestaurantにLLMを追加し、既存Front Deskと同じOllama・LiteLLM経由のqwen3.5を初期モデルとして使う。
- LLMには検索・照合・提案のtoolだけを公開する。業務ルールはヘキサゴナルな業務APIに保持する。
- 確定・拒否は入口の固定ロジックで処理する。Guest UIの構造化承認操作からFront Deskが、会話ID・提案ID・サーバー保管の承認tokenを送る。自然文だけで確定しない。
- 会話IDと承認tokenはLLMが生成・選択する引数にしない。tokenはブラウザーや通常ログへ渡さない。
- ClockはAsia/Tokyo、候補順は距離・時刻、卓順は定員・IDで決める。提案は10分で期限切れとし、仮押さえはしない。
- 完全な業務契約と移行方針はdocs/agents/restaurant-reservation-contract.mdを参照する。

## 理由

会話による相談と、決定的な予約可否・確定判断を分離できる。既存ローカルモデルを利用して新たな外部サービスへの依存を避ける。

## 検討した代替案

- Front Deskのみで会話を処理する: Restaurantの相談能力を拡充するユーザー方針に合わない。
- LLMに確定toolも公開する: 生成結果だけで承認境界を越えられるため採用しない。
- 自然文承認を従来どおりLLMで分類して確定する: 誤分類による更新を避けるため構造化操作へ移行する。

## 影響・セキュリティ・運用

RestaurantにもOllama利用が必要となる。モデル停止時は失敗を返し確定しない。通常ログとUIの通信デバッグには承認tokenとゲスト照合情報を露出しない。ローカルの信頼されたFront Deskを前提とし、本番認証・認可は別設計とする。ADK Webは相談まで、確定にはGuest UIの構造化操作を使う。旧MVP経路は移行期間の専用互換経路として扱う。

## 参照

- ADK Function tools: https://adk.dev/tools-custom/function-tools/ （確認日: 2026-10-07）
- ADK LiteLLM: https://adk.dev/agents/models/litellm/ （確認日: 2026-10-07）
- ADK A2A公開: https://adk.dev/a2a/quickstart-exposing/ （確認日: 2026-10-07）
- ユーザー承認: 2026-10-07「LLM追加」。
