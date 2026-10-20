"""Dados da Twelve Data para GBP/JPY e EUR/USD, sem expor credenciais."""
from __future__ import annotations
import requests
import pandas as pd

ENDPOINT = 'https://api.twelvedata.com/time_series'
SUPPORTED_PAIRS = ('GBP/JPY', 'EUR/USD')


class DataFeedError(RuntimeError):
    """Falha ou resposta inválida do fornecedor de cotações."""


def get_candles(api_key: str, interval: str = '15min', outputsize: int = 1500,
                symbol: str = 'GBP/JPY') -> pd.DataFrame:
    if not api_key or not api_key.strip():
        raise DataFeedError('Falta a chave TWELVE_DATA_API_KEY.')
    if interval not in {'5min', '15min'}:
        raise ValueError('Intervalo não suportado.')
    if symbol not in SUPPORTED_PAIRS:
        raise ValueError('Par de moedas não suportado.')
    try:
        result = requests.get(
            ENDPOINT,
            params={
                'symbol': symbol, 'interval': interval, 'outputsize': outputsize,
                'timezone': 'UTC', 'format': 'JSON', 'apikey': api_key.strip(),
            },
            timeout=25,
        )
        result.raise_for_status()
        payload = result.json()
    except (requests.RequestException, ValueError) as exc:
        raise DataFeedError(f'{symbol}: não foi possível contactar a Twelve Data.') from exc
    if not isinstance(payload, dict) or payload.get('status') == 'error' or 'values' not in payload:
        reason = payload.get('message', 'Resposta sem velas disponíveis.') if isinstance(payload, dict) else 'Resposta inesperada.'
        raise DataFeedError(f'Twelve Data ({symbol}): {reason}')
    frame = pd.DataFrame(payload['values'])
    needed = {'datetime', 'open', 'high', 'low', 'close'}
    if frame.empty or not needed.issubset(frame.columns):
        raise DataFeedError(f'{symbol}: resposta sem velas OHLC válidas.')
    try:
        frame['datetime'] = pd.to_datetime(frame['datetime'], utc=True)
        for col in ('open', 'high', 'low', 'close'):
            frame[col] = pd.to_numeric(frame[col], errors='raise')
    except (TypeError, ValueError) as exc:
        raise DataFeedError(f'{symbol}: formato de dados inválido.') from exc
    return (frame.drop_duplicates(subset='datetime')
                 .set_index('datetime')
                 .sort_index()[['open', 'high', 'low', 'close']])
