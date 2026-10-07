# A2A実装バージョン

3部署サービスはADK公式`to_a2a()`で公開し、Agent Cardは`/.well-known/agent-card.json`から取得する。

| 項目 | バージョン／設定 | 根拠 |
|---|---|---|
| Google ADK | `2.11.0` | [`uv.lock`](../../uv.lock) |
| A2A Python SDK | `1.2.2` | [`uv.lock`](../../uv.lock) |
| A2A Protocol | `1.0` | 3部署が返すAgent Cardの`supportedInterfaces[].protocolVersion` |
| Protocol binding | `JSONRPC` | 3部署が返すAgent Cardの`supportedInterfaces[].protocolBinding` |
| 公開方法 | ADK `to_a2a()` | [ADK公式A2A公開手順](https://adk.dev/a2a/quickstart-exposing/) |

`tests/test_a2a_contracts.py`は各Agent Cardの名前・能力説明・接続先・Protocol bindingを確認し、A2A SDKでTaskを送信して固定応答と完了状態を検証する。

ADKのPython A2A統合は公式資料上Experimental。Protocol自体とA2A SDKの安定性とは区別し、ADK更新時にはAgent CardとTaskの契約テストを実行する。
