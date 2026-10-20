"""Painel web de oportunidades GBP/JPY e EUR/USD (Twelve Data, velas fechadas)."""
from __future__ import annotations
import os
from datetime import datetime, timezone
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from datafeed import get_candles, DataFeedError
from strategy import (
    calculate_signals, aggregate_30m, last_closed_candles, recent_opportunities,
    fmt_price, format_lisbon, LISBON, PIPS,
)

st.set_page_config(page_title='GBP/JPY + EUR/USD · Radar FX', page_icon='📈', layout='wide', initial_sidebar_state='collapsed')

CSS = '''
<style>
.block-container { max-width: 1280px; padding-top: 1.5rem; }
[data-testid="stMetric"] { background: #152238; border:1px solid #2b3a50; border-radius: 14px; padding: 1rem; }
[data-testid="stMetricLabel"] { font-size: 0.88rem !important; color: #a9b8cb; }
[data-testid="stMetricValue"] { color: #eff7ff; font-weight: 700; }
.hero {padding: 24px 26px; border-radius: 20px; background: linear-gradient(105deg,#182945 0%,#122130 70%,#11312b 100%); border: 1px solid #30445d; margin-bottom: 22px;}
.eyebrow {color:#6ce6bf;letter-spacing:.13em;text-transform:uppercase;font-size:.75rem;font-weight:800;margin-bottom:7px;}
.hero-title {font-size:2.2rem;font-weight:850;letter-spacing:-.045em;color:#f6faff;line-height:1.1;}
.hero-sub {color:#a9bfd0;margin-top:8px;font-size:.95rem;}
.signal {border:1px solid #2b3a50;border-radius:17px;padding:19px 23px;background:#152238;margin-top:8px;margin-bottom:20px;}
.signal strong {font-size:1.35rem;}
.signal.buy {border-color: #1d775f;background:#122d2c;}
.signal.sell {border-color: #a44a56;background:#321d2a;}
.signal.wait {border-color:#415069;}
.signal-detail {color:#b8cce0;margin-top:5px;}
.smallmeta {color:#9eafc4;font-size:.83rem;}
</style>
'''
st.markdown(CSS, unsafe_allow_html=True)


def get_key() -> str:
    val = os.getenv('TWELVE_DATA_API_KEY', '')
    if val:
        return val
    try:
        return str(st.secrets.get('TWELVE_DATA_API_KEY', ''))
    except (FileNotFoundError, KeyError):
        return ''


@st.cache_data(ttl=180, show_spinner=False)
def load_quotes(key: str, interval: str, outputsize: int, symbol: str) -> pd.DataFrame:
    return get_candles(key, interval, outputsize, symbol=symbol)


def draw_chart(data: pd.DataFrame, title: str, show_signals: bool = False, symbol: str = 'GBP/JPY'):
    display = data.tail(160)
    fig = make_subplots(rows=2, cols=1, row_heights=[0.78, 0.22], shared_xaxes=True, vertical_spacing=0.045)
    fig.add_trace(go.Candlestick(
        x=display.index, open=display.open, high=display.high, low=display.low, close=display.close,
        name=symbol, increasing_line_color='#50e3bd', decreasing_line_color='#fd6f87',
    ), row=1, col=1)
    if 'ema20' in display:
        fig.add_trace(go.Scatter(x=display.index, y=display.ema20, mode='lines',
                                 line=dict(color='#fed383', width=1.6), name='EMA 20'), row=1, col=1)
    if 'ema50' in display:
        fig.add_trace(go.Scatter(x=display.index, y=display.ema50, mode='lines',
                                 line=dict(color='#6aaeff', width=1.6), name='EMA 50'), row=1, col=1)
    if show_signals and 'signal' in display:
        for side, color, marker in [('COMPRA', '#47dcaa', 'triangle-up'), ('VENDA', '#ff7793', 'triangle-down')]:
            s = display[display.signal == side]
            if not s.empty:
                fig.add_trace(go.Scatter(x=s.index, y=s.close, mode='markers', name=side,
                                         marker=dict(size=13, color=color, symbol=marker,
                                                     line=dict(width=1, color='#0b111c'))), row=1, col=1)
    if 'rsi' in display:
        rsi = display.rsi
    else:
        from strategy import rsi_wilder
        rsi = rsi_wilder(display.close)
    fig.add_trace(go.Scatter(x=display.index, y=rsi, mode='lines', name='RSI 14',
                             line=dict(color='#b8a5fd', width=1.6)), row=2, col=1)
    fig.add_hline(y=70, line_color='#f48993', line_dash='dot', opacity=.55, row=2, col=1)
    fig.add_hline(y=30, line_color='#65d7b7', line_dash='dot', opacity=.55, row=2, col=1)
    fig.update_yaxes(range=[0, 100], row=2, col=1, gridcolor='#263448')
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)),
        height=560, paper_bgcolor='#101a29', plot_bgcolor='#101a29', font=dict(color='#d9e5f4'),
        xaxis_rangeslider_visible=False,
        margin=dict(l=8, r=10, t=55, b=12),
        legend=dict(orientation='h', y=1.08, x=0.33),
        hovermode='x unified',
        xaxis=dict(showgrid=True, gridcolor='#243247', rangeslider_visible=False),
        xaxis2=dict(showgrid=True, gridcolor='#243247', rangeslider_visible=False),
        yaxis=dict(showgrid=True, gridcolor='#243247', side='right'),
    )
    st.plotly_chart(fig, use_container_width=True, config={'displaylogo': False, 'scrollZoom': False})


