"""Fonte Twelve Data. Não registar nem expor tokens no histórico ou interface."""
from __future__ import annotations
import requests
import pandas as pd

ENDPOINT = 'https://api.twelvedata.com/time_series'


class DataFeedError(RuntimeError):
    """Resposta indisponível ou inválida do fornecedor de cotações."""


def get_candles(api_key: str, interval: str = '15min', outputsize: int = 1500) -> pd.DataFrame:
    if not api_key or not api_key.strip():
        raise DataFeedError('Falta a chave gratuita da Twelve Data (TWELVE_DATA_API_KEY).')
    if interval not in {'5min', '15min'}:
        raise ValueError('Intervalo não suportado.')
    try:
        result = requests.get(
            ENDPOINT,
            params={
                'symbol': 'GBP/JPY', 'interval': interval, 'outputsize': outputsize,
                'timezone': 'UTC', 'format': 'JSON', 'apikey': api_key.strip(),
            },
            timeout=25,
        )
        result.raise_for_status()
        payload = result.json()
    except (requests.RequestException, ValueError) as exc:
        raise DataFeedError('Não foi possível contactar a Twelve Data.') from exc

    if not isinstance(payload, dict) or payload.get('status') == 'error' or 'values' not in payload:
        reason = payload.get('message', 'Resposta sem velas disponíveis.') if isinstance(payload, dict) else 'Resposta inesperada.'
        raise DataFeedError(f'Twelve Data: {reason}')

    frame = pd.DataFrame(payload['values'])
    needed = {'datetime', 'open', 'high', 'low', 'close'}
    if frame.empty or not needed.issubset(frame.columns):
        raise DataFeedError('O fornecedor não devolveu velas OHLC válidas.')
    try:
        frame['datetime'] = pd.to_datetime(frame['datetime'], utc=True)
        for col in ('open', 'high', 'low', 'close'):
            frame[col] = pd.to_numeric(frame[col], errors='raise')
    except (TypeError, ValueError) as exc:
        raise DataFeedError('Os dados recebidos não têm um formato válido.') from exc
    frame = (frame.drop_duplicates(subset='datetime')
                  .set_index('datetime')
                  .sort_index()[['open', 'high', 'low', 'close']])
    return frame
