"""Guest UIのHTTP境界から、実LLM/A2A経由の四つの予約シナリオを検証する。"""
import argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx


class Guest:
    def __init__(self, client):
        self.client = client
        response = client.post('/api/sessions')
        response.raise_for_status()
        self.id = response.json()['session_id']

    def send(self, text, **fields):
        response = self.client.post(f'/api/sessions/{self.id}/messages', json={'text': text, **fields})
        response.raise_for_status()
        result = response.json()
        assert 'approval_token' not in response.text, '承認資格がブラウザー応答に露出しています'
        print(result.get('reply', ''), flush=True)
        return result

    def propose(self, text):
        result = self.send(text)
        # 検索で止まった場合も、同じ条件をゲストが選ぶ会話を再現する。
        if not result.get('pending_proposal'):
            result = self.send('次の条件を選びます。予約は確定せず、予約案を作ってください。' + text)
        assert result.get('pending_proposal'), '予約案が作成されませんでした。LLM応答を確認してください'
        assert 'まだ予約は確定していません' in result['pending_proposal']['text']
        return result['pending_proposal']

    def approve(self, proposal):
        return self.send('表示された予約案を承認します。', decision='approve', proposal_id=proposal['proposal_id'])


def confirmed(result):
    assert '予約を確定しました' in result['reply']
    assert result.get('pending_proposal') is None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    tomorrow = (datetime.now(ZoneInfo('Asia/Tokyo')) + timedelta(days=1)).date().isoformat()
    race_day = (datetime.now(ZoneInfo('Asia/Tokyo')) + timedelta(days=2)).date().isoformat()
    with httpx.Client(base_url=args.url, timeout=240) as client:
        print('[1/4] 新規予約と自然文承認の非更新', flush=True)
        new = Guest(client)
        p = new.propose(f'{tomorrow}の18:00、2名、通常テーブルを新規予約したいです。101号室のデモ花子です。窓際希望です。')
        assert '窓際は希望' in p['text'] and '確約できません' in p['text']
        natural = new.send('はい、承認します。')
        assert natural.get('pending_proposal', {}).get('proposal_id') == p['proposal_id']
        confirmed(new.approve(p))

        print('[2/4] 個室満席から同じ席種の代替を選択', flush=True)
        full = Guest(client)
        search = full.send(f'{tomorrow}の19:00、4名、個室の空席を調べてください。')
        assert '満席' in search['reply'] and '20:00' in search['reply']
        p = full.propose(f'代替の{tomorrow}20:00を選びます。4名、個室、101号室のデモ花子です。窓際希望なしで新規予約案を作ってください。')
        confirmed(full.approve(p))

        print('[3/4] 複数予約から変更対象を明示して変更', flush=True)
        change = Guest(client)
        found = change.send('101号室のデモ花子です。既存のレストラン予約を照合してください。')
        assert 'demo-dinner' in found['reply'] and 'demo-lunch' in found['reply']
        p = change.propose(f'変更対象は予約ID demo-dinner、{tomorrow}19:00の予約です。{tomorrow}20:30、4名、通常テーブルに変更する予約案を作ってください。101号室のデモ花子です。窓際希望なしです。')
        confirmed(change.approve(p))

        print('[4/4] 二つの提案後に先に別ゲストが確定し、変更は競合', flush=True)
        other = Guest(client)
        first = other.propose(f'{race_day}20:30、4名、個室を新規予約したいです。202号室の架空太郎です。窓際希望なしです。')
        original = Guest(client)
        found = original.send('101号室のデモ花子です。レストランの既存予約を照合してください。')
        assert 'demo-dinner' in found['reply']
        second = original.propose(f'予約ID demo-dinner、{tomorrow}20:30の通常テーブルを、{race_day}20:00、4名、個室に変更する案を作ってください。101号室のデモ花子です。窓際希望なしです。')
        confirmed(other.approve(first))
        conflict = original.approve(second)
        assert '承認時点で満席' in conflict['reply'] and '予約を確定しました' not in conflict['reply']
        assert conflict.get('pending_proposal') is None
        assert '候補:' in conflict['reply']
        preserved = original.send('101号室のデモ花子です。既存のレストラン予約を再照合してください。')
        assert 'demo-dinner' in preserved['reply'] and tomorrow in preserved['reply'] and '20:30' in preserved['reply']
        replacement = original.propose(f'競合後の代替として{race_day}19:00、4名、個室を選びます。予約ID demo-dinnerを変更する案を作ってください。101号室のデモ花子、窓際希望なしです。')
        confirmed(original.approve(replacement))
    print('四つのHTTPシナリオが成功しました。画面の表示・クリックは別途確認してください。', flush=True)


if __name__ == '__main__':
    main()