symbol = st.selectbox('💱 Escolhe o par de moedas', ['GBP/JPY', 'EUR/USD'], index=0)
st.markdown(f'''<div class="hero"><div class="eyebrow">RADAR FX · OPORTUNIDADES TÉCNICAS</div>
<div class="hero-title">{symbol} <span style="color:#67dabd">— Monitor online</span></div>
<div class="hero-sub">Compra e venda · Velas de 15 e 30 minutos · Tendência de 1 hora · Alertas Telegram</div></div>''', unsafe_allow_html=True)

with st.sidebar:
    st.header('⚙️ Configurações')
    st.caption('Os indicadores são calculados em velas fechadas. O Telegram funciona através do agendamento externo GitHub Actions, não depende deste painel.')
    interval_selection = st.radio('Gráfico', ['15 minutos', '30 minutos', '5 minutos', '1 hora'], horizontal=True)
    show_signals = st.checkbox('Mostrar sinais no gráfico', value=True)
    if st.button('🔄 Forçar atualização', use_container_width=True):
        load_quotes.clear()
        st.rerun()
    st.divider()
    st.markdown('**Gestão do risco**')
    st.caption('Stop = 1,8 × ATR(14), mínimo 12 pips. Alvo 1 = 1,5R; alvo 2 = 2R. O spread e o slippage não estão incluídos.')
    st.caption('Não há garantia de acerto. Não usa notícias económicas para filtrar sinais.')

key = get_key()
if not key:
    st.warning('O painel ainda não está ligado à fonte de cotações. Precisas de configurar TWELVE_DATA_API_KEY na Streamlit Cloud.')
    st.markdown('Cria uma chave gratuita em https://twelvedata.com e segue o ficheiro **LEIA-ME.md** incluído no projeto.')
    st.stop()


