import streamlit as st
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
import pandas as pd
import os
import requests
from io import BytesIO
import seaborn as sns
import matplotlib.pyplot as plt

# Titre de l'application
st.title("📁 Recherche & Analyse depuis Google Drive")
st.write("Sélectionnez un dossier et cherchez des fichiers Excel automatiquement.")


# Fonction d'authentification unique
def authenticate_drive():
    gauth = GoogleAuth()

    if os.path.exists("credentials.json"):
        gauth.LoadCredentialsFile("credentials.json")

    if gauth.credentials is None:
        if os.path.exists("client_secrets.json"):
            try:
                gauth.LoadClientConfigFile("client_secrets.json")
                gauth.LocalWebserverAuth()
                gauth.SaveCredentialsFile("credentials.json")
            except Exception as e:
                st.error(f"❌ Erreur lors de l'authentification : {str(e)}")
                return None
        else:
            st.sidebar.error("❌ client_secrets.json manquant.")
            return None
    elif gauth.access_token_expired:
        gauth.Refresh()
    else:
        gauth.Authorize()

    drive = GoogleDrive(gauth)
    return drive


# Fonction pour lister tous les dossiers racine
def get_root_folders(drive):
    query = "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    file_list = drive.ListFile({'q': query}).GetList()
    return {f['title']: f['id'] for f in file_list}


# Fonction récursive de recherche
def find_files(drive, folder_id, keyword, extension=".xlsx"):
    found_files = []

    def recursive_search(current_folder_id, current_path=""):
        query = f"'{current_folder_id}' in parents and trashed = false"
        file_list = drive.ListFile({'q': query}).GetList()

        for file in file_list:
            file_path = f"{current_path}/{file['title']}"

            if file['mimeType'] == 'application/vnd.google-apps.folder':
                recursive_search(file['id'], file_path)
            else:
                if keyword.lower() in file['title'].lower() and file['title'].endswith(extension):
                    found_files.append({
                        'name': file['title'],
                        'path': file_path,
                        'id': file['id'],
                        'download_url': file.get('downloadUrl')
                    })

    recursive_search(folder_id)
    return found_files


# Fonction de chargement des fichiers Excel
def load_excel_files(drive, files_info):
    dfs = []
    headers = {'Authorization': 'Bearer ' + drive.auth.credentials.access_token}

    for file_info in files_info:
        download_url = file_info['download_url']
        if not download_url:
            st.warning(f"⚠️ Impossible de télécharger {file_info['name']}")
            continue

        try:
            response = requests.get(download_url, headers=headers)
            content = BytesIO(response.content)
            df = pd.read_excel(content)
            dfs.append(df)
        except Exception as e:
            st.warning(f"⚠️ Échec du chargement de {file_info['name']} : {str(e)}")

    return dfs


# Fonction pour charger les données
def load_data(drive, folder_id, keyword, extension=".xlsx"):
    with st.spinner("🔎 Recherche des fichiers..."):
        files_found = find_files(drive, folder_id, keyword, extension)

    if not files_found:
        return None, None

    with st.spinner("📥 Téléchargement des fichiers..."):
        dfs = load_excel_files(drive, files_found)

    final_df = pd.concat(dfs, ignore_index=True)
    return final_df, files_found


