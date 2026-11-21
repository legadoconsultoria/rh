import streamlit as st
import pandas as pd
from supabase import create_client, Client
from datetime import datetime
import pytz
from fpdf import FPDF
import unicodedata
import os
import io

# Configuração do banco de dados Supabase
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase: Client = init_connection()
FUSO_BR = pytz.timezone("America/Sao_Paulo")

CARDAPIO = {
    "Marmita": 20.00,
    "Marmita Pequena": 15.00,
    "Refrigerante 2L": 15.00,
    "Refrigerante 600ml": 8.00,
    "Refrigerante lata": 7.00,
}

# --- FUNÇÕES DO BANCO DE DADOS ---
def carregar_usuarios():
    try:
        response = supabase.table("usuarios").select("nome").execute()
        if response.data:
            return [row["nome"] for row in response.data if row.get("nome")]
        return []
    except Exception as e:
        st.error(f"Erro ao carregar usuários: {e}")
        return []

def carregar_pedidos():
    try:
        dados = []
        inicio = 0
        tamanho_pagina = 1000

        while True:
            response = (
                supabase.table("pedidos")
                .select("*")
                .order("id", desc=False)
                .range(inicio, inicio + tamanho_pagina - 1)
                .execute()
            )
            lote = response.data or []
            dados.extend(lote)
            if len(lote) < tamanho_pagina:
                break
            inicio += tamanho_pagina
    except Exception as e:
        st.error(f"Erro ao carregar pedidos: {e}")
        return pd.DataFrame()

    if not dados:
        return pd.DataFrame()

    df = pd.DataFrame(dados)

    if "hora_extra" not in df.columns:
        df["hora_extra"] = False
    else:
        df["hora_extra"] = df["hora_extra"].fillna(False).astype(bool)

    if "observacao" not in df.columns:
        df["observacao"] = ""
    else:
        df["observacao"] = df["observacao"].fillna("")

    dt_utc = pd.to_datetime(df["created_at"], format="ISO8601", utc=True, errors="coerce")
    df["Data_Hora"] = dt_utc.dt.tz_convert(FUSO_BR)
    df["Apenas_Data"] = df["Data_Hora"].dt.date

    def calcular_mes_competencia(data):
        if pd.isna(data):
            return ""
        if data.day > 20:
            if data.month == 12:
                return f"01/{data.year + 1}"
            return f"{data.month + 1:02d}/{data.year}"
        return data.strftime("%m/%Y")

    df["Mes_Ano"] = df["Data_Hora"].apply(calcular_mes_competencia)
    df["Hora_Fomatada"] = df["Data_Hora"].dt.strftime("%H:%M").fillna("")
    return df

def salvar_pedido(nome, itens, observacao, total, hora_extra):
    novo_pedido = {
        "nome": nome,
        "itens": itens,
        "observacao": observacao,
        "total": total,
        "hora_extra": hora_extra,
    }
    res = supabase.table("pedidos").insert(novo_pedido).execute()
    return res.data

# --- FUNÇÕES AUXILIARES ---
def remover_acentos(texto):
    if pd.isna(texto):
        return ""
    return unicodedata.normalize("NFKD", str(texto)).encode("ASCII", "ignore").decode("utf-8")