@st.fragment(run_every='10min')
def render_dashboard():
    try:
        with st.spinner(f'A consultar as velas {symbol}...'):
            raw = load_quotes(key, '15min', 1500, symbol)
            d15 = calculate_signals(last_closed_candles(raw, 15), minutes=15, symbol=symbol)
            d30 = calculate_signals(aggregate_30m(last_closed_candles(raw, 15)), minutes=30, symbol=symbol)
            is_30m = interval_selection == '30 minutos'
            d = d30 if is_30m else d15
            minutes = 30 if is_30m else 15
    except (DataFeedError, ValueError, IndexError) as exc:
        st.error(f'Não foi possível atualizar: {exc}')
        st.stop()

    if d.empty:
        st.warning('Ainda não há velas fechadas.')
        return

    now = pd.Timestamp(datetime.now(timezone.utc))
    latest_ts = d.index[-1]
    latest_close = latest_ts + pd.Timedelta(minutes=minutes)
    last = d.iloc[-1]
    delayed = now - latest_close > pd.Timedelta(minutes=45)
    if delayed:
        st.warning('Dados sem atualização recente. O mercado pode estar fechado ou o fornecedor pode estar atrasado. Não uses estes valores para entrar agora.')

    a,b,c,e = st.columns(4)
    a.metric(f'Último fecho {minutes}m', f'{fmt_price(last.close, symbol)} {symbol.split("/")[1]}')
    b.metric('Tendência 1h', str(last.trend))
    c.metric(f'RSI {minutes}m', f'{last.rsi:.1f}')
    e.metric(f'ATR {minutes}m', f'{last.atr / PIPS[symbol]:.1f} pips')

    if delayed:
        title, cls, desc = '⏸️ FORA DE TEMPO', 'wait', 'Não emitir indicação de entrada com preços desatualizados.'
    elif last.signal == 'COMPRA':
        title, cls, desc = '🟢 SINAL DE COMPRA', 'buy', f'Entrada de referência {fmt_price(last.entry, symbol)} · Stop {fmt_price(last.stop, symbol)} · Alvo 1 {fmt_price(last.target1, symbol)} · Alvo 2 {fmt_price(last.target2, symbol)}'
    elif last.signal == 'VENDA':
        title, cls, desc = '🔴 SINAL DE VENDA', 'sell', f'Entrada de referência {fmt_price(last.entry, symbol)} · Stop {fmt_price(last.stop, symbol)} · Alvo 1 {fmt_price(last.target1, symbol)} · Alvo 2 {fmt_price(last.target2, symbol)}'
    else:
        title, cls, desc = '🟡 AGUARDAR', 'wait', 'A última vela não gerou um novo sinal completo; não significa que o preço vá ficar parado.'
    st.markdown(f'<div class="signal {cls}"><strong>{title}</strong><div class="signal-detail">{desc}</div><div class="smallmeta">Última vela fechada: {format_lisbon(latest_close)} · Hora de Lisboa</div></div>', unsafe_allow_html=True)

    if interval_selection in ('15 minutos', '30 minutos'):
        draw_chart(d, f'{symbol} · {minutes} minutos', show_signals, symbol)
    elif interval_selection == '1 hora':
        from strategy import ema, rsi_wilder
        h = d[['open', 'high', 'low', 'close']].resample('1h').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'
        })
        count = d.close.resample('1h').count()
        h = h.loc[count == 4].copy()
        h['ema20'] = ema(h.close, 20)
        h['ema50'] = ema(h.close, 50)
        h['rsi'] = rsi_wilder(h.close)
        draw_chart(h, f'{symbol} · 1 hora', False, symbol)
        st.caption('Gráfico de 1h agregado a partir de velas de 15m fechadas. A tendência dos sinais usa EMA50 e EMA200 de 1h.')
    else:
        try:
            d5 = last_closed_candles(load_quotes(key, '5min', 400, symbol), 5)
            if len(d5) >= 50:
                from strategy import ema
                d5['ema20'] = ema(d5.close, 20)
                d5['ema50'] = ema(d5.close, 50)
            draw_chart(d5, f'{symbol} · 5 minutos (visualização)', False, symbol)
            st.caption('Os sinais são calculados separadamente em 15m e 30m; o gráfico de 5m serve para acompanhar o preço.')
        except (DataFeedError, ValueError) as exc:
            st.warning(f'Não foi possível carregar 5 minutos: {exc}')

    st.subheader(f'Últimas oportunidades {symbol} · {minutes} minutos')
    signals = recent_opportunities(d)
    if signals.empty:
        st.info('Ainda não foram identificados sinais no histórico disponível. O sistema continua a analisar.')
    else:
        records = []
        for ts, row in signals.tail(18).iloc[::-1].iterrows():
            records.append({
                'Hora (Lisboa)': format_lisbon(ts + pd.Timedelta(minutes=minutes)),
                'Sinal': row.signal,
                'Entrada': fmt_price(row.entry, symbol),
                'Stop-loss': fmt_price(row.stop, symbol),
                'Alvo 1': fmt_price(row.target1, symbol),
                'Alvo 2': fmt_price(row.target2, symbol),
                'RSI': round(float(row.rsi), 1),
            })
        st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)
    st.caption('Sinais históricos apresentados para estudo, não são recomendações válidas para entrar agora. Os níveis usam o fecho da vela, não a cotação da corretora.')

render_dashboard()
st.divider()
st.caption('⚠️ Ferramenta informativa. Forex alavancado envolve risco elevado de perda. Confirma sempre notícias, spread, liquidez e o risco global das tuas posições. Não executa operações.')