# Menu principal
def main():
    st.sidebar.header("🔐 Authentification")

    drive = authenticate_drive()
    if drive is None:
        if st.sidebar.button("🔑 Se connecter à Google Drive"):
            drive = authenticate_drive()
            if drive:
                st.rerun()
        return

    st.sidebar.success("✅ Connecté à Google Drive")

    # Charger les dossiers racine
    with st.spinner("📂 Chargement des dossiers principaux..."):
        root_folders = get_root_folders(drive)

    if not root_folders:
        st.warning("⚠️ Aucun dossier trouvé dans votre Google Drive.")
        return

    selected_folder = st.sidebar.selectbox("📁 Sélectionnez le dossier racine", options=list(root_folders.keys()))
    folder_id = root_folders[selected_folder]

    keyword = st.sidebar.text_input("🔍 Mot-clé à chercher", "tx_curr")
    extension = st.sidebar.selectbox("📄 Extension des fichiers", [".xlsx"])

    if st.sidebar.button("🔎 Lancer la recherche"):
        st.session_state.keyword = keyword
        st.session_state.folder_id = folder_id
        st.session_state.selected_folder = selected_folder
        st.session_state.extension = extension
        st.session_state.run_search = True
        st.rerun()

    if getattr(st.session_state, "run_search", False):
        final_df, files_found = load_data(drive, folder_id, keyword, extension)

        # --- AFFICHAGE DANS LE MENU LATÉRAL ---
        if files_found:
            st.sidebar.info(f"📚 Fichiers trouvés : {len(files_found)}")
            st.sidebar.markdown("**📜 Liste des fichiers :**")
            for file in files_found:
                st.sidebar.markdown(f"- {file['name']}")
        else:
            st.sidebar.error("❌ Aucun fichier trouvé.")

        # --- AFFICHAGE PRINCIPAL ---
        st.subheader(f"🔍 Résultats pour le dossier : `{selected_folder}`")

        if not files_found:
            st.error("❌ Aucun fichier trouvé avec ce mot-clé.")
            return

        st.success(f"✅ {len(files_found)} fichiers trouvés !")

        tab1, tab2, tab3 = st.tabs(["📄 Dataset Combiné", "📊 Analyse descriptive", "💾 Export"])

        with tab1:
            if final_df is not None and not final_df.empty:
                st.markdown("### 🧾 Dimensions du dataset")
                st.markdown(f"**Nombre de lignes :** {len(final_df)} | **Colonnes :** {len(final_df.columns)}")

                st.markdown("### 📋 Aperçu des données")
                st.dataframe(final_df.head(10))
            else:
                st.warning("⚠️ Aucune donnée à afficher.")

        with tab2:
            if final_df is not None and not final_df.empty:
                st.markdown("### 📈 Statistiques descriptives")
                st.write(final_df.describe(include='all'))

                numeric_cols = final_df.select_dtypes(include=['number']).columns
                if len(numeric_cols) > 0:
                    st.markdown("### 📊 Distribution des variables numériques")
                    for col in numeric_cols:
                        # Vérifie que la colonne n'est pas vide et est numérique
                        if pd.api.types.is_numeric_dtype(final_df[col]):
                            fig, ax = plt.subplots(1, 2, figsize=(12, 4))
                            sns.histplot(final_df[col], ax=ax[0], kde=True)
                            sns.boxplot(x=final_df[col], ax=ax[1])
                            st.pyplot(fig)
                        else:
                            st.warning(f"⚠️ La colonne `{col}` n’est pas numérique. Elle sera ignorée pour le boxplot.")
                else:
                    st.info("ℹ️ Aucune variable numérique à visualiser.")
            else:
                st.warning("⚠️ Aucune donnée à analyser.")

        with tab3:
            if final_df is not None and not final_df.empty:
                st.markdown("### 💾 Exporter le dataset combiné")
                export_format = st.radio("Choisissez le format d'export", ("CSV", "Excel"))

                if export_format == "CSV":
                    csv = final_df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 Télécharger en CSV",
                        data=csv,
                        file_name="dataset_combine.csv",
                        mime="text/csv"
                    )
                else:
                    towrite = BytesIO()
                    final_df.to_excel(towrite, index=False, engine='openpyxl')
                    towrite.seek(0)
                    st.download_button(
                        label="📥 Télécharger en Excel",
                        data=towrite,
                        file_name="dataset_combine.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
            else:
                st.warning("⚠️ Aucune donnée à exporter.")


# Lancement de l'app
if __name__ == "__main__":
    main()