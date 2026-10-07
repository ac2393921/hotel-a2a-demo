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
