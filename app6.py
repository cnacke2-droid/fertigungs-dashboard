import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import plotly.graph_objects as go
import os

# --- KONFIGURATION ---
st.set_page_config(page_title="Fertigungs-Intelligence Dashboard", layout="wide")

# --- HILFSFUNKTIONEN ---
KNOWN_MANUFACTURERS = [
    "Pokolm", "Rineck", "Dormer", "Precitool", "Nine9", "Garant", 
    "Hoffmann", "Seco", "Sandvik", "Iscar", "Walter", "Kennametal", 
    "Fraisa", "Gühring", "Heidenhain", "Renishaw", "Haimer"
]

OPERATIONS_MAP = {
    "Schruppen": ["schrup", "rough", "planfräsen", "fräsen"],
    "Schlichten": ["schlich", "finish", "restmat", "nachfahr"],
    "Bohren": ["bohr", "zentrier", "senk"],
    "Gewinde": ["gewinde", "m6", "m8", "m10", "m12", "m16"],
    "Fasen": ["fase", "entgrat"],
    "Messen": ["mess", "tast", "probe"]
}

def clean_numeric_column(series):
    s = series.astype(str).str.lower()
    s = s.str.replace(" mm", "", regex=False).str.replace("°", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors='coerce')

def detect_manufacturer(text):
    if not isinstance(text, str): return "Unbekannt"
    text_lower = text.lower()
    for manuf in KNOWN_MANUFACTURERS:
        if manuf.lower() in text_lower: return manuf
    return "Sonstige"

def detect_operation(text_wkz, text_job):
    combined = (str(text_wkz) + " " + str(text_job)).lower()
    for op, keywords in OPERATIONS_MAP.items():
        if any(k in combined for k in keywords): return op
    return "Allgemein"

def create_assembly_name(row):
    parts = [str(row['schneide'])]
    zh = str(row['zwischenhalter'])
    if zh not in ["-", "None", "", "nan", "Unbekannt"]: parts.append(zh)
    parts.append(str(row['grundhalter']))
    return " + ".join(parts)

