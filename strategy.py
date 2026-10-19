"""Indicadores e oportunidades técnicas sem execução de operações.

Velas com timestamps UTC no INÍCIO do intervalo. Apenas velas fechadas.
As médias de 1 hora só ficam visíveis nos candles de 15m/30m após fecharem.
"""
from __future__ import annotations
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

LISBON = ZoneInfo('Europe/Lisbon')
PIP = 0.01  # GBP/JPY: 1 pip = 0,01 JPY


def last_closed_candles(ohlc: pd.DataFrame, minutes: int = 15, now=None) -> pd.DataFrame:
    """Remove a vela ainda aberta; reserva 60s para atraso de publicação."""
    ts = pd.Timestamp(now or datetime.now(timezone.utc))
    if ts.tzinfo is None:
        ts = ts.tz_localize('UTC')
    else:
        ts = ts.tz_convert('UTC')
    return ohlc.loc[ohlc.index + pd.Timedelta(minutes=minutes, seconds=60) <= ts].copy()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi_wilder(close: pd.Series, n: int = 14) -> pd.Series:
    diff = close.diff()
    gains = diff.clip(lower=0)
    losses = (-diff).clip(lower=0)
    av_gain = gains.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    av_loss = losses.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    result = 100 - 100 / (1 + av_gain / av_loss.replace(0, np.nan))
    result = result.mask((av_gain > 0) & (av_loss == 0), 100.)
    result = result.mask((av_gain == 0) & (av_loss == 0), 50.)
    return result


