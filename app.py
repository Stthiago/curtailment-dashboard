from pathlib import Path
import io
import re
import unicodedata
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title='Constrained-off SIN | Intelligence',page_icon='⚡',layout='wide',initial_sidebar_state='expanded')
ROOT=Path(__file__).resolve().parent
LOCAL=Path(r'C:\Users\tsc\OneDrive - Elera\Desktop\Projeto LT (Pós)')
COLORS={'ENE':'#F6B44B','CNF':'#A78BFA','REL':'#4CC9C0','Fotovoltaica':'#F6B44B','Eólica':'#4EA8DE'}
REASONS=['ENE','CNF','REL']
NUM=['val_geracao','val_geracaolimitada','val_disponibilidade','val_geracaoreferencia','val_geracaoreferenciafinal','val_geracaonaorealizadaapurada']
STATES={'AC':(-9.02,-70.81),'AL':(-9.57,-36.78),'AP':(1.41,-51.77),'AM':(-3.42,-65.86),'BA':(-12.58,-41.70),'CE':(-5.20,-39.53),'DF':(-15.78,-47.93),'ES':(-19.18,-40.31),'GO':(-15.83,-49.84),'MA':(-5.00,-45.27),'MT':(-12.68,-55.70),'MS':(-20.77,-54.79),'MG':(-18.51,-44.56),'PA':(-3.79,-52.48),'PB':(-7.24,-36.78),'PR':(-24.89,-51.55),'PE':(-8.38,-37.86),'PI':(-7.72,-42.73),'RJ':(-22.25,-42.66),'RN':(-5.81,-36.59),'RS':(-30.03,-53.09),'RO':(-10.83,-63.34),'RR':(1.99,-61.33),'SC':(-27.24,-50.22),'SP':(-22.19,-48.79),'SE':(-10.57,-37.45),'TO':(-10.18,-48.33)}
st.markdown('''<style>.block-container{padding-top:1.3rem;max-width:1650px}h1,h2,h3{letter-spacing:-.035em}div[data-testid="stMetric"]{background:rgba(120,140,170,.08);padding:16px;border:1px solid rgba(120,140,170,.16);border-radius:14px}div[data-testid="stSidebar"]{border-right:1px solid rgba(120,140,170,.18)}.subtle{opacity:.7;font-size:.9rem}</style>''',unsafe_allow_html=True)

def norm(x):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(x)) if not unicodedata.combining(c)).upper().strip()

def sources():
    roots=[ROOT/'Bases',ROOT,LOCAL/'Bases',LOCAL]
    found={}
    for folder in roots:
        if not folder.is_dir():continue
        for p in sorted(folder.glob('*')):
            if p.suffix.lower() not in ('.xlsx','.csv'):continue
            name=norm(p.name)
            if p.suffix.lower()=='.xlsx' and 'RESTRICAO_COFF_' in name and ('FOTOVOLTAICA' in name or 'EOLICA' in name):
                found.setdefault(p.name,p)
            if p.suffix.lower()=='.csv' and 'SIGA' in name and 'EMPREENDIMENTOS' in name:
                found.setdefault(p.name,p)
    return list(found.values())

