# ADR 0001: PythonとGoogle ADKを採用する

- 状態: 承認済み
- 決定日: 2026-10-06

## 背景

本プロジェクトは、ホテル運営を題材にしたA2A Hub-Spokeデモである。複数の独立Agentを用意し、Front Desk Agentから部署Agentへの委譲、A2A Taskの進行、結果集約を学べる構成を目指す。

## 決定

- 実装言語にPython 3.13を採用する。
- Agentの実装にGoogle Agent Development Kit（ADK）を採用する。
- Python環境と依存関係の管理に`uv`を使う。
- ADKのA2A機能は`google-adk[a2a]` extraを使う。

## 理由

- ユーザーがPython ADKで開発する方針を決定した。
- ローカル環境にPython 3.13.14と`uv`があり、初期環境をすぐ構築できる。
- ADK公式ドキュメントにPythonでAgentをA2A公開・利用する手順がある。
- `uv`でPythonバージョンと依存バージョンを固定でき、複数Agentの開発環境を再現しやすい。

## 検討した代替案

- Go ADK: 選択可能だが、ユーザーのPython ADK方針に合わせて今回は採用しない。
- Java ADK: 選択可能だが、ユーザーのPython ADK方針に合わせて今回は採用しない。
- A2A SDKを直接利用し、ADKを使わない: 本プロジェクトでADKを使う方針のため採用しない。

## 影響

- 実行環境はPython 3.13に固定し、`uv.lock`を依存バージョンの基準とする。
- ADK本体とA2A extraの依存を導入する。
- A2Aの仕様バージョン、トランスポート、LLMプロバイダー、UI、永続化はこの決定には含めず、別途決める。
- Pythonの別マイナーバージョンへ変更する場合は、ADKの対応状況と依存関係を再確認する。

## セキュリティ上の影響

- ADKはAgent実行基盤として依存関係に加わる。バージョン更新時には公式リリースノートとセキュリティ情報を確認する。
- APIキーを使う場合は環境変数またはローカルの未追跡`.env`で管理し、ソースやログに含めない。

## 運用上の影響

- 開発者は`uv sync`で仮想環境とロック済み依存を再現する。
- `.venv`と`.env`はGit管理対象外とする。

## 参照した一次情報

- ADK公式A2Aガイド: <https://github.com/google/adk-docs/blob/main/docs/a2a/index.md>（2026-10-06確認）
- ADK公式Python A2A公開手順: <https://github.com/google/adk-docs/blob/main/docs/a2a/quickstart-exposing.md>（2026-10-06確認）
- ADK Python公式リポジトリ: <https://github.com/google/adk-python>（2026-10-06確認）
