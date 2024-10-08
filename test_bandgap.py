import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from io import StringIO
import requests
import re
from bs4 import BeautifulSoup

def auto_detect_linear_region(photon_energy, y, window_size=10, min_y=None):
    best_fit = None
    best_r_squared = -np.inf  # Start with a very low R² value
    best_metrics = None       # Store the best fit quality metrics
    band_gap = None

    for i in range(len(photon_energy) - window_size):
        # Select a window of data for fitting
        x_fit = photon_energy[i:i + window_size]
        y_fit = y[i:i + window_size]

        # If a minimum y value is set, check if the window's y values meet the requirement
        if min_y is not None and np.any(y_fit < min_y):
            continue  # Skip this window if any y value is below the threshold

        # Perform linear fit
        popt, _ = curve_fit(linear_fit, x_fit, y_fit)
        y_pred = linear_fit(x_fit, *popt)
        residuals = y_fit - y_pred
        ss_res = np.sum(residuals**2)
        ss_tot = np.sum((y_fit - np.mean(y_fit))**2)
        r_squared = 1 - (ss_res / ss_tot)
        
        # Calculate additional metrics: RMSE, MAE
        rmse = np.sqrt(np.mean(residuals**2))
        mae = np.mean(np.abs(residuals))

        band_gap_energy = -popt[1] / popt[0]

        # Track the best fitting region with the highest R² value
        if r_squared > best_r_squared:
            best_r_squared = r_squared
            best_fit = (x_fit, y_fit, popt)
            band_gap = band_gap_energy
            # Store the best metrics
            best_metrics = {
                'R²': r_squared,
                'RMSE': rmse,
                'MAE': mae,
                'Residuals': residuals
            }

    # Return the best fit and associated metrics
    return best_fit, best_metrics, band_gap

# Define the Tauc plot fitting function (for linear region)
def linear_fit(x, m, c):
    return m * x + c

# Kubelka-Munk function for reflectance data
def kubelka_munk(reflectance):
    return (1 - reflectance)**2 / (2 * reflectance)

# Inverse Kubelka-Munk function for calculating absorbance
def inverse_kubelka_munk(alpha):
    return 1 - np.sqrt(1 + 4 * alpha) / 2

# File loading function
def load_data(uploaded_file, file_type):
    if file_type == "csv":
        return pd.read_csv(uploaded_file)
    elif file_type == "xlsx":
        return pd.read_excel(uploaded_file)
    elif file_type == "txt":
        return pd.read_csv(uploaded_file, delimiter='\t')  # Assuming tab-delimited txt file

# Export data to CSV
def export_to_csv(wavelength, absorbance, reflectance, transmittance, photon_energy, y, x_fit, y_fit, band_gap):
    df = pd.DataFrame({
        'Wavelength (nm)': wavelength,
        'Absorbance': absorbance,
        'Reflectance': reflectance,
        'Transmittance': transmittance,
        'Photon Energy (eV)': photon_energy,
        'Tauc Plot Value': y,
        'Fitted Photon Energy (eV)': np.concatenate([x_fit, np.full(len(photon_energy) - len(x_fit), np.nan)]),
        'Fitted Tauc Plot Value': np.concatenate([y_fit, np.full(len(photon_energy) - len(y_fit), np.nan)]),
        'Band Gap (eV)': [band_gap] * len(photon_energy)
    })
    csv = df.to_csv(index=False)
    return csv

# Export data to TXT
def export_to_txt(photon_energy, y, x_fit, y_fit, band_gap):
    output = StringIO()
    output.write("Photon Energy (eV),Tauc Plot Value,Fitted Photon Energy (eV),Fitted Tauc Plot Value,Band Gap (eV)\n")

    # Convert pandas Series to lists for safe indexing
    photon_energy_list = photon_energy.tolist()
    y_list = y.tolist()
    x_fit_list = x_fit.tolist()
    y_fit_list = y_fit.tolist()

    max_length = max(len(photon_energy_list), len(x_fit_list))  # Ensure enough rows for all data

    for i in range(max_length):
        photon_energy_value = photon_energy_list[i] if i < len(photon_energy_list) else ''
        y_value = y_list[i] if i < len(y_list) else ''
        x_fit_value = x_fit_list[i] if i < len(x_fit_list) else ''
        y_fit_value = y_fit_list[i] if i < len(y_fit_list) else ''
        output.write(f"{photon_energy_value},{y_value},{x_fit_value},{y_fit_value},{band_gap}\n")

    txt = output.getvalue()
    return txt