def gerar_pdf(df, data_str):
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()

    logo_path = None
    for ext in ["png", "jpg", "jpeg"]:
        if os.path.exists(f"adf.{ext}"):
            logo_path = f"adf.{ext}"
            break

    if logo_path:
        pdf.image(logo_path, x=10, y=8, w=30)
        pdf.set_y(40)
    else:
        pdf.set_y(20)

    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 10, f"Relatorio de Pedidos - {data_str}", ln=True, align="C")
    pdf.ln(10)

    # --- Cabeçalho da tabela ---
    pdf.set_font("helvetica", "B", 11)
    pdf.cell(20, 10, "Hora", border=1, align="C")
    pdf.cell(45, 10, "Colaborador", border=1, align="C")
    pdf.cell(65, 10, "Pedido", border=1, align="C")
    pdf.cell(60, 10, "Observacoes", border=1, align="C")
    pdf.ln()

    # --- Conteúdo da tabela ---
    pdf.set_font("helvetica", "", 10)

    col_widths = [20, 45, 65, 60]
    line_height = 5

    def calcular_linhas(pdf_obj, texto, largura_coluna):
        if not texto:
            return 1
        palavras = str(texto).split()
        linhas = 1
        linha_atual = ""
        for palavra in palavras:
            teste_linha = linha_atual + " " + palavra if linha_atual else palavra
            if pdf_obj.get_string_width(teste_linha) > (largura_coluna - 2):
                linhas += 1
                linha_atual = palavra
            else:
                linha_atual = teste_linha
        return max(1, linhas)

    for _, row in df.iterrows():
        hora = str(row["Hora"])
        colab = remover_acentos(row["Colaborador"])
        pedido = remover_acentos(row["Pedido"])
        obs = remover_acentos(row["Observações"])

        linhas_colab = calcular_linhas(pdf, colab, col_widths[1])
        linhas_pedido = calcular_linhas(pdf, pedido, col_widths[2])
        linhas_obs = calcular_linhas(pdf, obs, col_widths[3])

        max_linhas = max(linhas_colab, linhas_pedido, linhas_obs)
        altura_linha = max_linhas * line_height

        if pdf.get_y() + altura_linha > 275:
            pdf.add_page()

        x_start = pdf.get_x()
        y_start = pdf.get_y()

        pdf.rect(x_start, y_start, col_widths[0], altura_linha)
        pdf.set_xy(x_start, y_start)
        pdf.multi_cell(col_widths[0], line_height, hora, align="C")

        x_atual = x_start + col_widths[0]
        pdf.rect(x_atual, y_start, col_widths[1], altura_linha)
        pdf.set_xy(x_atual, y_start)
        pdf.multi_cell(col_widths[1], line_height, colab)

        x_atual += col_widths[1]
        pdf.rect(x_atual, y_start, col_widths[2], altura_linha)
        pdf.set_xy(x_atual, y_start)
        pdf.multi_cell(col_widths[2], line_height, pedido)

        x_atual += col_widths[2]
        pdf.rect(x_atual, y_start, col_widths[3], altura_linha)
        pdf.set_xy(x_atual, y_start)
        pdf.multi_cell(col_widths[3], line_height, obs)

        pdf.set_xy(x_start, y_start + altura_linha)

    return bytes(pdf.output())

# --- INTERFACE DO STREAMLIT ---
st.set_page_config(page_title="Sistema de Pedidos", page_icon="🍔", layout="wide")
st.title("🍔 Sistema de Pedidos - Almoço")

lista_usuarios = carregar_usuarios()

