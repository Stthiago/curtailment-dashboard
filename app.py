from pathlib import Path
import io
import re
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title='Constrained-off | SIN', page_icon='⚡', layout='wide', initial_sidebar_state='expanded')
ROOT = Path(__file__).resolve().parent
LOCAL = Path(r'C:\Users\tsc\OneDrive - Elera\Desktop\Projeto LT (Pós)')
COLORS = {'ENE':'#F59E0B','CNF':'#8B5CF6','REL':'#06B6D4','Fotovoltaica':'#EAB308','Eólica':'#3B82F6'}
REASONS = ['ENE','CNF','REL']
NUMS = ['val_geracao','val_geracaolimitada','val_disponibilidade','val_geracaoreferencia','val_geracaoreferenciafinal','val_geracaonaorealizadaapurada','num_minutos_rel','num_minutos_cnf','num_minutos_ene','num_minutos_restricao']
LABELS = {'nom_usina':'Conjunto','nom_estado':'Estado','nom_subsistema':'Submercado','nom_agenteoperador':'Agente operador','nom_pontoconexao':'Ponto de conexão'}
st.markdown('''<style>.block-container{max-width:1650px;padding-top:1.2rem;padding-bottom:3rem}h1,h2,h3{letter-spacing:-.035em}div[data-testid="stMetric"]{background:rgba(115,130,160,.08);padding:18px;border-radius:14px;border:1px solid rgba(120,140,170,.18)}div[data-testid="stMetricLabel"]{font-weight:600}div[data-testid="stSidebar"]{border-right:1px solid rgba(140,140,140,.18)}.subtitle{opacity:.72;font-size:14px}.eyebrow{font-size:12px;letter-spacing:.12em;font-weight:750;color:#38BDF8;text-transform:uppercase}.footnote{font-size:12px;opacity:.7}</style>''', unsafe_allow_html=True)

def source_type(name):
    name=name.upper()
    if 'FOTOVOLTAICA' in name or 'SOLAR' in name: return 'Fotovoltaica'
    if 'EOLICA' in name or 'EÓLICA' in name: return 'Eólica'
    return None

def discover_files():
    # Cloud: arquivos no repositório; local: pasta do Windows como alternativa.
    found={}
    for folder in [LOCAL,ROOT,ROOT/'Bases']:
        if folder.is_dir():
            for path in sorted(folder.glob('RESTRICAO_COFF_*.xlsx')):
                if source_type(path.name):
                    # Arquivos iguais na pasta Bases prevalecem sobre os da raiz.
                    found[path.name]=path
    return list(found.values())

@st.cache_data(show_spinner='Preparando séries de geração e restrição...')
def read_files(paths_and_signatures, uploads=()):
    frames=[]
    for path,_,_ in paths_and_signatures:
        p=Path(path)
        try:
            d=pd.read_excel(p,engine='openpyxl')
            d['arquivo_origem']=p.name
            d['fonte']=source_type(p.name)
            frames.append(d)
        except Exception as exc:
            st.warning(f'Falha ao ler {p.name}: {exc}')
    for name,data in uploads:
        try:
            d=pd.read_excel(io.BytesIO(data),engine='openpyxl')
            d['arquivo_origem']=name
            d['fonte']=source_type(name)
            frames.append(d)
        except Exception as exc:
            st.warning(f'Falha ao ler {name}: {exc}')
    if not frames: return pd.DataFrame()
    df=pd.concat(frames,ignore_index=True)
    df.columns=df.columns.astype(str).str.strip().str.lower()
    if 'din_instante' not in df: return pd.DataFrame()
    df['din_instante']=pd.to_datetime(df['din_instante'],errors='coerce')
    df=df.dropna(subset=['din_instante','fonte']).copy()
    for col in NUMS: df[col]=pd.to_numeric(df[col],errors='coerce') if col in df else np.nan
    for col in list(LABELS)+['cod_razaorestricao','id_ons','dsc_restricao','cod_origemrestricao']:
        df[col]=df[col].fillna('Não informado').astype(str).str.strip() if col in df else 'Não informado'
    df['razao']=df['cod_razaorestricao'].str.upper()
    df['restrito']=df['razao'].isin(REASONS)
    # Intervalos de 30 minutos: MWmed * 0.5 h = MWh.
    df['perda_mwh']=df['val_geracaonaorealizadaapurada'].clip(lower=0)*.5
    df.loc[~df['restrito'],'perda_mwh']=0.0
    df['geracao_mwh']=df['val_geracao']*.5
    df['data']=df['din_instante'].dt.date
    df['mes']=df['din_instante'].dt.to_period('M').dt.to_timestamp()
    # Impede dupla contagem ao manter somente uma observação por fonte/conjunto/intervalo.
    df=df.sort_values(['din_instante','arquivo_origem']).drop_duplicates(['fonte','id_ons','din_instante'],keep='last')
    return df

