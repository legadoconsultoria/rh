import streamlit as st
import pandas as pd
from supabase import create_client, Client
from datetime import datetime
import pytz
from fpdf import FPDF
import unicodedata
import os

# Configuração do banco de dados Supabase
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase: Client = init_connection()
FUSO_BR = pytz.timezone('America/Sao_Paulo')

CARDAPIO = {
    "Marmita": 20.00,
    "Marmita Pequena": 15.00,
    "Refrigerante 2L": 15.00,
    "Refrigerante 600ml": 8.00,
    "Refrigerante lata": 7.00
}

# --- FUNÇÕES DO BANCO DE DADOS ---
def carregar_usuarios():
    # Busca apenas os nomes dos usuários, sem ligar para senhas
    response = supabase.table("usuarios").select("nome").execute()
    return [row['nome'] for row in response.data]

def carregar_pedidos():
    response = supabase.table("pedidos").select("*").execute()
    dados = response.data
    if dados:
        df = pd.DataFrame(dados)
        if 'hora_extra' not in df.columns:
            df['hora_extra'] = False
            
        df['Data_Hora'] = pd.to_datetime(df['created_at']).dt.tz_convert(FUSO_BR)
        df['Apenas_Data'] = df['Data_Hora'].dt.date
        df['Mes_Ano'] = df['Data_Hora'].dt.strftime("%m/%Y")
        df['Hora_Fomatada'] = df['Data_Hora'].dt.strftime("%H:%M")
        return df
    return pd.DataFrame()

def salvar_pedido(nome, itens, observacao, total, hora_extra):
    novo_pedido = {
        "nome": nome,
        "itens": itens,
        "observacao": observacao,
        "total": total,
        "hora_extra": hora_extra
    }
    supabase.table("pedidos").insert(novo_pedido).execute()

# --- FUNÇÕES AUXILIARES ---
def remover_acentos(texto):
    if pd.isna(texto): return ""
    return unicodedata.normalize('NFKD', str(texto)).encode('ASCII', 'ignore').decode('utf-8')

def gerar_pdf(df, data_str):
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    
    logo_path = None
    for ext in ['png', 'jpg', 'jpeg']:
        if os.path.exists(f'adf.{ext}'):
            logo_path = f'adf.{ext}'
            break
            
    if logo_path:
        pdf.image(logo_path, x=10, y=8, w=30)
        pdf.set_y(40)
    else:
        pdf.set_y(20)

    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 10, f"Relatorio de Pedidos - {data_str}", ln=True, align="C")
    pdf.ln(10)

    pdf.set_font("helvetica", "B", 11)
    pdf.cell(20, 10, "Hora", border=1, align="C")
    pdf.cell(45, 10, "Colaborador", border=1, align="C")
    pdf.cell(65, 10, "Pedido", border=1, align="C")
    pdf.cell(60, 10, "Observacoes", border=1, align="C")
    pdf.ln()

    pdf.set_font("helvetica", "", 10)
    for _, row in df.iterrows():
        hora = str(row['Hora'])
        colab = remover_acentos(row['Colaborador'])[:22]
        pedido = remover_acentos(row['Pedido'])[:35]
        obs = remover_acentos(row['Observações'])[:32]
        
        pdf.cell(20, 10, hora, border=1, align="C")
        pdf.cell(45, 10, colab, border=1)
        pdf.cell(65, 10, pedido, border=1)
        pdf.cell(60, 10, obs, border=1)
        pdf.ln()

    return bytes(pdf.output())


# Carrega a lista de usuários no início da aplicação
lista_usuarios = carregar_usuarios()

# --- INTERFACE DO STREAMLIT ---
st.set_page_config(page_title="Sistema de Pedidos", page_icon="🍔", layout="wide")
st.title("🍔 Sistema de Pedidos - Almoço")

aba_pedidos, aba_restaurante, aba_fechamento, aba_funcionarios = st.tabs([
    "🛒 Fazer Pedido", 
    "🍽️ Relatório Diário", 
    "💰 Fechamento Mensal",
    "👥 Funcionários"
])

# --- ABA 1: FAZER PEDIDO ---
with aba_pedidos:
    st.header("Faça seu pedido")
    st.info("Os pedidos estão liberados. Faça o seu a qualquer momento!")
    
    nome_usuario = st.selectbox("Selecione seu nome:", [""] + lista_usuarios)
    
    st.subheader("Cardápio")
    quantidades = {}
    for item, preco in CARDAPIO.items():
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"**{item}** (R$ {preco:.2f})")
        with col2:
            quantidades[item] = st.number_input(f"Qtd {item}", min_value=0, value=0, step=1, label_visibility="collapsed")
    
    observacao = st.text_input("Observações (Ex: sem legumes, carne bem passada):")
    is_hora_extra = st.checkbox("Marque aqui se for Hora Extra")
    
    if st.button("Confirmar Pedido"):
        if not nome_usuario:
            st.warning("Por favor, identifique-se selecionando seu nome.")
        else:
            itens_escolhidos = [f"{qtd}x {item}" for item, qtd in quantidades.items() if qtd > 0]
            if not itens_escolhidos:
                st.warning("Você precisa adicionar pelo menos um item.")
            else:
                valor_total = sum(quantidades[item] * preco for item, preco in CARDAPIO.items())
                itens_texto = ", ".join(itens_escolhidos)
                salvar_pedido(nome_usuario, itens_texto, observacao, float(valor_total), is_hora_extra)
                st.success(f"Pedido registrado com sucesso, {nome_usuario}!")

