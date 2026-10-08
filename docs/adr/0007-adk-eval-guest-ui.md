# ADR 0007: Guest UIの公開入口を通すADK予約相談評価

- 状態: 採用
- 決定日: 2026-10-08
- 関連: Task #57、ADR 0005、ADR 0006

## 背景

ユーザーはTask #57の検証を`adk eval`の評価で担保する方針を指定した。予約確定は自然文でなくGuest UIの構造化操作を必要とし、会話評価からRestaurant内部のRepositoryや承認資格を直接操作すると既存の境界を崩してしまう。

## 決定

`evals/guest_ui_agent`を評価専用ADK BaseAgentとする。評価入力は架空ゲストの発話、画面での承認／拒否、二会話の操作順を表す。アダプターはブラウザーと同じGuest UI HTTP入口を呼び出し、実Front Desk、公開A2A、実Restaurantを通す。提案IDはHTTP応答から取得する。内部tool、store、承認tokenには依存しない。製品のAgent構成・承認境界を変更しない。

評価指標`reservation_contract`はADK公式のcustom metricsで登録する。ケースの各ターンで必須の条件、禁止する確定表現、承認待ち提案の有無、公開A2A Taskの受信を評価し、すべてのターンが通った場合だけ1、それ以外は0とする。閾値は1.0。可変IDとTask IDの一致は要求しない。judgeモデルは利用せず、Ollama以外のモデル利用・API費用を追加しない。

ケースごとに評価専用8800/8803ポートのGuest UIとRestaurantを起動・停止して状態を初期化する。既存デモは再利用しない。基準日はAsia/Tokyoの実行開始日を記録し、データセットの日付プレースホルダーを同じ基準日で置換する。製品Clockは実時刻のままなので、日付をまたぐ実行は結果を有効と扱わず、両サービスを再起動して新しい結果を記録する。

ADK公式eval extraを任意依存`evaluation`としてロックする。`adk eval`の終了コードだけに依存せず、保存されたADK JSONレポートの各ケースの合否を確認する。1実行につき各ケース1回、失敗を自動再試行しない。

## 理由

正規の承認経路と会話を同じ評価ケースで検証できる。条件付きの応答評価は動的IDや言い回しの全面一致より適切で、外部judgeの設定も不要となる。ケース間の再起動で状態汚染を防ぐ。

## 検討した代替案

- Front Deskを直接`adk eval`へ渡す: 構造化承認をGuest UIと同じ入口で実行できないため、今回の四シナリオ全体の評価には採用しない。
- 自然文の承認で確定する: ADR 0006の承認境界に反するため採用しない。
- LLM judgeのみで評価する: 予約状態・原子性の証明にはならず、judgeモデルも未決のため採用しない。
- HTTPスクリプトだけで評価する: ユーザーが指定したADKの評価データ・設定・レポート管理を満たさない。

## 影響・セキュリティ・運用

評価はHTTPで見える応答と提案状態を扱う。Restaurant内部toolのtrajectoryを評価済みと主張しない。公開A2A委譲は既存の契約・統合テストとGuest UIデバッグ表示で補完する。原子性・同時確定・元予約維持は業務テスト、実画面のクリックと表示は画面検証で補完する。

評価ログは架空データだけを扱い、Git管理外の`.adk/`に保存する。応答に`approval_token`が含まれた場合は生応答を保存せず失敗する。評価先はローカルHTTPだけに制限する。eval extraによりLiteLLM・protobufなどの互換バージョンが変わるため、既存テストと実Ollamaを再検証する。

## 一次情報

以下を2026-10-08に確認し、ロックされたgoogle-adk 2.11.0の`eval_case.py`、`custom_metric_evaluator.py`、`evaluator.py`、`cli_tools_click.py`とも照合した。

- ADK CLI評価: https://adk.dev/evaluate/#run-evaluations-via-the-cli
- ADK custom metrics: https://adk.dev/evaluate/custom_metrics/
- ADK公式実装: https://github.com/google/adk-python/tree/v2.11.0/src/google/adk/evaluation