def plot(fig,height=420,unified=True):
    fig.update_layout(template='plotly_white',height=height,margin=dict(l=15,r=15,t=65,b=25),font=dict(family='Arial',size=12,color='#263247'),paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',legend_title_text='',hovermode='x unified' if unified else 'closest',title_font_size=17)
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor='rgba(100,116,139,.15)',zeroline=False)
    st.plotly_chart(fig,use_container_width=True)

def fmt(value,unit='MWh'):
    if pd.isna(value): return '—'
    if unit=='MWh' and abs(value)>=1000: return f'{value/1000:,.2f} GWh'
    return f'{value:,.1f} {unit}'

def group_energy(data,group_cols):
    return data.groupby(group_cols,dropna=False,as_index=False)['perda_mwh'].sum()

st.markdown('<div class="eyebrow">Energy intelligence / ONS</div>',unsafe_allow_html=True)
st.title('⚡ Constrained-off | SIN')
st.markdown('<div class="subtitle">Inteligência operacional em restrições de geração eólica e fotovoltaica · Painel exploratório</div>',unsafe_allow_html=True)
paths=discover_files()
signatures=tuple((str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in paths)
with st.sidebar:
    st.header('Centro de filtros')
    with st.expander('📁 Fontes de dados',expanded=False):
        st.caption(f'{len(paths)} arquivo(s) detectado(s) no servidor.')
        for p in paths: st.caption(f'• {p.name} ({p.parent.name})')
        uploads=st.file_uploader('Adicionar planilhas nesta sessão',type=['xlsx'],accept_multiple_files=True)
        st.caption('Os arquivos enviados são temporários e não alteram o GitHub.')
    uploaded=tuple((f.name,f.getvalue()) for f in uploads if source_type(f.name))

df=read_files(signatures,uploaded)
if df.empty:
    st.error('Nenhuma base válida encontrada. Coloque os arquivos RESTRICAO_COFF_*.xlsx na raiz do projeto ou na pasta Bases/ do GitHub.')
    st.stop()
with st.sidebar:
    lo,hi=df['data'].min(),df['data'].max()
    dates=st.date_input('Período',value=(lo,hi),min_value=lo,max_value=hi)
    start,end=(dates if isinstance(dates,tuple) and len(dates)==2 else (lo,hi))
    fontes=st.multiselect('Fonte de geração',sorted(df['fonte'].unique()),default=sorted(df['fonte'].unique()))
    choices=df[df['fonte'].isin(fontes)]
    subs=st.multiselect('Submercado',sorted(choices['nom_subsistema'].unique()))
    if subs: choices=choices[choices['nom_subsistema'].isin(subs)]
    estados=st.multiselect('Estado',sorted(choices['nom_estado'].unique()))
    if estados: choices=choices[choices['nom_estado'].isin(estados)]
    parques=st.multiselect('Parque / conjunto',sorted(choices['nom_usina'].unique()),placeholder='Todos os conjuntos')
    if parques: choices=choices[choices['nom_usina'].isin(parques)]
    reasons=st.multiselect('Razões de restrição',REASONS,default=REASONS)
    gran=st.selectbox('Resolução temporal',['Diária','30 minutos','Mensal'])
    st.divider()
    st.caption('Os filtros de razão afetam a perda, não a geração total. Unidade de energia: MWmed × 0,5 h.')

base=choices[(choices['data']>=start)&(choices['data']<=end)].copy()
if base.empty:
    st.warning('Não há registros para a combinação selecionada.');st.stop()
restr=base[base['restrito']&base['razao'].isin(reasons)].copy()
missing=int(restr['perda_mwh'].isna().sum())
energy=restr['perda_mwh'].sum(min_count=1) if len(restr) else 0
energy=0 if pd.isna(energy) else energy
generation=base['geracao_mwh'].sum()
affected=restr.loc[restr['perda_mwh']>0,'nom_usina'].nunique()
coverage=100*(len(restr)-missing)/len(restr) if len(restr) else 100
st.caption(f'Janela: {start:%d/%m/%Y} – {end:%d/%m/%Y}  ·  {base["nom_usina"].nunique()} conjuntos  ·  {len(base):,} observações')
a,b,c,d,e=st.columns(5)
a.metric('Energia restringida',fmt(energy))
b.metric('Geração verificada',fmt(generation))
c.metric('Conjuntos impactados',f'{affected:,}')
d.metric('Registros com restrição',f'{len(restr):,}')
e.metric('Cobertura da perda',f'{coverage:.1f}%',help='Percentual de registros restritos com energia não realizada apurada preenchida.')
if missing: st.warning(f'Qualidade de dados: {missing:,} intervalos restritos não têm energia não realizada apurada; não foram imputados como zero.')

overview,temporal,rankings,detail,audit=st.tabs(['▦ Visão executiva','◷ Evolução temporal','▤ Rankings','⌁ Análise do conjunto','☷ Dados & auditoria'])
with overview:
    l,r=st.columns([1.6,1])
    with l:
        t=group_energy(restr,['data','razao'])
        fig=px.bar(t,x='data',y='perda_mwh',color='razao',color_discrete_map=COLORS,title='Energia restringida por dia e razão',labels={'data':'Data','perda_mwh':'Energia (MWh)','razao':'Razão'})
        plot(fig)
    with r:
        t=group_energy(restr,['razao'])
        if not t.empty and t['perda_mwh'].sum()>0:
            fig=px.pie(t,names='razao',values='perda_mwh',hole=.68,color='razao',color_discrete_map=COLORS,title='Composição das restrições')
            plot(fig,unified=False)
        else: st.info('Sem perdas apuradas no período.')
    l,r=st.columns(2)
    with l:
        t=group_energy(restr,['fonte','razao'])
        plot(px.bar(t,x='fonte',y='perda_mwh',color='razao',barmode='stack',color_discrete_map=COLORS,title='Perda por fonte e motivo',labels={'fonte':'Fonte','perda_mwh':'MWh'}))
    with r:
        t=group_energy(restr,['nom_subsistema','fonte'])
        plot(px.bar(t,x='nom_subsistema',y='perda_mwh',color='fonte',barmode='group',color_discrete_map=COLORS,title='Distribuição por submercado',labels={'nom_subsistema':'Submercado','perda_mwh':'MWh'}))

with temporal:
    freq={'Diária':'D','30 minutos':'30min','Mensal':'MS'}[gran]
    t=group_energy(restr,[pd.Grouper(key='din_instante',freq=freq),'razao'])
    plot(px.area(t,x='din_instante',y='perda_mwh',color='razao',color_discrete_map=COLORS,title=f'Evolução das restrições • {gran}',labels={'din_instante':'Data/hora','perda_mwh':'MWh'}),470)
    t=base.groupby([pd.Grouper(key='din_instante',freq=freq),'fonte'],as_index=False)['geracao_mwh'].sum()
    plot(px.line(t,x='din_instante',y='geracao_mwh',color='fonte',color_discrete_map=COLORS,title='Geração verificada por fonte',labels={'din_instante':'Data/hora','geracao_mwh':'MWh'}))
    r=restr.assign(hora=restr['din_instante'].dt.strftime('%H:%M'))
    t=group_energy(r,['hora','razao'])
    plot(px.line(t,x='hora',y='perda_mwh',color='razao',markers=True,color_discrete_map=COLORS,title='Perfil intradiário acumulado da restrição',labels={'hora':'Hora','perda_mwh':'MWh'}))

with rankings:
    l,r=st.columns([2,1])
    with r:
        dimension=st.selectbox('Dimensão',list(LABELS.values()))
        top_n=st.slider('Quantidade de posições',5,30,15)
    col={v:k for k,v in LABELS.items()}[dimension]
    t=group_energy(restr,[col]).nlargest(top_n,'perda_mwh').sort_values('perda_mwh')
    with l:
        plot(px.bar(t,x='perda_mwh',y=col,orientation='h',title=f'Top {top_n} — {dimension}',labels={col:dimension,'perda_mwh':'MWh'}),max(450,top_n*28))
    st.dataframe(t.sort_values('perda_mwh',ascending=False).rename(columns={col:dimension,'perda_mwh':'Curtailment (MWh)'}),hide_index=True,use_container_width=True)

with detail:
    chosen=st.selectbox('Selecione o conjunto para análise',sorted(base['nom_usina'].unique()))
    one=base[base['nom_usina']==chosen].sort_values('din_instante')
    one_restr=restr[restr['nom_usina']==chosen]
    x,y,z=st.columns(3)
    x.metric('Energia restringida',fmt(one_restr['perda_mwh'].sum()))
    y.metric('Geração verificada',fmt(one['geracao_mwh'].sum()))
    z.metric('Intervalos restritos',len(one_restr))
    fig=go.Figure()
    for col,label,color in [('val_geracao','Geração verificada','#3B82F6'),('val_geracaoreferencia','Referência','#F59E0B'),('val_geracaoreferenciafinal','Referência final','#8B5CF6'),('val_disponibilidade','Disponibilidade','#10B981'),('val_geracaolimitada','Geração limitada','#64748B')]:
        if one[col].notna().any(): fig.add_trace(go.Scatter(x=one['din_instante'],y=one[col],name=label,mode='lines',line=dict(color=color,width=2)))
    fig.update_layout(title=f'Potências operativas — {chosen}',yaxis_title='MW médios')
    plot(fig,490)
    t=group_energy(one_restr,['din_instante','razao'])
    plot(px.bar(t,x='din_instante',y='perda_mwh',color='razao',color_discrete_map=COLORS,title='Energia restringida por intervalo',labels={'din_instante':'Data/hora','perda_mwh':'MWh'}))
    st.dataframe(one[['din_instante','fonte','nom_usina','val_geracao','val_disponibilidade','val_geracaoreferencia','val_geracaoreferenciafinal','razao','perda_mwh']],hide_index=True,use_container_width=True)

with audit:
    st.subheader('Rastreabilidade e qualidade da informação')
    q1,q2,q3=st.columns(3)
    q1.metric('Registros filtrados',f'{len(base):,}')
    q2.metric('Perdas ausentes em restrições',f'{missing:,}')
    q3.metric('Arquivos considerados',base['arquivo_origem'].nunique())
    st.dataframe(base.groupby(['arquivo_origem','fonte'],as_index=False).agg(registros=('din_instante','size'),inicio=('din_instante','min'),fim=('din_instante','max')),hide_index=True,use_container_width=True)
    st.caption('A exportação preserva os registros da seleção atual, inclusive os não restritos. Os valores ausentes permanecem nulos.')
    st.dataframe(base,hide_index=True,use_container_width=True,height=410)
    st.download_button('⬇ Exportar seleção em CSV',base.to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),file_name='constrained_off_sin.csv',mime='text/csv')
    st.info('Metodologia: energia em MWh = potência média (MWmed) × 0,5 h. A classificação ENE/CNF/REL usa cod_razaorestricao. Os resultados são exploratórios e devem ser confrontados com as regras oficiais antes de uso regulatório.')
st.divider()
st.markdown('<div class="footnote">Constrained-off SIN • Dados de origem ONS • Visualização exploratória • Atualização mediante commit de novas planilhas</div>',unsafe_allow_html=True)
