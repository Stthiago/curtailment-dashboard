import io
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title='Curtailment Brasil | ONS', page_icon='⚡', layout='wide', initial_sidebar_state='expanded')
ROOT = Path(__file__).resolve().parent
FILES = {'Fotovoltaica': 'RESTRICAO_COFF_FOTOVOLTAICA_2026_11.xlsx', 'Eólica': 'RESTRICAO_COFF_EOLICA_2026_11.xlsx'}
REASONS = ['ENE', 'CNF', 'REL']
COLORS = {'ENE':'#f59e0b','CNF':'#8b5cf6','REL':'#06b6d4','Fotovoltaica':'#fbbf24','Eólica':'#38bdf8'}
NUMERIC = ['val_geracao','val_geracaolimitada','val_disponibilidade','val_geracaoreferencia','val_geracaoreferenciafinal','val_geracaonaorealizadaapurada','num_minutos_rel','num_minutos_cnf','num_minutos_ene','num_minutos_restricao']
st.markdown('''<style>.block-container{padding-top:1.3rem;max-width:1600px}.stMetric{background:rgba(125,125,125,.07);padding:16px;border-radius:14px;border:1px solid rgba(125,125,125,.16)}h1{letter-spacing:-.04em}div[data-testid="stSidebar"]{border-right:1px solid rgba(125,125,125,.15)}</style>''', unsafe_allow_html=True)

@st.cache_data(show_spinner='Lendo bases ONS...')
def load_data(file_bytes=None):
    chunks=[]
    for fonte, filename in FILES.items():
        if file_bytes and fonte in file_bytes:
            stream=io.BytesIO(file_bytes[fonte])
        else:
            path=ROOT/filename
            if not path.exists():
                continue
            stream=path
        d=pd.read_excel(stream, engine='openpyxl')
        d.columns=d.columns.str.strip().str.lower()
        d['fonte']=fonte
        chunks.append(d)
    if not chunks:
        return pd.DataFrame()
    df=pd.concat(chunks, ignore_index=True)
    df['din_instante']=pd.to_datetime(df['din_instante'], errors='coerce')
    df=df.dropna(subset=['din_instante'])
    for col in NUMERIC:
        if col in df:
            df[col]=pd.to_numeric(df[col],errors='coerce')
        else:
            df[col]=np.nan
    for col in ['nom_usina','nom_estado','nom_subsistema','cod_razaorestricao','nom_agenteoperador','nom_pontoconexao','id_ons']:
        if col not in df: df[col]=''
        df[col]=df[col].fillna('Não informado').astype(str).str.strip()
    df['razao']=df['cod_razaorestricao'].str.upper()
    df['restrito']=df['razao'].isin(REASONS)
    # Base ONS em intervalos de 30 minutos: MWmed x 0,5h = MWh.
    # Não imputar valores ausentes de energia não realizada como zero para registros restritos.
    df['curtailment_mwh']=df['val_geracaonaorealizadaapurada'].clip(lower=0)*0.5
    df.loc[~df['restrito'],'curtailment_mwh']=0.0
    df['geracao_mwh']=df['val_geracao']*0.5
    df['data']=df['din_instante'].dt.date
    df['mes']=df['din_instante'].dt.to_period('M').dt.to_timestamp()
    df['hora']=df['din_instante'].dt.hour+df['din_instante'].dt.minute/60
    return df

st.title('⚡ Curtailment Brasil')
st.caption('Painel analítico de restrições de geração renovável • Dados ONS • Solar e eólica')
with st.sidebar:
    st.header('Filtros')
    uploaded=st.file_uploader('Opcional: carregar arquivos XLSX',type=['xlsx'],accept_multiple_files=True,help='Se não enviar arquivos, o aplicativo usa os XLSX presentes no repositório. Para substituir, envie arquivos com EOLICA ou FOTOVOLTAICA no nome.')
    replacements={}
    for f in uploaded:
        name=f.name.upper()
        if 'FOTOVOLTAICA' in name or 'SOLAR' in name: replacements['Fotovoltaica']=f.getvalue()
        elif 'EOLICA' in name or 'EÓLICA' in name: replacements['Eólica']=f.getvalue()
    if uploaded and not replacements: st.warning('Nome do arquivo deve conter EOLICA ou FOTOVOLTAICA.')

df=load_data(replacements or None)
if df.empty:
    st.error('Nenhuma base encontrada. Coloque os dois arquivos XLSX na mesma pasta de app.py ou carregue-os na barra lateral.')
    st.stop()