@st.cache_data
def load_data_from_db(db_path):
    try:
        conn = sqlite3.connect(db_path)
        query = """
        SELECT 
            w.wkz_bez, w.schneide, w.wkz_laufzeit_sec, 
            w.durchmesser, w.eckenradius, w.ausspannlaenge, w.gesamtlänge,
            w.grundhalter, w.zwischenhalter, w.kommentar AS kommentar_wkz,
            d.auftragsnr, d.maschine, d.teil_bezeichnung, 
            d.erstelldatum, d.kommentar AS kommentar_auftrag, d.programmierer
        FROM werkzeug_details w
        LEFT JOIN dokument d ON w.dokument_id = d.dokument_id
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        df['erstelldatum'] = pd.to_datetime(df['erstelldatum'], format='%d.%m.%Y %H:%M', errors='coerce')
        for col in ['durchmesser', 'eckenradius', 'ausspannlaenge', 'gesamtlänge']:
            df[col] = clean_numeric_column(df[col])
        
        df = df.fillna({
            'grundhalter': '-', 'zwischenhalter': '-', 
            'kommentar_wkz': '', 'kommentar_auftrag': '', 
            'schneide': 'Unbekannt', 'maschine': 'Unbekannt',
            'auftragsnr': 'Unbekannt', 'teil_bezeichnung': 'Unbekannt',
            'programmierer': 'Unbekannt'
        })

        df['Laufzeit_h'] = df['wkz_laufzeit_sec'] / 3600.0
        df['Hersteller'] = df.apply(lambda x: detect_manufacturer(x['schneide'] + " " + x['grundhalter']), axis=1)
        df['Prozess'] = df.apply(lambda x: detect_operation(x['kommentar_wkz'], x['kommentar_auftrag']), axis=1)
        df['Assembly'] = df.apply(create_assembly_name, axis=1)
        df['Geometrie_Key'] = "D" + df['durchmesser'].round(1).astype(str) + " R" + df['eckenradius'].round(1).astype(str)
        return df
    except Exception as e:
        st.error(f"Fehler beim Laden: {e}"); return pd.DataFrame()

# --- SIDEBAR ---
st.sidebar.title("🎛️ Steuerung")
uploaded_file = st.sidebar.file_uploader("Datenbank wählen (.db)", type=["db", "sqlite"])

# --- HAUPTANWENDUNG ---
st.title("🏭 Fertigungs-Intelligence & Standardisierung")

if uploaded_file:
    with open("temp.db", "wb") as f: f.write(uploaded_file.getbuffer())
    df = load_data_from_db("temp.db")
    
    if not df.empty:
        # --- FILTER ---
        st.sidebar.divider()
        st.sidebar.write("🔎 **Globale Filter**")
        min_d, max_d = df['erstelldatum'].min(), df['erstelldatum'].max()
        if pd.notnull(min_d):
            sd, ed = st.sidebar.date_input("Zeitraum", [min_d, max_d])
            df = df[(df['erstelldatum'].dt.date >= sd) & (df['erstelldatum'].dt.date <= ed)]
        
        sel_mach = st.sidebar.multiselect("Maschine", sorted(df['maschine'].unique()))
        if sel_mach: df = df[df['maschine'].isin(sel_mach)]

        sel_auftrag = st.sidebar.multiselect("Auftrag", sorted(df['auftragsnr'].unique()))
        if sel_auftrag: df = df[df['auftragsnr'].isin(sel_auftrag)]

        sel_teil = st.sidebar.multiselect("Bauteil", sorted(df['teil_bezeichnung'].unique()))
        if sel_teil: df = df[df['teil_bezeichnung'].isin(sel_teil)]
        
        # KPI HEADER
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Laufzeit Gesamt", f"{df['Laufzeit_h'].sum():.1f} h")
        c2.metric("Anzahl Werkzeugeinsätze", f"{len(df):,}")
        c3.metric("Verschiedene Werkzeuge", df['wkz_bez'].nunique())
        c4.metric("Verschiedene Assemblies", df['Assembly'].nunique())

        # --- TABS ---
        tabs = st.tabs([
            "📊 Übersicht", "💰 Einkaufs-Hebel", "📏 Geometrie-Cluster", 
            "🧩 Baugruppen", "🏭 Magazin-Optimierung", "⚙️ Prozess-Analyse", 
            "📦 Bauteile", "👨‍💻 Programmierer", "📄 Rohdaten"
        ])

        # === TAB 1: ÜBERSICHT ===
        with tabs[0]:
            st.subheader("Top Werkzeuge Analyse")
            c_conf1, c_conf2 = st.columns([1, 3])
            with c_conf1:
                top_n = st.slider("Anzahl Werkzeuge", 5, 100, 20)
            with c_conf2:
                metric_mode = st.radio("Betrachtung nach:", ["Laufzeit (Stunden)", "Anzahl (Verwendungen)"], horizontal=True)

            if metric_mode == "Laufzeit (Stunden)":
                top_w = df.groupby('wkz_bez')['Laufzeit_h'].sum().nlargest(top_n).reset_index().sort_values('Laufzeit_h', ascending=True)
                x_col, color_sc, txt_fmt = 'Laufzeit_h', 'Blues', '.1f'
            else:
                top_w = df['wkz_bez'].value_counts().nlargest(top_n).reset_index()
                top_w.columns = ['wkz_bez', 'Anzahl']
                top_w = top_w.sort_values('Anzahl', ascending=True)
                x_col, color_sc, txt_fmt = 'Anzahl', 'Reds', '.0f'
            
            # Dynamische Höhe berechnen (min 400px, pro Balken 25px)
            dyn_height = max(400, top_n * 25)
            
            fig = px.bar(top_w, x=x_col, y='wkz_bez', orientation='h', 
                         title=f"Top {top_n} nach {metric_mode}",
                         color=x_col, color_continuous_scale=color_sc, text_auto=txt_fmt,
                         height=dyn_height) # <-- HIER: Dynamische Höhe
            st.plotly_chart(fig, use_container_width=True)

        # === TAB 2: EINKAUF ===
        with tabs[1]:
            c1, c2 = st.columns(2)
            m_share = df.groupby('Hersteller')['Laufzeit_h'].sum().sort_values(ascending=False).reset_index()
            c1.plotly_chart(px.bar(m_share, x='Hersteller', y='Laufzeit_h', title="Marktanteil (Laufzeit)"), use_container_width=True)
            
            df['D_Int'] = df['durchmesser'].round(0)
            heat = df.pivot_table(index='Hersteller', columns='D_Int', values='Laufzeit_h', aggfunc='sum', fill_value=0)
            c2.plotly_chart(px.imshow(heat, aspect='auto', title="Heatmap: Hersteller vs. Durchmesser"), use_container_width=True)

        # === TAB 3: GEOMETRIE ===
        with tabs[2]:
            gs = st.selectbox("Geometrie-Cluster (D + R):", sorted(df['Geometrie_Key'].unique()))
            sub = df[df['Geometrie_Key'] == gs]
            st.plotly_chart(px.scatter(sub, x='ausspannlaenge', y='Laufzeit_h', size='Laufzeit_h', color='grundhalter',
                                       hover_data=['wkz_bez'], title=f"Varianz-Check {gs}"), use_container_width=True)

        # === TAB 4: BAUGRUPPEN (ASSEMBLIES) MIT TREEMAP ===
        with tabs[3]:
            st.subheader("Baugruppen-Hierarchie (Treemap)")
            st.info("Klicken Sie in die Kacheln, um hinein zu zoomen (Grundhalter -> Baugruppe).")
            
            # Treemap: Grundhalter -> Assembly -> Werkzeug
            # Wir aggregieren erst, um Performance zu schonen
            tree_ass = df.groupby(['grundhalter', 'Assembly', 'wkz_bez'])['Laufzeit_h'].sum().reset_index()
            tree_ass = tree_ass[tree_ass['Laufzeit_h'] > 0.1] # Filter rauschen
            
            fig_tree_ass = px.treemap(tree_ass, 
                                      path=[px.Constant("Alle Halter"), 'grundhalter', 'Assembly', 'wkz_bez'], 
                                      values='Laufzeit_h',
                                      color='Laufzeit_h', color_continuous_scale='RdBu',
                                      title="Baugruppen-Übersicht (Laufzeit)")
            st.plotly_chart(fig_tree_ass, use_container_width=True)
            
            st.divider()
            st.subheader("Top Liste Assemblies")
            top_ass = df.groupby('Assembly')['Laufzeit_h'].sum().nlargest(20).reset_index()
            st.plotly_chart(px.bar(top_ass, x='Laufzeit_h', y='Assembly', orientation='h'), use_container_width=True)

        # === TAB 5: MAGAZIN OPTIMIERUNG (ERWEITERT) ===
        with tabs[4]:
            st.subheader("Maschinen-Magazin Optimierung")
            
            c_sim1, c_sim2 = st.columns([1, 3])
            with c_sim1:
                sel_m_sim = st.selectbox("Maschine:", sorted(df['maschine'].unique()))
                target_pct = st.slider("Ziel-Abdeckung (%)", 50, 99, 90)
            
            df_mach = df[df['maschine'] == sel_m_sim]
            if not df_mach.empty:
                usage = df_mach.groupby('wkz_bez')['Laufzeit_h'].sum().sort_values(ascending=False).reset_index()
                usage['Kumulativ_%'] = 100 * usage['Laufzeit_h'].cumsum() / usage['Laufzeit_h'].sum()
                usage['Rang'] = usage.index + 1
                
                cut_idx = usage[usage['Kumulativ_%'] <= target_pct].index.max()
                cut_count = usage.loc[cut_idx, 'Rang'] if pd.notnull(cut_idx) else 0
                
                # Pareto Chart mit Hover
                fig_par = go.Figure()
                # Balken (Laufzeit)
                fig_par.add_trace(go.Bar(
                    x=usage['Rang'], y=usage['Laufzeit_h'], name='Laufzeit (h)',
                    text=usage['wkz_bez'], # Werkzeugname im Balken (oder Hover)
                    hovertemplate='<b>%{text}</b><br>Laufzeit: %{y:.1f} h<extra></extra>'
                ))
                # Linie (Prozent)
                fig_par.add_trace(go.Scatter(x=usage['Rang'], y=usage['Kumulativ_%'], name='Abdeckung %', yaxis='y2', mode='lines'))
                
                fig_par.update_layout(
                    title=f"Pareto-Analyse ({target_pct}% Ziel)",
                    xaxis_title="Anzahl Werkzeuge", yaxis=dict(title="Stunden"),
                    yaxis2=dict(title="Abdeckung (%)", overlaying='y', side='right', range=[0, 105]),
                    shapes=[dict(type="line", xref="paper", x0=0, x1=1, yref="y2", y0=target_pct, y1=target_pct, line=dict(color="red", dash="dot"))],
                    hovermode="x unified"
                )
                c_sim2.plotly_chart(fig_par, use_container_width=True)
                
                st.success(f"Sie benötigen **{int(cut_count)} Werkzeuge**, um **{target_pct}%** der Laufzeit abzudecken.")
                
                with st.expander(f"📋 Liste der Stamm-Beladung (Top {int(cut_count)})", expanded=True):
                    st.dataframe(usage.head(int(cut_count))[['Rang', 'wkz_bez', 'Laufzeit_h', 'Kumulativ_%']], use_container_width=True)
            else:
                st.warning("Keine Daten für diese Maschine.")

        # === TAB 6: PROZESS ===
        with tabs[5]:
            st.subheader("Prozess & Konflikte")
            
            # Pivot-Tabelle erstellen
            pivot = df.groupby(['wkz_bez', 'Prozess'])['Laufzeit_h'].sum().unstack(fill_value=0)
            
            # Eine "Total"-Spalte hilft immer beim Sortieren, falls spezifische Spalten fehlen
            pivot['Total'] = pivot.sum(axis=1)
            
            # Bestimme Sortier-Spalte: 
            # Versuche nach "Schruppen" zu sortieren. Wenn nicht da, dann nach "Total".
            sort_col = "Schruppen"
            if sort_col not in pivot.columns:
                sort_col = "Total"
                
            st.write(f"Sortiert nach: **{sort_col}**") # Info für den User
            
            # Anzeige
            st.dataframe(
                pivot.sort_values(sort_col, ascending=False).head(20), 
                use_container_width=True
            )
        # === TAB 7: BAUTEILE (TREEMAP) ===
        with tabs[6]:
            st.subheader("Bauteil & Auftrag Visualisierung")
            st.info("Hierarchie: Auftrag -> Bauteil -> Werkzeug. Farbe = Laufzeit.")
            
            # Treemap Data
            # Wir aggregieren erst, damit Plotly nicht abstürzt bei zu vielen Einzeldaten
            tree_df = df.groupby(['auftragsnr', 'teil_bezeichnung', 'wkz_bez'])['wkz_laufzeit_sec'].sum().reset_index()
            
            fig_tree = px.treemap(tree_df, 
                                  path=[px.Constant("Alle Aufträge"), 'auftragsnr', 'teil_bezeichnung', 'wkz_bez'], 
                                  values='wkz_laufzeit_sec',
                                  color='wkz_laufzeit_sec',
                                  color_continuous_scale='Magma', # Farbschema wie im Beispielbild
                                  title="Laufzeiten pro Bauteil (Interaktiv)")
            
            # Layout Anpassungen für den "Dark Look" aus dem Screenshot
            fig_tree.update_layout(margin=dict(t=50, l=25, r=25, b=25))
            st.plotly_chart(fig_tree, use_container_width=True)
            
            st.divider()
            st.subheader("Detail-Tabelle")
            st.dataframe(df[['auftragsnr', 'teil_bezeichnung', 'wkz_bez', 'Laufzeit_h', 'Prozess']], use_container_width=True)

        # === TAB 8: PROGRAMMIERER ===
        with tabs[7]:
            sel_p = st.selectbox("Programmierer:", sorted(df['programmierer'].unique()))
            sub_p = df[df['programmierer'] == sel_p]
            st.plotly_chart(px.bar(sub_p.groupby('Assembly')['Laufzeit_h'].sum().nlargest(10).reset_index(), 
                                   x='Laufzeit_h', y='Assembly', orientation='h', title="Top Werkzeuge"), use_container_width=True)

        # === TAB 9: ROHDATEN ===
        with tabs[8]:
            st.dataframe(df, use_container_width=True)
    else:
        st.warning("Keine Daten.")
else:
    st.info("Datenbank hochladen.")