# --- ABA 2: RELATÓRIO DIÁRIO ---
with aba_restaurante:
    st.header("Envio para o Restaurante")
    st.divider()
    df_pedidos = carregar_pedidos()
    
    if not df_pedidos.empty:
        data_escolhida = st.date_input("Escolha o dia para gerar o relatório:", format="DD/MM/YYYY")
        df_dia = df_pedidos[df_pedidos['Apenas_Data'] == data_escolhida].copy()
        
        if not df_dia.empty:
            df_restaurante = df_dia[['Hora_Fomatada', 'nome', 'itens', 'observacao']]
            df_restaurante.columns = ['Hora', 'Colaborador', 'Pedido', 'Observações']
            st.dataframe(df_restaurante, use_container_width=True, hide_index=True)
            
            pdf_bytes = gerar_pdf(df_restaurante, data_escolhida.strftime('%d/%m/%Y'))
            st.download_button("📄 Baixar Relatório PDF", data=pdf_bytes, file_name=f"Relatorio_{data_escolhida.strftime('%d_%m_%Y')}.pdf", mime="application/pdf")
        else:
            st.warning("Nenhum pedido foi feito neste dia.")
    else:
        st.info("O banco de dados está vazio.")

# --- ABA 3: FECHAMENTO MENSAL ---
with aba_fechamento:
    st.header("Gestão Financeira")
    st.divider()
    df_pedidos = carregar_pedidos()
    
    if not df_pedidos.empty:
        mes_selecionado = st.selectbox("Selecione o Mês:", df_pedidos['Mes_Ano'].unique().tolist())
        df_mes = df_pedidos[df_pedidos['Mes_Ano'] == mes_selecionado].copy()
        
        df_mes['Total Funcionário'] = df_mes.apply(lambda row: row['total'] if not row['hora_extra'] else 0.0, axis=1)
        df_mes['Total Hora Extra'] = df_mes.apply(lambda row: row['total'] if row['hora_extra'] else 0.0, axis=1)
        
        st.subheader(f"Total a cobrar - {mes_selecionado}")
        resumo = df_mes.groupby('nome')[['Total Funcionário', 'Total Hora Extra']].sum().reset_index()
        resumo['Total Funcionário'] = resumo['Total Funcionário'].apply(lambda x: f"R$ {x:.2f}")
        resumo['Total Hora Extra'] = resumo['Total Hora Extra'].apply(lambda x: f"R$ {x:.2f}")
        resumo.rename(columns={'nome': 'Colaborador'}, inplace=True)
        st.table(resumo)
        
        st.divider()
        st.subheader("Auditoria por Colaborador")
        pessoa_selecionada = st.selectbox("Selecione a pessoa para ver detalhes:", ["Todos"] + df_mes['nome'].unique().tolist())
        df_mes['Hora_Extra?'] = df_mes['hora_extra'].apply(lambda x: "Sim" if x else "Não")
        df_auditoria = df_mes[['Apenas_Data', 'nome', 'itens', 'observacao', 'Hora_Extra?', 'total']]
        df_auditoria.columns = ['Data', 'Nome', 'Pedido', 'Observações', 'Hora Extra?', 'Valor (R$)']
        
        if pessoa_selecionada != "Todos":
            df_auditoria = df_auditoria[df_auditoria['Nome'] == pessoa_selecionada]
        st.dataframe(df_auditoria, use_container_width=True, hide_index=True)
    else:
        st.info("Não há dados suficientes.")

# --- ABA 4: GESTÃO DE FUNCIONÁRIOS ---
with aba_funcionarios:
    st.header("Gestão de Perfis")
    st.divider()
    
    st.subheader("Lista de Funcionários Atual")
    df_users = pd.DataFrame([{"Nome": n} for n in lista_usuarios])
    st.dataframe(df_users, hide_index=True, use_container_width=True)
    
    st.divider()
    col_add, col_edit = st.columns(2)
    
    with col_add:
        st.subheader("Adicionar Funcionário")
        novo_nome = st.text_input("Nome Completo:")
        if st.button("Adicionar"):
            if novo_nome in lista_usuarios:
                st.error("Este usuário já existe!")
            elif novo_nome:
                # O banco exige 'senha', então enviamos um valor padrão oculto
                supabase.table("usuarios").insert({"nome": novo_nome, "senha": "123", "is_admin": False}).execute()
                st.success("Usuário adicionado! A página vai recarregar.")
                st.rerun()
            else:
                st.warning("Preencha o nome.")
    
    with col_edit:
        st.subheader("Excluir Funcionário")
        user_excluir = st.selectbox("Selecione quem excluir:", [""] + lista_usuarios)
        if st.button("Excluir Usuário"):
            if user_excluir:
                supabase.table("usuarios").delete().eq("nome", user_excluir).execute()
                st.success("Excluído com sucesso!")
                st.rerun()