with st.sidebar:
    min_date,max_date=df['data'].min(),df['data'].max()
    selected=st.date_input('Período',(min_date,max_date),min_value=min_date,max_value=max_date)
    if isinstance(selected,tuple) and len(selected)==2: start,end=selected
    else: start,end=min_date,max_date
    fontes=st.multiselect('Fonte',sorted(df['fonte'].unique()),default=sorted(df['fonte'].unique()))
    opts=df[df['fonte'].isin(fontes)]
    subs=st.multiselect('Submercado',sorted(opts['nom_subsistema'].unique()),default=[])
    if subs: opts=opts[opts['nom_subsistema'].isin(subs)]
    estados=st.multiselect('Estado',sorted(opts['nom_estado'].unique()),default=[])
    if estados: opts=opts[opts['nom_estado'].isin(estados)]
    parques=st.multiselect('Parque / conjunto',sorted(opts['nom_usina'].unique()),default=[],placeholder='Todos os parques')
    if parques: opts=opts[opts['nom_usina'].isin(parques)]
    razoes=st.multiselect('Razão de restrição',REASONS,default=REASONS)
    st.caption('A seleção de razão afeta os indicadores e gráficos de curtailment; geração total mantém todos os registros dos parques filtrados.')
    freq=st.selectbox('Granularidade', ['Diária','30 minutos','Mensal'],index=0)
    st.divider()
    st.caption('Unidades: MW médios por intervalo de 30 min → MWh = MW × 0,5 h.')
base=opts[(opts['data']>=start)&(opts['data']<=end)].copy()
restr=base[base['restrito'] & base['razao'].isin(razoes)].copy()
if base.empty:
    st.warning('Não há dados para os filtros escolhidos.');st.stop()
missing=restr['curtailment_mwh'].isna().sum()
if missing: st.warning(f'{missing:,} registros com restrição não têm valor de geração não realizada apurada. Eles não entram na soma de energia restringida.'.replace(',','.'))

energy=restr['curtailment_mwh'].sum()
gen=base['geracao_mwh'].sum()
active=restr.loc[restr['curtailment_mwh']>0,'nom_usina'].nunique()
c1,c2,c3,c4,c5=st.columns(5)
c1.metric('Curtailment',f'{energy/1000:,.2f} GWh')
c2.metric('Geração verificada',f'{gen/1000:,.2f} GWh')
c3.metric('Conjuntos afetados',f'{active:,}')
c4.metric('Registros restritos',f'{len(restr):,}')
c5.metric('Perda / (geração + perda)',f'{energy/(gen+energy)*100:.1f}%' if gen+energy>0 else '—',help='Indicador exploratório, não equivale necessariamente ao índice oficial de curtailment.')

visao,evolucao,ranking,parque,dados=st.tabs(['📊 Visão geral','📈 Evolução temporal','🏆 Rankings','🔎 Análise do conjunto','🗃️ Dados'])

def plot(fig, key=None):
    fig.update_layout(template='plotly_dark',height=430,margin=dict(l=15,r=15,t=55,b=20),legend_title_text='',hovermode='x unified')
    st.plotly_chart(fig,use_container_width=True,key=key)

with visao:
    left,right=st.columns([1.5,1])
    with left:
        t=restr.groupby(['data','razao'],as_index=False)['curtailment_mwh'].sum()
        fig=px.bar(t,x='data',y='curtailment_mwh',color='razao',color_discrete_map=COLORS,title='Energia restringida por dia e razão',labels={'data':'Data','curtailment_mwh':'MWh','razao':'Razão'})
        plot(fig,'daily')
    with right:
        t=restr.groupby('razao',as_index=False)['curtailment_mwh'].sum()
        if not t.empty and t['curtailment_mwh'].sum()>0:
            fig=px.pie(t,names='razao',values='curtailment_mwh',hole=.62,color='razao',color_discrete_map=COLORS,title='Participação das razões')
            plot(fig,'pie')
        else: st.info('Sem energia restringida para exibir a distribuição.')
    t=restr.groupby(['fonte','razao'],as_index=False)['curtailment_mwh'].sum()
    fig=px.bar(t,x='fonte',y='curtailment_mwh',color='razao',barmode='stack',color_discrete_map=COLORS,title='Curtailment por fonte e razão',labels={'fonte':'Fonte','curtailment_mwh':'MWh'})
    plot(fig,'sources')

