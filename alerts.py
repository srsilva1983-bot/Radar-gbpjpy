"""Verificar oportunidades dos dois pares, alertar pelo Telegram e evitar repetidos."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import requests
import pandas as pd

from datafeed import get_candles, DataFeedError, SUPPORTED_PAIRS
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
        if not resp.json().get('ok'):
            raise RuntimeError('O Telegram recusou a mensagem; verifica bot e chat_id.')
    except requests.RequestException:
        # Não imprimir endereços que possam conter o token do Telegram.
        raise RuntimeError('Falha na comunicação com o Telegram.') from None


def read_state() -> set[str]:
    if STATE_PATH.exists():
        try:
            return set(json.loads(STATE_PATH.read_text(encoding='utf-8')).get('notified', []))
        except (OSError, ValueError, TypeError):
            pass
    return set()


def save_state(ids: set[str]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({'notified': sorted(ids)}, indent=2), encoding='utf-8')


def fresh_signals(key: str, symbol: str, now: pd.Timestamp, seen: set[str]):
    market = get_candles(key, '15min', 1500, symbol=symbol)
    closed = last_closed_candles(market)
    if len(closed) < 1000:
        print(f'{symbol}: sem velas fechadas suficientes; sem alertas.')
        return []
    frames = {
        15: calculate_signals(closed, minutes=15, symbol=symbol),
        30: calculate_signals(aggregate_30m(closed), minutes=30, symbol=symbol),
    }
    found = []
    for minutes, frame in frames.items():
        latest_close = frame.index[-1] + pd.Timedelta(minutes=minutes)
        if now - latest_close > pd.Timedelta(minutes=45):
            print(f'{symbol} {minutes}m: cotação atrasada; sem alertas.')
            continue
        for ts, row in frame.tail(4).iterrows():
            age = now - (ts + pd.Timedelta(minutes=minutes))
            if age < pd.Timedelta(0) or age > pd.Timedelta(minutes=45):
                continue
            if row.signal not in ('COMPRA', 'VENDA'):
                continue
            base = f'{minutes}m:{row.signal}:{ts.isoformat()}'
            ident = f'{symbol}:{base}'
            # Reconhecer identificadores usados pela versão antiga do GBP/JPY.
            if ident in seen or (symbol == 'GBP/JPY' and base in seen):
                continue
            found.append((ident, ts, row, minutes, symbol))
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--test-telegram', action='store_true', help='Envia um teste; não é sinal')
    args = parser.parse_args()
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat = os.getenv('TELEGRAM_CHAT_ID', '')
    if args.test_telegram:
        send_telegram(token, chat, '✅ Radar FX: Telegram configurado para GBP/JPY + EUR/USD (COMPRA/VENDA, 15m/30m). Isto não é um sinal.')
        print('Teste enviado para GBP/JPY e EUR/USD.')
        return 0

    key = os.getenv('TWELVE_DATA_API_KEY', '')
    now = pd.Timestamp(datetime.now(timezone.utc))
    seen = read_state()
    pending = []
    errors = []
    for symbol in SUPPORTED_PAIRS:
        try:
            pending.extend(fresh_signals(key, symbol, now, seen))
        except (DataFeedError, ValueError, IndexError) as exc:
            print(f'Erro de dados em {symbol}: {exc}')
            errors.append(symbol)

    pending.sort(key=lambda x: (x[1] + pd.Timedelta(minutes=x[3]), x[4], x[3]))
    for ident, ts, row, minutes, symbol in pending:
        send_telegram(token, chat, telegram_message(ts, row, minutes=minutes, symbol=symbol))
        seen.add(ident)
        save_state(seen)
        print(f'Enviado: {ident}')
    if not pending:
        print('Sem novos sinais de compra/venda para GBP/JPY ou EUR/USD.')
    # Permitir que um par continue a alertar mesmo que a API falhe no outro.
    # Se ambos falharem, marcar a execução como erro para diagnóstico no GitHub.
    return 1 if len(errors) == len(SUPPORTED_PAIRS) else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (DataFeedError, ValueError, RuntimeError) as exc:
        print(f'Erro: {exc}')
        raise SystemExit(1)