# Function to extract band gap values using regex
def extract_band_gap(text):
    # Regular expression to find values followed by "eV" and their positions
    pattern = re.compile(r'(\d+\.?\d*)\s*(eV|electron\s*volts|ev|e\.v\.|e\.v)\b', re.IGNORECASE)
    matches = pattern.finditer(text)
    
    results = []
    
    for match in matches:
        value = float(match.group(1))
        value_start = match.start()
        
        # Check the context around the value
        context = text[max(0, value_start - 100):min(len(text), value_start + 100)].lower()
        
        # Check if "band gap", "bandgap", or "band-gap" is within 8 words of the value
        if any(term in context for term in ['band gap', 'bandgap', 'band-gap']):
            # Ensure it's within 8 words
            context_words = re.findall(r'\b\w+\b', context)
            value_index = context_words.index(match.group(2).lower()) - 1
            band_gap_index = None
            
            # Look for "band gap", "bandgap", or "band-gap" within 8 words
            for i, word in enumerate(context_words):
                if word in ['band', 'gap', 'bandgap', 'band-gap']:
                    if abs(i - value_index) <= 8:
                        band_gap_index = i
                        break

            if band_gap_index is not None:
                results.append(value)
    
    # Return the first band gap value found or None
    return results[0] if results else None

# Function to fetch full text from a URL (assumes DOI leads to a full-text URL)
def fetch_full_text(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            # Extract text from the soup object, may need to adjust based on the site structure
            text = soup.get_text()
            return text
        #else:
            #st.error("Failed to retrieve full text.")
            #return None
    except Exception as e:
        st.error(f"An error occurred: {e}")
        return None

# Search literature using CrossRef API
def search_literature(common_name): #, chemical_composition, cas_number):
    query = ""
    if common_name:
        query += f"{common_name} "
    #if chemical_composition:
        #query += f"{chemical_composition} "
    #if cas_number:
        #query += f"CAS:{cas_number}"
    
    if not query.strip():
        return None

    search_url = f"https://api.crossref.org/works?query={query}&rows=5"
    response = requests.get(search_url)
    if response.status_code == 200:
        data = response.json()
        items = data.get('message', {}).get('items', [])

        results = []
        for item in items:
            # Extract relevant fields
            title = item.get('title', ['No title available'])[0]
            abstract = item.get('abstract', 'No abstract available')
            doi = item.get('DOI', 'No DOI available')
            full_text_url = f"https://doi.org/{doi}"  # Assuming DOI provides a link to the full text
            
            # Extract band gap value from abstract if possible
            band_gap_value = extract_band_gap(abstract)
            if band_gap_value is None:
                # Fetch and extract band gap value from full text if available
                full_text = fetch_full_text(full_text_url)
                if full_text:
                    band_gap_value = extract_band_gap(full_text)
                
            # Create a DOI link if available
            doi_link = f"[{doi}](https://doi.org/{doi})" if doi != 'No DOI available' else doi

            results.append({
                'title': title,
                #'abstract': abstract,
                'doi_link': doi_link,
                'band_gap': band_gap_value
            })
        
        return results
    else:
        st.error("Error fetching literature data.")
        return None


# Compare user band gap with extracted value
def compare_band_gap(user_band_gap, extracted_band_gap):
    tolerance = 0.1  # e.g., ±0.1 eV for close matches
    extracted_value = float(extracted_band_gap.split()[0])
    if abs(user_band_gap - extracted_value) <= tolerance:
        return True
    return False

# Streamlit app starts here
def main():
    st.title("Band Gap Calculation")

    st.write("""This Streamlit app allows users to upload reflectance or transmittance data in CSV, XLSX, or TXT formats, 
        and calculates the band gap of a semiconductor using the Kubelka-Munk function and Tauc plot method. 
        Users can select wavelength ranges, plot data, and perform linear fitting to estimate the band gap value. 
        Additionally, the app provides a literature review feature to search for band gap values from research articles.
        """)

    # File upload
    uploaded_file = st.file_uploader("Upload your data (CSV, XLSX, or TXT format)", type=["csv", "xlsx", "txt"])

    if uploaded_file is not None:
        # Detect the file type based on the extension
        file_type = uploaded_file.name.split('.')[-1].lower()

        # Load the data using the appropriate pandas function
        if file_type in ['csv', 'xlsx', 'txt']:
            data = load_data(uploaded_file, file_type)
        else:
            st.error("Unsupported file format. Please upload a CSV, XLSX, or TXT file.")
            return

        st.write("Data Preview:")
        st.write(data.head())

        # DATA MANIPULATION

        # Clean the data to keep only rows with valid numerical values
        data_cleaned = data.apply(pd.to_numeric, errors='coerce').dropna()

        # Let the user choose which columns to use for wavelength and signal (reflectance/transmittance)
        column1 = st.selectbox("Select Column 1 (Wavelength in nm):", data_cleaned.columns)
        column2 = st.selectbox("Select Column 2 (Reflectance or Transmittance):", data_cleaned.columns)

        # Clean the selected columns to keep only rows with numerical data
        wavelength = pd.to_numeric(data_cleaned[column1].astype(str).str.replace(',', ''), errors='coerce')
        signal = pd.to_numeric(data_cleaned[column2].astype(str).str.replace(',', ''), errors='coerce')

        # Add sliders for wavelength range selection
        min_wavelength = float(wavelength.min())
        max_wavelength = float(wavelength.max())
        selected_range = st.slider("Select Wavelength Range (nm):", min_value=min_wavelength, max_value=max_wavelength, value=(min_wavelength, max_wavelength))

        # Filter the data based on the selected range
        data_filtered = data_cleaned[(data_cleaned[column1] >= selected_range[0]) & (data_cleaned[column1] <= selected_range[1])]

        if data_filtered.empty:
            st.error("No data available in the selected wavelength range.")
            return

        # Display cleaned data with headers
        #st.write("Cleaned Data Preview:")
        #st.write(data_filtered.head())

        wavelength = data_filtered[column1]
        signal = data_filtered[column2]

        # Let the user choose the mode of the data (Reflectance or Transmittance)
        mode = st.selectbox("Select Data Mode", ["Reflectance", "Transmittance"])

        if mode == "Reflectance":
            reflectance = signal
            # Apply Kubelka-Munk transformation for reflectance data
            alpha = kubelka_munk(signal)
            # Calculate absorbance using the inverse Kubelka-Munk function
            absorbance = inverse_kubelka_munk(alpha)
            transmittance = 1 - reflectance
            #st.write("Reflectance data detected. Applying Kubelka-Munk transformation.")

        elif mode == "Transmittance":
            # Apply transmittance to absorbance conversion
            transmittance = signal / 100 if signal.max() > 1 else signal  # Convert to fraction if in %
            reflectance = 1 - transmittance
            alpha = kubelka_munk(reflectance) 
            absorbance = inverse_kubelka_munk(alpha) 
            #st.write("Transmittance data detected. Converting to absorbance using A = -log(T).")

        # Convert Wavelength to photon energy (hν in eV)
        h = 4.135667696e-15  # Planck's constant in eV·s
        c = 3e8              # Speed of light in m/s
        photon_energy = (h * c) / (wavelength * 1e-9)  # Convert wavelength from nm to m
        
        # Tauc plot (direct or indirect transition)
        transition_type = st.selectbox("Select the type of electronic transition", ("Direct", "Indirect"))

        if transition_type == "Direct":
            y = (alpha * photon_energy)**2
        else:
            y = np.sqrt(alpha * photon_energy)

        # DATA VISUALISATION

        st.header("Plots")
        fig, axs = plt.subplots(2, 2, figsize=(10, 10))
        axs = axs.flatten()

        # Plot Reflectance Spectrum
        axs[0].plot(wavelength, transmittance, label="Transmittance")
        axs[0].set_xlabel('Wavelength')
        axs[0].set_ylabel("Transmittance")
        axs[0].legend()
        axs[0].set_title("Transmittance Spectrum:")

        # Plot Reflectance Spectrum
        axs[1].plot(wavelength, reflectance, label='Reflectance', color='black')
        axs[1].set_xlabel('Wavelength')
        axs[1].set_ylabel('Reflectance')
        axs[1].legend()
        axs[1].set_title("Reflectance Spectrum:")

        # Plot Absorbance Spectrum
        axs[2].plot(wavelength, absorbance, label='Absorbance', color='orange')
        axs[2].set_xlabel('Wavelength')
        axs[2].set_ylabel('Absorbance')
        axs[2].legend()
        axs[2].set_title("Absorbance Spectrum:")

        # Tauc Plot
        axs[3].plot(photon_energy, y, label=f'Tauc Plot ({transition_type})')
        axs[3].set_xlabel('Photon Energy (eV)')
        axs[3].set_ylabel(r'$(\alpha h\nu)^n$')
        axs[3].legend()
        axs[3].set_title("Tauc Plot:")

        plt.tight_layout()
        st.pyplot(fig)

        # Linear region selection
        st.header("Linear Region Fitting")
        st.write("Select the energy range for the linear region fitting:")
        x_min = st.number_input("Minimum energy (eV):", min_value=float(photon_energy.min()), max_value=float(photon_energy.max()), value=float(photon_energy.min()))
        x_max = st.number_input("Maximum energy (eV):", min_value=float(photon_energy.min()), max_value=float(photon_energy.max()), value=float(photon_energy.max()))

        # Select the linear region data
        mask = (photon_energy >= x_min) & (photon_energy <= x_max)
        x_fit = photon_energy[mask]
        y_fit = y[mask]

        # Perform linear fit
        popt, _ = curve_fit(linear_fit, x_fit, y_fit)

        # Plot the linear fit
        st.write("Linear Fit on the Selected Region:")
        fig, ax = plt.subplots()
        ax.plot(photon_energy, y, label=f'Tauc Plot ({transition_type})')
        ax.plot(x_fit, linear_fit(x_fit, *popt), 'r--', label='Linear Fit')
        ax.set_xlabel('Photon Energy (eV)')
        ax.set_ylabel(r'$(\alpha h\nu)^n$')
        plt.legend()
        st.pyplot(fig)

        # Extrapolate to find band gap
        band_gap = -popt[1] / popt[0]
        st.write(f"Estimated Band Gap: {band_gap:.2f} eV")

        # Prepare data for export
        csv_data = export_to_csv(wavelength, absorbance, reflectance, transmittance, photon_energy, y, x_fit, y_fit, band_gap)
        #txt_data = export_to_txt(photon_energy, y, x_fit, y_fit, band_gap)

        # Provide download links
        st.download_button(
            label="Download CSV",
            data=csv_data,
            file_name="band_gap_results.csv",
            mime="text/csv"
        )

        #st.download_button(
            #label="Download TXT",
            #data=txt_data,
            #file_name="band_gap_results.txt",
            #mime="text/plain"
        #)

        # Automatically detect linear region for fitting
        st.title("Automatic Linear Region Detector [Beta]")
        st.write("This beta feature detects the most linear region for the user and gives an estimation of the band gap based on the best linear fitting.")

        # Call the function to detect the linear region
        best_fit, best_metrics, band_gap = auto_detect_linear_region(photon_energy, y, min_y=2.5)

        if best_fit is None or best_metrics is None:
            st.write("No suitable linear region detected.")
            return

        # Unpack the best fit values
        x_fit, y_fit, popt = best_fit

        # Plot the original data and the best linear fit
        fig, ax = plt.subplots()
        ax.plot(photon_energy, y, label=f'Tauc Plot')
        ax.plot(x_fit, linear_fit(x_fit, *popt), label='Best Linear Fit')
        ax.set_xlabel('Photon Energy (eV)')
        ax.set_ylabel(r'$(\alpha h\nu)^n$')
        plt.legend()
        st.pyplot(fig)

        # Display the estimated band gap
        st.metric("Estimated Band Gap (eV)", f"{band_gap:.2f}")

        # Display the metrics
        st.header("Fit Quality Metrics:")
        st.write(f"R² Value: {best_metrics['R²']:.4f}")
        st.write(f"RMSE: {best_metrics['RMSE']:.4f}")
        st.write(F"MAE: {best_metrics['MAE']:.4f}")
        st.write(f"Residuals: {best_metrics['Residuals']}")

        # LITERATURE REVIEW
        
        # Add literature benchmark feature
        st.title("Quick and Dirty Literature Review [Beta]")
        st.write("Beta feature, the band gap values are shown only for opensource journals with webpage view, otherwise the user should open the DOI.")
        common_name = st.text_input("Enter common name of the material:")
        #chemical_composition = st.text_input("Enter chemical composition:")
        #cas_number = st.text_input("Enter CAS number (optional):")

        if st.button("Search Literature"):
            if common_name: 
                results = search_literature(common_name)
            if results:
                st.write("Literature Search Results:")
                for item in results:
                    title = item.get('title', 'No title available')
                    #abstract = item.get('abstract', 'No abstract available')
                    doi_link = item.get('doi_link', 'No DOI available')
                    band_gap_value = item.get('band_gap', 'No band gap value found')

                    st.write(f"Title: {title}")
                    #st.write(f"Abstract: {abstract[:500]}...")  # Display a snippet of the abstract
                    st.write(f"DOI: {doi_link}")
                    st.write(f"Band Gap: {band_gap_value if band_gap_value != 'No band gap value found' else 'Not available'}")

                    st.write("---")
            else:
                st.write("No results found.")

if __name__ == "__main__":
    main()