with evolucao:
    gran={'Diária':'D','30 minutos':'30min','Mensal':'MS'}[freq]
    r=restr.groupby([pd.Grouper(key='din_instante',freq=gran),'razao'],as_index=False)['curtailment_mwh'].sum()
    fig=px.area(r,x='din_instante',y='curtailment_mwh',color='razao',color_discrete_map=COLORS,title=f'Evolução do curtailment • {freq}',labels={'din_instante':'Data/hora','curtailment_mwh':'MWh'})
    plot(fig,'time')
    g=base.groupby([pd.Grouper(key='din_instante',freq=gran),'fonte'],as_index=False)['geracao_mwh'].sum()
    fig=px.line(g,x='din_instante',y='geracao_mwh',color='fonte',color_discrete_map=COLORS,markers=(freq!='30 minutos'),title='Geração verificada por fonte',labels={'din_instante':'Data/hora','geracao_mwh':'MWh'})
    plot(fig,'generation')
    hh=restr.groupby(['hora','razao'],as_index=False)['curtailment_mwh'].sum()
    fig=px.line(hh,x='hora',y='curtailment_mwh',color='razao',color_discrete_map=COLORS,markers=True,title='Perfil horário acumulado da restrição',labels={'hora':'Hora do dia','curtailment_mwh':'MWh'})
    plot(fig,'hour')

with ranking:
    dim=st.selectbox('Agrupar ranking por',['Parque / conjunto','Estado','Submercado','Agente operador','Ponto de conexão'])
    dims={'Parque / conjunto':'nom_usina','Estado':'nom_estado','Submercado':'nom_subsistema','Agente operador':'nom_agenteoperador','Ponto de conexão':'nom_pontoconexao'}
    top=st.slider('Top N',5,40,15)
    t=restr.groupby(dims[dim],as_index=False)['curtailment_mwh'].sum().nlargest(top,'curtailment_mwh').sort_values('curtailment_mwh')
    fig=px.bar(t,x='curtailment_mwh',y=dims[dim],orientation='h',title=f'Top {top} • {dim}',labels={'curtailment_mwh':'Curtailment (MWh)',dims[dim]:dim})
    fig.update_layout(height=max(430,top*27))
    st.plotly_chart(fig,use_container_width=True)
    st.dataframe(t.sort_values('curtailment_mwh',ascending=False),hide_index=True,use_container_width=True)

with parque:
    options=sorted(base['nom_usina'].unique())
    chosen=st.selectbox('Selecione o conjunto',options)
    b=base[base['nom_usina']==chosen].sort_values('din_instante')
    rr=restr[restr['nom_usina']==chosen]
    a,bcol,c=st.columns(3)
    a.metric('Curtailment do conjunto',f'{rr["curtailment_mwh"].sum():,.1f} MWh')
    bcol.metric('Geração verificada',f'{b["geracao_mwh"].sum():,.1f} MWh')
    c.metric('Intervalos com restrição',f'{len(rr):,}')
    fig=go.Figure()
    for col,label,color in [('val_geracao','Geração verificada','#38bdf8'),('val_geracaoreferencia','Geração referência','#fbbf24'),('val_geracaoreferenciafinal','Referência final','#a78bfa'),('val_disponibilidade','Disponibilidade','#34d399')]:
        if b[col].notna().any():fig.add_trace(go.Scatter(x=b['din_instante'],y=b[col],name=label,mode='lines',line=dict(color=color)))
    fig.update_layout(title='Potências do conjunto • MW médios',yaxis_title='MW')
    plot(fig,'park_lines')
    if not rr.empty:
        fig=px.bar(rr,x='din_instante',y='curtailment_mwh',color='razao',color_discrete_map=COLORS,title='Energia restringida por intervalo',labels={'din_instante':'Data/hora','curtailment_mwh':'MWh'})
        plot(fig,'park_curt')
    st.dataframe(b[['din_instante','fonte','nom_usina','val_geracao','val_disponibilidade','val_geracaoreferencia','val_geracaoreferenciafinal','razao','curtailment_mwh']],hide_index=True,use_container_width=True)

with dados:
    st.caption('Exportação da seleção atual. Linhas sem restrição são preservadas para auditoria.')
    export=base.copy()
    export['curtailment_mwh_filtrado']=np.where(export['razao'].isin(razoes),export['curtailment_mwh'],0.0)
    st.dataframe(export,hide_index=True,use_container_width=True,height=480)
    st.download_button('⬇️ Baixar dados filtrados (CSV)',data=export.to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),file_name='curtailment_filtrado.csv',mime='text/csv')
    st.markdown('**Qualidade da base**')
    st.write({'Registros':len(base),'Datas':f'{start} a {end}','Conjuntos':base['nom_usina'].nunique(),'Restritos sem energia apurada':int(missing),'Intervalos duplicados por fonte/ID ONS/data':int(base.duplicated(['fonte','id_ons','din_instante']).sum())})

st.divider()
st.caption('Fonte: planilhas ONS fornecidas pelo usuário. Conversão assumida: 30 minutos por registro. Verifique a unidade e a metodologia oficial antes de utilizar os resultados em relatórios regulatórios.')