aba_pedidos, aba_restaurante, aba_fechamento, aba_funcionarios = st.tabs([
    "🛒 Fazer Pedido",
    "🍽️ Relatório Diário",
    "💰 Fechamento Mensal",
    "👥 Funcionários",
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
            quantidades[item] = st.number_input(
                f"Qtd {item}", min_value=0, value=0, step=1, label_visibility="collapsed"
            )

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
                try:
                    inserido = salvar_pedido(
                        nome_usuario, itens_texto, observacao, float(valor_total), is_hora_extra
                    )
                    if inserido:
                        st.success(f"Pedido registrado com sucesso, {nome_usuario}!")
                    else:
                        st.warning("A requisição foi enviada, mas o banco não confirmou o registro.")
                except Exception as e:
                    st.error(f"Erro ao salvar pedido: {e}")

# --- ABA 2: RELATÓRIO DIÁRIO ---
with aba_restaurante:
    st.header("Envio para o Restaurante")
    st.divider()
    df_pedidos = carregar_pedidos()

    if not df_pedidos.empty:
        datas_validas = [d for d in df_pedidos["Apenas_Data"].dropna().unique()]
        data_padrao = max(datas_validas) if datas_validas else datetime.now(FUSO_BR).date()

        data_escolhida = st.date_input(
            "Escolha o dia para gerar o relatório:",
            value=data_padrao,
            format="DD/MM/YYYY",
        )

        df_dia = df_pedidos[df_pedidos["Apenas_Data"] == data_escolhida].copy()

        if not df_dia.empty:
            df_restaurante = df_dia[["Hora_Fomatada", "nome", "itens", "observacao"]].copy()
            df_restaurante.columns = ["Hora", "Colaborador", "Pedido", "Observações"]
            st.dataframe(df_restaurante, use_container_width=True, hide_index=True)

            pdf_bytes = gerar_pdf(df_restaurante, data_escolhida.strftime("%d/%m/%Y"))
            st.download_button(
                "📄 Baixar Relatório PDF",
                data=pdf_bytes,
                file_name=f"Relatorio_{data_escolhida.strftime('%d_%m_%Y')}.pdf",
                mime="application/pdf",
            )

            st.divider()
            st.subheader("🗑️ Apagar Registro do Dia")

            if "id" in df_dia.columns:
                opcoes_apagar = {}
                for _, row in df_dia.iterrows():
                    texto_exibicao = f"{row['Hora_Fomatada']} - {row['nome']} ({row['itens']})"
                    opcoes_apagar[texto_exibicao] = row["id"]

                pedido_selecionado = st.selectbox(
                    "Selecione o pedido que deseja remover:",
                    [""] + list(opcoes_apagar.keys()),
                )

                if st.button("Apagar Pedido Selecionado"):
                    if pedido_selecionado:
                        id_para_apagar = opcoes_apagar[pedido_selecionado]
                        try:
                            supabase.table("pedidos").delete().eq("id", id_para_apagar).execute()
                            st.success("Pedido apagado com sucesso! A página será atualizada.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao apagar pedido: {e}")
                    else:
                        st.warning("Por favor, selecione um pedido na lista para apagar.")
            else:
                st.error("A coluna 'id' não foi encontrada. Verifique a estrutura da sua tabela no Supabase.")
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
        meses_disponiveis = [m for m in df_pedidos["Mes_Ano"].unique().tolist() if m]
        mes_selecionado = st.selectbox("Selecione o Mês:", meses_disponiveis)
        df_mes = df_pedidos[df_pedidos["Mes_Ano"] == mes_selecionado].copy()

        df_mes["Total Funcionário"] = df_mes.apply(
            lambda row: row["total"] if not row["hora_extra"] else 0.0, axis=1
        )
        df_mes["Total Hora Extra"] = df_mes.apply(
            lambda row: row["total"] if row["hora_extra"] else 0.0, axis=1
        )

        st.subheader(f"Total a cobrar - {mes_selecionado}")
        resumo = df_mes.groupby("nome")[["Total Funcionário", "Total Hora Extra"]].sum().reset_index()

        resumo_excel = resumo.copy()
        resumo_excel.rename(columns={"nome": "Colaborador"}, inplace=True)

        resumo["Total Funcionário"] = resumo["Total Funcionário"].apply(lambda x: f"R$ {x:.2f}")
        resumo["Total Hora Extra"] = resumo["Total Hora Extra"].apply(lambda x: f"R$ {x:.2f}")
        resumo.rename(columns={"nome": "Colaborador"}, inplace=True)
        st.table(resumo)

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            resumo_excel.to_excel(writer, index=False, sheet_name="Fechamento")

        st.download_button(
            label="📥 Baixar Tabela em Excel",
            data=buffer.getvalue(),
            file_name=f"Fechamento_{mes_selecionado.replace('/', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.divider()
        st.subheader("Auditoria por Colaborador")
        pessoa_selecionada = st.selectbox(
            "Selecione a pessoa para ver detalhes:", ["Todos"] + df_mes["nome"].unique().tolist()
        )
        df_mes["Hora_Extra?"] = df_mes["hora_extra"].apply(lambda x: "Sim" if x else "Não")
        df_auditoria = df_mes[["Apenas_Data", "nome", "itens", "observacao", "Hora_Extra?", "total"]].copy()
        df_auditoria.columns = ["Data", "Nome", "Pedido", "Observações", "Hora Extra?", "Valor (R$)"]

        if pessoa_selecionada != "Todos":
            df_auditoria = df_auditoria[df_auditoria["Nome"] == pessoa_selecionada]
        st.dataframe(df_auditoria, use_container_width=True, hide_index=True)

        buffer_auditoria = io.BytesIO()
        with pd.ExcelWriter(buffer_auditoria, engine="openpyxl") as writer:
            df_auditoria.to_excel(writer, index=False, sheet_name="Auditoria")

        nome_pessoa = "Todos" if pessoa_selecionada == "Todos" else pessoa_selecionada.replace(" ", "_")
        nome_arquivo_aud = f"Auditoria_{nome_pessoa}_{mes_selecionado.replace('/', '_')}.xlsx"

        st.download_button(
            label="📥 Baixar Auditoria em Excel",
            data=buffer_auditoria.getvalue(),
            file_name=nome_arquivo_aud,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
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
                try:
                    res = supabase.table("usuarios").insert(
                        {"nome": novo_nome, "senha": "123", "is_admin": False}
                    ).execute()
                    if res.data:
                        st.success("Usuário adicionado! A página vai recarregar.")
                        st.rerun()
                    else:
                        st.warning("Não foi possível inserir o usuário (verifique permissões/RLS no Supabase).")
                except Exception as e:
                    st.error(f"Erro ao adicionar usuário: {e}")
            else:
                st.warning("Preencha o nome.")

    with col_edit:
        st.subheader("Excluir Funcionário")
        user_excluir = st.selectbox("Selecione quem excluir:", [""] + lista_usuarios)
        if st.button("Excluir Usuário"):
            if user_excluir:
                try:
                    supabase.table("usuarios").delete().eq("nome", user_excluir).execute()
                    st.success("Excluído com sucesso!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao excluir usuário: {e}")