def signature(paths):return tuple((str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in paths)

@st.cache_data(show_spinner='Carregando bases ONS...',max_entries=3)
def load_ons(paths_sig,uploaded=()):
    chunks=[]
    for path,_,_ in paths_sig:
        p=Path(path)
        source='Fotovoltaica' if 'FOTOVOLTAICA' in norm(p.name) else 'Eólica'
        d=pd.read_excel(p,engine='openpyxl');d.columns=d.columns.astype(str).str.strip().str.lower();d['fonte']=source;d['arquivo_origem']=p.name;chunks.append(d)
    for filename,raw in uploaded:
        source='Fotovoltaica' if 'FOTOVOLTAICA' in norm(filename) else 'Eólica'
        d=pd.read_excel(io.BytesIO(raw),engine='openpyxl');d.columns=d.columns.astype(str).str.strip().str.lower();d['fonte']=source;d['arquivo_origem']=filename;chunks.append(d)
    if not chunks:return pd.DataFrame()
    df=pd.concat(chunks,ignore_index=True)
    if 'din_instante' not in df:raise ValueError('Coluna din_instante ausente das planilhas ONS.')
    df['din_instante']=pd.to_datetime(df['din_instante'],errors='coerce');df=df.dropna(subset=['din_instante'])
    for c in NUM:df[c]=pd.to_numeric(df[c],errors='coerce') if c in df else np.nan
    for c in ['nom_usina','nom_estado','id_estado','nom_subsistema','cod_razaorestricao','ceg','id_ons','nom_agenteoperador','nom_pontoconexao']:
        df[c]=df[c].fillna('').astype(str).str.strip() if c in df else ''
    df['razao']=df['cod_razaorestricao'].str.upper()
    df['restrito']=df['razao'].isin(REASONS)
    df['curtailment_mwh']=df['val_geracaonaorealizadaapurada'].clip(lower=0)*.5
    df.loc[~df['restrito'],'curtailment_mwh']=0.
    df['geracao_mwh']=df['val_geracao']*.5
    df['data']=df['din_instante'].dt.date
    df['mes']=df['din_instante'].dt.to_period('M').dt.to_timestamp()
    df['hora']=df['din_instante'].dt.hour+df['din_instante'].dt.minute/60
    # Evita dupla contagem se o mesmo registro estiver em dois arquivos mensais.
    key=['fonte','id_ons','din_instante']
    df=df.sort_values('arquivo_origem').drop_duplicates(key,keep='last')
    return df

@st.cache_data(show_spinner='Carregando cadastro SIGA / ANEEL...',max_entries=3)
def load_siga(path_sig,raw=None):
    if raw is None and path_sig is None:return pd.DataFrame()
    stream=io.BytesIO(raw) if raw is not None else path_sig[0]
    d=pd.read_csv(stream,sep=';',encoding='utf-8-sig',low_memory=False,on_bad_lines='skip')
    d.columns=d.columns.str.strip()
    required=['CodCEG','NomEmpreendimento','SigUFPrincipal','SigTipoGeracao','NumCoordNEmpreendimento','NumCoordEEmpreendimento']
    if any(c not in d.columns for c in required):raise ValueError('CSV SIGA sem as colunas esperadas: '+', '.join(set(required)-set(d.columns)))
    d=d[d['SigTipoGeracao'].isin(['UFV','EOL'])].copy()
    for col,new in [('NumCoordNEmpreendimento','lat'),('NumCoordEEmpreendimento','lon'),('MdaPotenciaFiscalizadaKw','pot_kw')]:
        if col in d:d[new]=pd.to_numeric(d[col].astype(str).str.replace('.','',regex=False).str.replace(',','.',regex=False),errors='coerce') if col!='MdaPotenciaFiscalizadaKw' else pd.to_numeric(d[col].astype(str).str.replace(',','.',regex=False),errors='coerce')
        else:d[new]=np.nan
    d['pot_mw']=d['pot_kw']/1000
    d['ceg_key']=d['CodCEG'].map(norm)
    d['fonte']=d['SigTipoGeracao'].map({'UFV':'Fotovoltaica','EOL':'Eólica'})
    d=d[d['lat'].between(-35,6)&d['lon'].between(-75,-30)].drop_duplicates('ceg_key')
    return d

def plot(fig,height=420):
    fig.update_layout(template='plotly_dark',height=height,margin=dict(l=12,r=12,t=52,b=12),legend_title_text='',paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig,use_container_width=True)

def map_plot(df,lat='lat',lon='lon',size=None,color=None,hover_name=None,hover_data=None,height=540,zoom=3.1):
    if df.empty:st.info('Nenhum ponto geográfico disponível para os filtros atuais.');return
    kwargs=dict(data_frame=df,lat=lat,lon=lon,hover_name=hover_name,hover_data=hover_data,zoom=zoom,center={'lat':-14,'lon':-52},height=height,map_style='open-street-map')
    if size and pd.to_numeric(df[size],errors='coerce').fillna(0).gt(0).any():kwargs['size']=size;kwargs['size_max']=23
    if color:kwargs['color']=color;kwargs['color_discrete_map']=COLORS
    fig=px.scatter_map(**kwargs)
    fig.update_layout(margin=dict(l=0,r=0,t=0,b=0),legend_title_text='')
    st.plotly_chart(fig,use_container_width=True)

paths=sources();ons_files=[p for p in paths if p.suffix.lower()=='.xlsx'];siga_files=[p for p in paths if p.suffix.lower()=='.csv']
with st.sidebar:
    st.markdown('### ⚡ CONSTRAINED-OFF SIN')
    st.caption('Inteligência de restrições renováveis')
    with st.expander('Fontes de dados',expanded=False):
        st.caption(f'{len(ons_files)} planilha(s) ONS encontradas')
        for p in ons_files:st.caption('• '+str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else '• '+p.name)
        st.caption('SIGA: '+(siga_files[0].name if siga_files else 'não encontrado'))
    ons_upload=st.file_uploader('Adicionar planilhas ONS (opcional)',type='xlsx',accept_multiple_files=True)
    siga_upload=st.file_uploader('Substituir cadastro SIGA (opcional)',type='csv')
    st.divider()
ons_sig=signature(ons_files)
valid_upload=[(f.name,f.getvalue()) for f in ons_upload if 'RESTRICAO_COFF_' in norm(f.name) and ('EOLICA' in norm(f.name) or 'FOTOVOLTAICA' in norm(f.name))]
try:df=load_ons(ons_sig,tuple(valid_upload))
except Exception as e:st.error(f'Erro ao ler planilhas ONS: {e}');st.stop()
if df.empty:st.error('Nenhuma planilha ONS encontrada. Adicione arquivos RESTRICAO_COFF_*.xlsx na raiz ou na pasta Bases/ do repositório.');st.stop()
try:siga=load_siga((str(siga_files[0]),siga_files[0].stat().st_mtime_ns) if siga_files else None,siga_upload.getvalue() if siga_upload else None)
except Exception as e:st.warning(f'Cadastro SIGA não pôde ser lido: {e}');siga=pd.DataFrame()
with st.sidebar:
    start_min,end_max=df['data'].min(),df['data'].max()
    date_range=st.date_input('Período',(start_min,end_max),min_value=start_min,max_value=end_max)
    start,end=date_range if isinstance(date_range,(tuple,list)) and len(date_range)==2 else (start_min,end_max)
    fontes=st.multiselect('Fonte',sorted(df['fonte'].unique()),default=sorted(df['fonte'].unique()))
    subset=df[df['fonte'].isin(fontes)]
    submercados=st.multiselect('Submercado',sorted(subset['nom_subsistema'].unique()))
    if submercados:subset=subset[subset['nom_subsistema'].isin(submercados)]
    estados=st.multiselect('Estado (nome)',sorted(subset['nom_estado'].unique()))
    if estados:subset=subset[subset['nom_estado'].isin(estados)]
    parques=st.multiselect('Parque / conjunto ONS',sorted(subset['nom_usina'].unique()))
    if parques:subset=subset[subset['nom_usina'].isin(parques)]
    razoes=st.multiselect('Razão da restrição',REASONS,default=REASONS)
    freq=st.selectbox('Granularidade',['Diária','30 minutos','Mensal'])
    st.caption('Energia (MWh) = MW médios × 0,5 h. A seleção de razões não remove registros da geração total.')
base=subset[subset['data'].between(start,end)].copy()
restr=base[base['restrito']&base['razao'].isin(razoes)].copy()
if base.empty:st.warning('Nenhum registro para os filtros selecionados.');st.stop()
energy=restr['curtailment_mwh'].sum();generation=base['geracao_mwh'].sum();missing=int(restr['curtailment_mwh'].isna().sum())
st.title('Constrained-off | SIN')
st.caption('ONS × ANEEL SIGA  •  Análise temporal, espacial e operacional  •  Coordenadas geográficas provenientes do cadastro SIGA')
k1,k2,k3,k4,k5=st.columns(5)
k1.metric('Energia restringida',f'{energy/1000:,.2f} GWh')
k2.metric('Geração verificada',f'{generation/1000:,.2f} GWh')
k3.metric('Conjuntos afetados',f'{restr.loc[restr.curtailment_mwh>0,"nom_usina"].nunique():,}')
k4.metric('Registros restritos',f'{len(restr):,}')
k5.metric('Sem perda apurada',f'{missing:,}',help='Registros restritos cujo valor de geração não realizada está ausente.')
if missing:st.warning(f'{missing:,} registros restritos não possuem valor de perda apurada; eles não são tratados como perda zero.')
t1,t2,t3,t4,t5,t6=st.tabs(['📊 Visão executiva','🗺️ Mapas SIGA + ONS','📈 Evolução','🏆 Rankings','🔎 Conjunto','🗃️ Auditoria'])
with t1:
    a,b=st.columns([1.6,1])
    with a:
        d=restr.groupby(['data','razao'],as_index=False)['curtailment_mwh'].sum()
        plot(px.bar(d,x='data',y='curtailment_mwh',color='razao',color_discrete_map=COLORS,title='Energia restringida por dia e razão',labels={'data':'Data','curtailment_mwh':'MWh'}))
    with b:
        d=restr.groupby('razao',as_index=False)['curtailment_mwh'].sum()
        if d['curtailment_mwh'].sum()>0:plot(px.pie(d,names='razao',values='curtailment_mwh',hole=.62,color='razao',color_discrete_map=COLORS,title='Distribuição ENE / CNF / REL'))
        else:st.info('Sem restrições apuradas no período.')
    d=restr.groupby(['fonte','razao'],as_index=False)['curtailment_mwh'].sum()
    plot(px.bar(d,x='fonte',y='curtailment_mwh',color='razao',barmode='stack',color_discrete_map=COLORS,title='Energia restringida por fonte e razão'))
with t2:
    st.subheader('Geografia das usinas e das restrições')
    st.caption('Pontos SIGA representam empreendimentos cadastrados pela ANEEL. Conjuntos ONS não são posicionados em coordenadas SIGA sem correspondência CEG exata.')
    if siga.empty:st.warning('Arquivo SIGA não encontrado. Adicione siga-empreendimentos-geracao.csv na raiz ou pasta Bases/ do GitHub.')
    else:
        sig=siga[siga['fonte'].isin(fontes)].copy()
        selected_uf=set(base['id_estado'].str.upper().unique())
        if estados or submercados or parques:sig=sig[sig['SigUFPrincipal'].isin(selected_uf)]
        st.markdown('#### Mapa 1 · Empreendimentos SIGA (localização real cadastrada)')
        mode=st.radio('Visualizar', ['Todos os empreendimentos das fontes selecionadas','Somente empreendimentos com correspondência CEG exata'],horizontal=True)
        ons_ceg=base[['ceg','fonte','nom_usina','id_estado']].copy()
        ons_ceg['ceg_key']=ons_ceg['ceg'].map(norm)
        ons_ceg=ons_ceg[~ons_ceg['ceg_key'].isin(['','-','NAN'])].drop_duplicates(['ceg_key','fonte'])
        matched=sig.merge(ons_ceg[['ceg_key','fonte','nom_usina']],on=['ceg_key','fonte'],how='inner')
        if mode.startswith('Somente'):sig_map=matched
        else:sig_map=sig
        if len(sig_map)>7000:
            st.info('Exibindo amostra determinística de até 7.000 pontos para manter o mapa responsivo; métricas usam a base completa.')
            sig_map=sig_map.sample(n=7000,random_state=42)
        m1,m2,m3=st.columns(3)
        m1.metric('Usinas SIGA no filtro',f'{len(sig):,}')
        m2.metric('Potência fiscalizada SIGA',f'{sig["pot_mw"].sum()/1000:,.2f} GW')
        m3.metric('CEGs com vínculo exato',f'{matched["ceg_key"].nunique():,}')
        map_plot(sig_map,color='fonte',hover_name='NomEmpreendimento',hover_data={'SigUFPrincipal':True,'CodCEG':True,'pot_mw':':.2f','lat':False,'lon':False})
        st.markdown('#### Mapa 2 · Curtailment ONS por estado')
        st.caption('Os marcadores representam o centro aproximado de cada UF, NÃO a localização física dos parques. Valores agregados por UF dos registros ONS.')
        by_uf=restr.groupby('id_estado',as_index=False).agg(curtailment_mwh=('curtailment_mwh','sum'),registros=('din_instante','size'),conjuntos=('nom_usina','nunique'))
        by_uf['lat']=by_uf['id_estado'].map(lambda x:STATES.get(x,(np.nan,np.nan))[0]);by_uf['lon']=by_uf['id_estado'].map(lambda x:STATES.get(x,(np.nan,np.nan))[1]);by_uf=by_uf.dropna(subset=['lat','lon'])
        map_plot(by_uf,size='curtailment_mwh',hover_name='id_estado',hover_data={'curtailment_mwh':':,.1f','conjuntos':True,'registros':True,'lat':False,'lon':False})
        st.markdown('#### Comparativo estadual: potência SIGA × energia restringida ONS')
        capacity=sig.groupby('SigUFPrincipal',as_index=False)['pot_mw'].sum().rename(columns={'SigUFPrincipal':'id_estado'})
        comp=by_uf[['id_estado','curtailment_mwh','conjuntos']].merge(capacity,on='id_estado',how='outer').fillna({'curtailment_mwh':0,'pot_mw':0,'conjuntos':0})
        comp['mwh_por_mw_instalado']=np.where(comp['pot_mw']>0,comp['curtailment_mwh']/comp['pot_mw'],np.nan)
        st.caption('Indicador exploratório MWh restringidos / MW fiscalizados, NÃO é taxa oficial de curtailment. O denominador inclui usinas SIGA que podem não integrar os conjuntos ONS selecionados.')
        plot(px.scatter(comp,x='pot_mw',y='curtailment_mwh',text='id_estado',size='pot_mw',hover_data=['mwh_por_mw_instalado','conjuntos'],title='Potência fiscalizada SIGA × restrição ONS por UF',labels={'pot_mw':'Potência fiscalizada SIGA (MW)','curtailment_mwh':'Curtailment ONS (MWh)'}))
        st.dataframe(comp.sort_values('curtailment_mwh',ascending=False),hide_index=True,use_container_width=True)
with t3:
    gran={'Diária':'D','30 minutos':'30min','Mensal':'MS'}[freq]
    d=restr.groupby([pd.Grouper(key='din_instante',freq=gran),'razao'],as_index=False)['curtailment_mwh'].sum()
    plot(px.area(d,x='din_instante',y='curtailment_mwh',color='razao',color_discrete_map=COLORS,title=f'Evolução do curtailment · {freq}'))
    d=base.groupby([pd.Grouper(key='din_instante',freq=gran),'fonte'],as_index=False)['geracao_mwh'].sum()
    plot(px.line(d,x='din_instante',y='geracao_mwh',color='fonte',color_discrete_map=COLORS,title='Geração verificada por fonte'))
    d=restr.groupby(['hora','razao'],as_index=False)['curtailment_mwh'].sum()
    plot(px.line(d,x='hora',y='curtailment_mwh',color='razao',color_discrete_map=COLORS,markers=True,title='Perfil intradiário de restrição'))
with t4:
    dims={'Conjunto':'nom_usina','UF':'id_estado','Submercado':'nom_subsistema','Agente':'nom_agenteoperador','Ponto de conexão':'nom_pontoconexao'}
    dimension=st.selectbox('Dimensão',list(dims))
    top_n=st.slider('Top N',5,40,15)
    d=restr.groupby(dims[dimension],as_index=False)['curtailment_mwh'].sum().nlargest(top_n,'curtailment_mwh').sort_values('curtailment_mwh')
    plot(px.bar(d,x='curtailment_mwh',y=dims[dimension],orientation='h',title=f'Top {top_n} · {dimension}'),height=max(420,top_n*29))
    st.dataframe(d.sort_values('curtailment_mwh',ascending=False),hide_index=True,use_container_width=True)
with t5:
    chosen=st.selectbox('Conjunto ONS',sorted(base['nom_usina'].unique()))
    b=base[base['nom_usina']==chosen].sort_values('din_instante');r=restr[restr['nom_usina']==chosen]
    a1,a2,a3=st.columns(3);a1.metric('Curtailment',f'{r.curtailment_mwh.sum():,.1f} MWh');a2.metric('Geração',f'{b.geracao_mwh.sum():,.1f} MWh');a3.metric('Intervalos restritos',len(r))
    fig=go.Figure()
    for c,label,color in [('val_geracao','Geração verificada','#4EA8DE'),('val_geracaoreferencia','Referência','#F6B44B'),('val_geracaoreferenciafinal','Referência final','#A78BFA'),('val_disponibilidade','Disponibilidade','#4CC9C0'),('val_geracaolimitada','Geração limitada','#E7798B')]:
        if b[c].notna().any():fig.add_trace(go.Scatter(x=b['din_instante'],y=b[c],name=label,mode='lines',line=dict(color=color)))
    fig.update_layout(title='Variáveis operativas · MW médios',yaxis_title='MW');plot(fig)
    if not r.empty:plot(px.bar(r,x='din_instante',y='curtailment_mwh',color='razao',color_discrete_map=COLORS,title='Restrição por intervalo · MWh'))
    if not siga.empty:
        ceg=b['ceg'].map(norm).unique().tolist()
        loc=siga[siga['ceg_key'].isin(ceg)&siga['fonte'].isin(b['fonte'].unique())]
        if len(loc):
            st.caption('Localização SIGA confirmada por CEG exata:');map_plot(loc,hover_name='NomEmpreendimento',hover_data=['CodCEG'],zoom=5)
        else:st.info('Este conjunto não possui correspondência CEG exata no SIGA. Não é possível afirmar sua localização precisa apenas pelo nome.')
    st.dataframe(b,hide_index=True,use_container_width=True)
with t6:
    st.subheader('Rastreabilidade e qualidade')
    st.write({'Registros após deduplicação':len(base),'Conjuntos':base['nom_usina'].nunique(),'Restrições sem valor apurado':missing,'Planilhas ONS':len(ons_files),'Empreendimentos SIGA com coordenadas':len(siga)})
    st.dataframe(base,hide_index=True,use_container_width=True,height=440)
    st.download_button('Baixar registros filtrados (CSV)',base.to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),file_name='constrainedoff_filtrado.csv',mime='text/csv')
    if not siga.empty:st.download_button('Baixar cadastro SIGA filtrado (CSV)',siga[siga['fonte'].isin(fontes)].to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),file_name='siga_renovaveis.csv',mime='text/csv')
st.divider()
st.caption('Fontes: planilhas de restrição ONS e SIGA/ANEEL fornecidas pelo usuário. Coordenadas SIGA não representam automaticamente conjuntos agregados ONS. Antes de divulgar, confirme a autorização de publicação das bases.')
