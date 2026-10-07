# ADR 0004: ゲスト画面で公開A2A状態を表示する

- Status: Accepted
- Date: 2026-10-07

## 背景

ゲスト向け専用UIで部署Agentの担当能力、A2A Taskの状態、各部署の結果を確認できるようにする。Agent間の独立性を保つため、UIは部署Agentの内部実装やメモリに依存せず、公開Agent CardとFront Deskが受信したA2A応答だけを使う。

## 決定

- UIサーバーは設定済みの各部署Agentの`.well-known` Agent Cardを取得し、`name`、`description`、`skills`だけを画面へ返す。
- Front Deskセッションイベントから、A2AのTask ID、Task状態、イベント時刻、表示用応答だけを抽出してTaskタイムラインに返す。
- `request`メタデータ、生のA2A payload、Agent内部推論、プロンプト、セッションstateはブラウザーへ公開しない。
- 受信した状態だけを時系列表示する。A2A応答に途中状態が含まれない場合、未受信の「受付済み」「対応中」を作らない。
- 一部のAgentが失敗した場合は、失敗状態と失敗していないAgentの結果を同時に残す。
- Agent Cardを取得できない場合は、そのAgentを未接続として表示する。TaskがまだないAgentは「今回の依頼なし」とする。

## 理由

Agent CardはAgentの能力を発見するための公開情報であり、Taskは状態と一意なIDを持つ作業単位である。A2A Taskの状態・ID・時刻を使えば、部署Agentの内部実装を知ることなく連携状況を示せる。A2Aの公開応答に含まれない進捗をUIが補完すると、実際に観測していない状態をゲストへ事実として伝えてしまう。

## 影響

- 起動中Agentの能力を実際のAgent Cardから表示でき、停止中のAgentも区別できる。
- 同期応答しか返らない場合、表示できるTask状態は受信した完了・失敗などに限られる。処理中の細かな変化は表示されない。
- Agent Card取得に失敗したAgentへは短いタイムアウトで未接続を返し、ゲストの会話APIをブロックしない。
- UI APIは公開フィールドを絞り、Agent CardとTask payload全体をそのままブラウザーへ渡さない。

## 検討した代替案

- **固定の部署説明を画面に埋め込む:** Agent Cardの実際の能力とずれる可能性があるため採用しない。
- **Agent内部ログやメモリから進捗を作る:** A2Aのサービス境界を越えて内部状態へ依存するため採用しない。
- **未受信の状態を受付・処理中として補完する:** 表示のために観測していないプロトコル状態を捏造することになるため採用しない。

## 参考資料

- A2A Protocol, Agent Skills & Agent Card: https://a2a-protocol.org/v1.0.1/tutorials/python/3-agent-skills-and-card/ （確認日: 2026-10-07）
- A2A Protocol, Specification — Task / TaskStatus / TaskState: https://a2a-protocol.org/v1.0.1/specification/ （確認日: 2026-10-07）
- Google ADK Python, Remote A2A Agent event metadata: https://github.com/google/adk-python/blob/main/src/google/adk/a2a/agent/_remote_a2a_agent.py （確認日: 2026-10-07）