def atr_wilder(data: pd.DataFrame, n: int = 14) -> pd.Series:
    previous = data.close.shift(1)
    true_range = pd.concat([
        data.high - data.low,
        (data.high - previous).abs(),
        (data.low - previous).abs(),
    ], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def aggregate_30m(source: pd.DataFrame) -> pd.DataFrame:
    """Agrega velas FECHADAS de 15m para velas COMPLETAS de 30m, sem lookahead."""
    if source.index.tz is None:
        raise ValueError('O índice OHLC tem de ter fuso horário UTC.')
    src = source[['open', 'high', 'low', 'close']].copy().sort_index().tz_convert('UTC')
    resampler = src.resample('30min', label='left', closed='left')
    count = resampler['close'].count()
    bars = resampler.agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'})
    return bars.loc[count == 2].copy()


def calculate_signals(source: pd.DataFrame, minutes: int = 15) -> pd.DataFrame:
    """Sinais de 15m ou 30m com confirmação de 1h apenas após fecho da hora."""
    if minutes not in (15, 30):
        raise ValueError('Os sinais usam velas de 15 ou 30 minutos.')
    min_bars = 1000 if minutes == 15 else 500
    if len(source) < min_bars:
        raise ValueError(f'São necessárias pelo menos {min_bars} velas de {minutes} minutos para a EMA200 de 1 hora.')
    d = source[['open', 'high', 'low', 'close']].copy().sort_index()
    if d.index.tz is None:
        raise ValueError('O índice OHLC tem de ter fuso horário UTC.')
    d = d.tz_convert('UTC')

    d['ema20'] = ema(d.close, 20)
    d['ema50'] = ema(d.close, 50)
    d['rsi'] = rsi_wilder(d.close)
    d['atr'] = atr_wilder(d)
    macd = ema(d.close, 12) - ema(d.close, 26)
    d['macd'] = macd
    d['macd_signal'] = ema(macd, 9)
    d['macd_hist'] = d.macd - d.macd_signal

    h = d[['open', 'high', 'low', 'close']].resample('1h', label='left', closed='left').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last',
    })
    # Excluir horas incompletas (4 velas de 15m ou 2 velas de 30m).
    count = d.close.resample('1h', label='left', closed='left').count()
    h = h.loc[count == 60 // minutes].copy()
    h['h_ema50'] = ema(h.close, 50)
    h['h_ema200'] = ema(h.close, 200)
    h['h_ema50_prev'] = h.h_ema50.shift(1)
    h = h[['h_ema50', 'h_ema200', 'h_ema50_prev']]
    # A hora de 14:00-15:00 só fica disponível às 15:00 UTC.
    h.index = h.index + pd.Timedelta(hours=1)
    h.index.name = 'available_at'
    timestamps_close = pd.DataFrame({'closed_at': d.index + pd.Timedelta(minutes=minutes)}, index=d.index)
    hourly_context = pd.merge_asof(
        timestamps_close[['closed_at']].sort_values('closed_at'),
        h.reset_index().sort_values('available_at'),
        left_on='closed_at', right_on='available_at', direction='backward'
    )
    for col in ('h_ema50', 'h_ema200', 'h_ema50_prev'):
        d[col] = hourly_context[col].to_numpy()

    d['trend'] = 'NEUTRA'
    rising = (d.h_ema50 > d.h_ema200) & (d.h_ema50 > d.h_ema50_prev)
    falling = (d.h_ema50 < d.h_ema200) & (d.h_ema50 < d.h_ema50_prev)
    d.loc[rising, 'trend'] = 'ALTA'
    d.loc[falling, 'trend'] = 'BAIXA'

    cross_macd_up = (d.macd > d.macd_signal) & (d.macd.shift(1) <= d.macd_signal.shift(1))
    cross_macd_down = (d.macd < d.macd_signal) & (d.macd.shift(1) >= d.macd_signal.shift(1))
    cross_ema_up = (d.close > d.ema20) & (d.close.shift(1) <= d.ema20.shift(1))
    cross_ema_down = (d.close < d.ema20) & (d.close.shift(1) >= d.ema20.shift(1))
    prior_high = d.high.shift(1).rolling(12, min_periods=12).max()
    prior_low = d.low.shift(1).rolling(12, min_periods=12).min()
    breakout_up = (d.close > prior_high) & (d.close.shift(1) <= prior_high.shift(1))
    breakout_down = (d.close < prior_low) & (d.close.shift(1) >= prior_low.shift(1))

    momentum_up = (d.macd_hist > 0) & (d.macd_hist > d.macd_hist.shift(1))
    momentum_down = (d.macd_hist < 0) & (d.macd_hist < d.macd_hist.shift(1))
    buy_trigger = cross_macd_up | (cross_ema_up & momentum_up) | (breakout_up & momentum_up)
    sell_trigger = cross_macd_down | (cross_ema_down & momentum_down) | (breakout_down & momentum_down)
    bullish = (
        rising & (d.ema20 > d.ema50) & (d.close > d.ema20)
        & d.rsi.between(52, 72, inclusive='both') & buy_trigger
        & (d.atr > 0)
    )
    bearish = (
        falling & (d.ema20 < d.ema50) & (d.close < d.ema20)
        & d.rsi.between(28, 48, inclusive='both') & sell_trigger
        & (d.atr > 0)
    )
    d['signal'] = 'AGUARDAR'
    d.loc[bullish, 'signal'] = 'COMPRA'
    d.loc[bearish, 'signal'] = 'VENDA'

    # Stops e alvos de referência baseados em ATR; spread e slippage excluídos.
    d['stop_pips'] = (1.8 * d.atr / PIP).clip(lower=12)
    d['stop_distance'] = d.stop_pips * PIP
    d['entry'] = d.close
    d['stop'] = np.where(bullish, d.close - d.stop_distance,
                        np.where(bearish, d.close + d.stop_distance, np.nan))
    d['target1'] = np.where(bullish, d.close + 1.5 * d.stop_distance,
                           np.where(bearish, d.close - 1.5 * d.stop_distance, np.nan))
    d['target2'] = np.where(bullish, d.close + 2.0 * d.stop_distance,
                           np.where(bearish, d.close - 2.0 * d.stop_distance, np.nan))
    return d


def recent_opportunities(d: pd.DataFrame, *, lookback_bars: int = 80) -> pd.DataFrame:
    return d[d.signal.ne('AGUARDAR')].tail(lookback_bars).copy()


def fmt_price(number: float) -> str:
    return f'{float(number):.3f}'


def format_lisbon(index: pd.Timestamp) -> str:
    ts = pd.Timestamp(index)
    return ts.tz_convert(LISBON).strftime('%d/%m/%Y %H:%M')


def telegram_message(ts: pd.Timestamp, row: pd.Series, minutes: int = 15) -> str:
    emoji = '🟢' if row.signal == 'COMPRA' else '🔴'
    return (
        f'{emoji} GBP/JPY — POSSÍVEL {row.signal} ({minutes}m)\n'
        f'Fecho da vela (Lisboa): {format_lisbon(ts + pd.Timedelta(minutes=minutes))}\n'
        f'Entrada de referência: {fmt_price(row.entry)}\n'
        f'Stop-loss: {fmt_price(row.stop)} ({row.stop_pips:.0f} pips)\n'
        f'Alvo 1 (1,5R): {fmt_price(row.target1)}\n'
        f'Alvo 2 (2,0R): {fmt_price(row.target2)}\n'
        f'RSI {minutes}m: {row.rsi:.1f} | Tendência 1h: {row.trend}\n\n'
        '⚠️ Sinal técnico, não ordem. Confirma spread, notícias e risco antes de entrar. '
        'Os preços podem variar face à tua corretora.'
    )
