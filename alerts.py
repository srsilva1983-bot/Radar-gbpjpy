"""Verificação agendada, deduplicação por vela e envio Telegram."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import requests
import pandas as pd
from datafeed import get_candles, DataFeedError
from strategy import aggregate_30m, calculate_signals, last_closed_candles, telegram_message

STATE_PATH = Path('.state/last_signals.json')


def send_telegram(token: str, chat_id: str, message: str) -> None:
    if not token or not chat_id:
        raise RuntimeError('Configura TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nos Secrets.')
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': message, 'disable_web_page_preview': True},
            timeout=20,
        )
        resp.raise_for_status()
        body = resp.json()
        if not body.get('ok'):
            raise RuntimeError('Telegram recusou a mensagem. Verifica bot e chat_id.')
    except requests.RequestException as exc:
        # Não imprimir URL/token de pedidos que falhem.
        raise RuntimeError('Falha na comunicação com o Telegram.') from None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--test-telegram', action='store_true', help='Envia uma mensagem de teste')
    args = parser.parse_args()
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat = os.getenv('TELEGRAM_CHAT_ID', '')

    if args.test_telegram:
        send_telegram(token, chat, '✅ Teste GBP/JPY: avisos Telegram configurados. Não é um sinal de trading.')
        print('Teste enviado.')
        return 0

    secret = os.getenv('TWELVE_DATA_API_KEY', '')
    market = get_candles(secret, '15min', 1500)
    closed = last_closed_candles(market)
    if len(closed) < 1000:
        print('Ainda não existem velas fechadas suficientes; não enviámos alertas.')
        return 0
    frames = {
        15: calculate_signals(closed, minutes=15),
        30: calculate_signals(aggregate_30m(closed), minutes=30),
    }
    now = pd.Timestamp(datetime.now(timezone.utc))

    old = {'notified': []}
    if STATE_PATH.exists():
        try:
            old = json.loads(STATE_PATH.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
    old_ids = set(old.get('notified', []))

    # Monitoriza as duas escalas; recupera até 45 minutos de sinais ainda recentes.
    # A chave inclui timeframe para evitar confusões entre alertas 15m e 30m.
    new_signals = []
    for minutes, frame in frames.items():
        latest_close = frame.index[-1] + pd.Timedelta(minutes=minutes)
        if now - latest_close > pd.Timedelta(minutes=45):
            print(f'{minutes}m: dados atrasados; sem alertas neste intervalo.')
            continue
        for ts, row in frame.tail(4).iterrows():
            candle_close = ts + pd.Timedelta(minutes=minutes)
            age = now - candle_close
            if age < pd.Timedelta(0) or age > pd.Timedelta(minutes=45):
                continue
            if row.signal not in ('COMPRA', 'VENDA'):
                continue
            ident = f'{minutes}m:{row.signal}:{ts.isoformat()}'
            if ident not in old_ids:
                new_signals.append((ident, ts, row, minutes))

    new_signals.sort(key=lambda item: (item[1] + pd.Timedelta(minutes=item[3]), item[3]))
    for ident, ts, row, minutes in new_signals:
        send_telegram(token, chat, telegram_message(ts, row, minutes=minutes))
        old_ids.add(ident)
        # Persistir após cada envio para reduzir repetição em caso de falha posterior.
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({'notified': sorted(old_ids)[-200:]}, indent=2), encoding='utf-8')
        print(f'Enviado: {ident}')

    if not new_signals:
        print('Sem novos sinais de 15m ou 30m. Nenhuma mensagem enviada.')
    return 0

    old = {'notified': []}
    if STATE_PATH.exists():
        try:
            old = json.loads(STATE_PATH.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
    old_ids = set(old.get('notified', []))

    # Processa até três velas recentemente fechadas: tolera atrasos de execução.
    fresh = frame.tail(3)
    new_signals = []
    for ts, row in fresh.iterrows():
        candle_close = ts + pd.Timedelta(minutes=15)
        if now - candle_close > pd.Timedelta(minutes=45):
            continue
        if row.signal not in ('COMPRA', 'VENDA'):
            continue
        ident = f'{row.signal}:{ts.isoformat()}'
        if ident not in old_ids:
            new_signals.append((ident, ts, row))

    for ident, ts, row in new_signals:
        send_telegram(token, chat, telegram_message(ts, row))
        old_ids.add(ident)
        print(f'Enviado: {ident}')

    if new_signals:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({'notified': sorted(old_ids)[-160:]}, indent=2), encoding='utf-8')
    else:
        print('Sem novos sinais. Nenhuma mensagem enviada.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (DataFeedError, ValueError, RuntimeError) as exc:
        print(f'Erro: {exc}')
        raise SystemExit(1)
