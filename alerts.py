"""Radar FX: sinais GBP/JPY + EUR/USD, resumo periódico e Telegram.

O resumo é enviado de 4 em 4 horas de funcionamento do workflow, mesmo
sem sinais, e usa os mesmos dados de mercado das verificações normais.
O ficheiro de estado existente guarda o último resumo para evitar repetições.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import pandas as pd
import requests

from datafeed import DataFeedError, SUPPORTED_PAIRS, get_candles
from strategy import (
    aggregate_30m,
    calculate_signals,
    fmt_price,
    format_lisbon,
    last_closed_candles,
    telegram_message,
)

STATE_PATH = Path('.state/last_signals.json')
SUMMARY_PERIOD = timedelta(hours=4)
MAX_CANDLE_AGE = timedelta(minutes=45)


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
        # Evitar expor o token, incluído no endereço do pedido.
        raise RuntimeError('Falha na comunicação com o Telegram.') from None


def read_state_document() -> dict:
    if STATE_PATH.exists():
        try:
            document = json.loads(STATE_PATH.read_text(encoding='utf-8'))
            if isinstance(document, dict):
                return document
        except (OSError, ValueError, TypeError):
            pass
    return {'notified': []}


def read_state() -> set[str]:
    previous = read_state_document().get('notified', [])
    if not isinstance(previous, list):
        return set()
    return {item for item in previous if isinstance(item, str)}


def read_last_summary() -> datetime | None:
    saved = read_state_document().get('last_summary_utc')
    if not isinstance(saved, str):
        return None
    try:
        parsed = datetime.fromisoformat(saved.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def save_state(ids: set[str], *, last_summary: datetime | None = None) -> None:
    # Preservar os sinais e outros campos já guardados no repositório.
    document = read_state_document()
    document['notified'] = sorted(ids)
    if last_summary is not None:
        document['last_summary_utc'] = last_summary.astimezone(timezone.utc).isoformat()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Escrita atómica para que uma interrupção não trunque o estado.
    temporary_path = STATE_PATH.with_name(STATE_PATH.name + '.tmp')
    temporary_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary_path.replace(STATE_PATH)


def candle_momentum(row: pd.Series) -> str:
    """Estado técnico descritivo, não previsão ou ordem de negociação."""
    if pd.isna(row.ema20) or pd.isna(row.ema50) or pd.isna(row.macd_hist):
        return 'indefinido'
    if row.close > row.ema20 > row.ema50 and row.macd_hist > 0:
        return 'comprador'
    if row.close < row.ema20 < row.ema50 and row.macd_hist < 0:
        return 'vendedor'
    return 'misto'


def summary_section(symbol: str, frames: dict[int, pd.DataFrame]) -> str:
    if 15 not in frames or 30 not in frames:
        return f'{symbol}\n⚠️ Sem cotações recentes completas; estado técnico indisponível.'
    fifteen = frames[15].iloc[-1]
    thirty = frames[30].iloc[-1]
    closed_at = frames[15].index[-1] + timedelta(minutes=15)
    return (
        f'{symbol} | {fmt_price(fifteen.close, symbol)}\n'
        f'Tendência 1h: {fifteen.trend}\n'
        f'15m: {candle_momentum(fifteen)} | 30m: {candle_momentum(thirty)}\n'
        f'RSI: 15m {fifteen.rsi:.1f} | 30m {thirty.rsi:.1f}\n'
        f'Última vela 15m (Lisboa): {format_lisbon(closed_at)}'
    )


def summary_message(sections: dict[str, str], now: datetime) -> str:
    when = format_lisbon(pd.Timestamp(now))
    blocks = [sections.get(symbol, f'{symbol}\n⚠️ Dados indisponíveis; consulta os registos no GitHub.')
              for symbol in SUPPORTED_PAIRS]
    return (
        f'📊 RADAR FX — RESUMO PERIÓDICO (4h)\n{when}\n\n'
        + '\n\n'.join(blocks)
        + '\n\nℹ️ Resumo técnico, não é sinal de entrada. '
          'Os alertas COMPRA/VENDA continuam separados quando existem condições.'
    )


def fresh_signals(key: str, symbol: str, now: pd.Timestamp, seen: set[str]):
    """Retorna alertas ainda não enviados e estado técnico atual do par."""
    market = get_candles(key, '15min', 1500, symbol=symbol)
    closed = last_closed_candles(market)
    if len(closed) < 1000:
        print(f'{symbol}: velas fechadas insuficientes para a análise.')
        return [], None
    frames = {
        15: calculate_signals(closed, minutes=15, symbol=symbol),
        30: calculate_signals(aggregate_30m(closed), minutes=30, symbol=symbol),
    }
    found = []
    fresh_frames: dict[int, pd.DataFrame] = {}
    for minutes, frame in frames.items():
        latest_close = frame.index[-1] + timedelta(minutes=minutes)
        if now - latest_close > MAX_CANDLE_AGE or now < latest_close:
            print(f'{symbol} {minutes}m: velas atrasadas; sem alertas neste intervalo.')
            continue
        fresh_frames[minutes] = frame
        print(f'{symbol} {minutes}m: dados válidos; última vela {latest_close.isoformat()}.')
        for ts, row in frame.tail(4).iterrows():
            age = now - (ts + timedelta(minutes=minutes))
            if age < timedelta(0) or age > MAX_CANDLE_AGE:
                continue
            if row.signal not in ('COMPRA', 'VENDA'):
                continue
            base = f'{minutes}m:{row.signal}:{ts.isoformat()}'
            ident = f'{symbol}:{base}'
            # Aceitar também identificadores antigos do GBP/JPY, sem prefixo.
            if ident in seen or (symbol == 'GBP/JPY' and base in seen):
                continue
            found.append((ident, ts, row, minutes, symbol))
    return found, (summary_section(symbol, fresh_frames) if fresh_frames else None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--test-telegram', action='store_true', help='Envia um teste; não é sinal')
    args = parser.parse_args()
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat = os.getenv('TELEGRAM_CHAT_ID', '')
    if args.test_telegram:
        send_telegram(token, chat,
                      '✅ Radar FX: Telegram configurado para GBP/JPY + EUR/USD '
                      '(COMPRA/VENDA, 15m/30m). Resumo periódico: 4 horas. Isto não é um sinal.')
        print('Teste enviado. Não foram consultadas cotações no modo de teste.')
        return 0

    key = os.getenv('TWELVE_DATA_API_KEY', '')
    now = pd.Timestamp(datetime.now(timezone.utc))
    seen = read_state()
    pending = []
    sections: dict[str, str] = {}
    errors = []

    for symbol in SUPPORTED_PAIRS:
        try:
            new_signals, report = fresh_signals(key, symbol, now, seen)
            pending.extend(new_signals)
            if report:
                sections[symbol] = report
        except (DataFeedError, ValueError, IndexError, KeyError) as exc:
            print(f'Erro de dados em {symbol}: {exc}')
            errors.append(symbol)

    pending.sort(key=lambda x: (x[1] + timedelta(minutes=x[3]), x[4], x[3]))
    for ident, ts, row, minutes, symbol in pending:
        send_telegram(token, chat, telegram_message(ts, row, minutes=minutes, symbol=symbol))
        seen.add(ident)
        save_state(seen)
        print(f'Enviado: {ident}')
    if not pending:
        print('Sem novos sinais de compra/venda para GBP/JPY ou EUR/USD.')

    previous_summary = read_last_summary()
    due = (previous_summary is None or now.to_pydatetime() - previous_summary >= SUMMARY_PERIOD)
    if due and sections:
        send_telegram(token, chat, summary_message(sections, now.to_pydatetime()))
        save_state(seen, last_summary=now.to_pydatetime())
        print('Resumo periódico enviado ao Telegram e horário guardado no estado.')
    elif due:
        print('Resumo não enviado: não há dados recentes válidos para qualquer dos pares.')
    else:
        print('Resumo ainda não devido; mantém-se o último envio guardado no estado.')

    # Se ambos os fornecedores falharem, a execução fica vermelha para diagnóstico.
    # Se apenas um falhar, o outro mantém alertas e resumo.
    return 1 if len(errors) == len(SUPPORTED_PAIRS) else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (DataFeedError, ValueError, RuntimeError) as exc:
        print(f'Erro: {exc}')
        raise SystemExit(1)
