"""
Allocate photovoltaic generators on a distribution network.

Generates interpolated irradiance/temperature profiles from weather station data
and produces a corresponding OpenDSS script file for time-series power flow.
"""

__version__ = "1.0.0"
# ==============================================================================
# USER ADAPTATION GUIDE
# ==============================================================================
#
# To apply this script to a different distribution network or dataset, follow the
# steps below and adjust the constants in the "Simulation Control Variables" and
# "Paths Configurations" sections accordingly.
#
# 1. DISTRIBUTION NETWORK
#    - Replace the circuit file: set SCRIPT_DSS to the path of your OpenDSS master
#      script (e.g., 'path/to/your_circuit.dss').
#    - Ensure the circuit has buses with purely numeric names (e.g., '650', '646').
#      Buses with non‑digit names are automatically ignored during mapping.
#
# 2. WEATHER STATION DATA
#    - The script expects a directory (SOLAR_STATION_FILES) containing one CSV file
#      per solar station, named exactly as specified in the metadata (e.g., 'station_01.csv').
#    - Each CSV must have at least the following columns (with exactly these names):
#        * datetime               : timestamp string (e.g., '2026-01-01 00:00:00')
#        * poa_irradiance_wm2     : plane‑of‑array irradiance (W/m²)
#        * panel_temperature_celsius : PV panel temperature (°C)
#    - The metadata file (INFO_PV_FILE) is a CSV with at least the columns:
#        * id                     : station identifier (used to build the CSV file name)
#        * nominal_power_mw       : reference installed capacity (MW) for each station
#      Additional columns can be present but will be ignored by the current code.
#
# 3. SIMULATION PREFERENCES
#    - t_simulation : total simulation length (minutes). The code assumes the weather
#      data has a 15‑minute native resolution and calculates the required number of
#      points automatically (npts_origin).
#    - step : desired output time step (Pandas offset alias, e.g., '5min', '1h', '30s').
#    - start_date : start date/time for the interpolated output series. Must be a
#      string compatible with Pandas (e.g., "2026-01-01 00:00:00").
#    - my_seed : random seed for reproducible bus sampling.
#
# 4. OUTPUT LOCATION
#    - OUTPUT_DIR : directory where the generated CSVs and DSS file will be saved.
#      It must already exist.
#    - OUTPUT_IRRAD_CSV, OUTPUT_TEMP_CSV, OUTPUT_DSS_FILE : output file names.
#      You can change them, but keep the .csv and .dss extensions respectively.
#
# 5. PV ALLOCATION (inside the 'if __name__ == "__main__":' block)
#    - QtdPVs : number of PV generators to randomly install on available buses.
#    - PV_Dictionaries : list of dictionaries with manual PV definitions.
#      Each dictionary accepts:
#        'PV_phases' : 1 or 3 (2‑phase entries are automatically reduced to 1‑phase)
#        'PV_bus'    : bus name with nodes (e.g., '646.2.3')
#        'PV_kv'     : voltage (kV) – optional, will be calculated if missing
#        'PV_kva'    : capacity (kVA) – optional, will use metadata if missing
#        'PV_curve_id' : solar curve ID (1‑51, or None to use the station's position)
#    - ignore_buses : list (or single string) of base bus numbers to exclude from
#      random allocation.
#    - bus_multi_PV : set to True if you want to allow multiple PVs on the same bus.
#
# 6. DEPENDENCIES
#    - pandas, py_dss_interface, pathlib, math, random (all standard or easily installed).
#    - The script also uses the logging module (configured at the top).
#
# After adjusting the constants and the main block execution call, simply run:
#    python pv_creator.py



# ==============================================================================
# LIBRARY IMPORTS & CONSTANTS
# ==============================================================================
# --- Library Imports ---
from unittest import case

from unittest import case

import pandas as pd              # Data manipulation and CSV file handling
import py_dss_interface          # Python interface for OpenDSS (EPRI)
import logging                   # Logging for debugging and information output
from pathlib import Path         # Object-oriented filesystem paths
from math import ceil            # Ceiling function to calculate total simulation points
from random import choice, seed  # Random node selection and reproducibility seeding

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s]: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- Simulation Control Variables ---
t_simulation = 24 * 60 * 1              # Total simulation time in minutes
npts_origin = ceil(t_simulation/15)     # Original data points (15-min base)
step = '5min'                           # Target simulation time step (e.g., '5s', '5min', '2h')
start_date = "2026-01-01 00:00:00"      # Target simulation start timestamp for the final outputs 
my_seed = 25                            # Seed for reproducibility of random bus sampling

# --- Paths Configurations ---
BASE_DIR = Path(".").resolve()
INFO_PV_FILE = BASE_DIR/'src'/'data'/'InfoPV'/'power_station_metadata.csv'
SOLAR_STATION_FILES = BASE_DIR/'src'/'data'/'InfoPV'/'solar_station'
SCRIPT_DSS = BASE_DIR/'src'/'data'/'13Bus'/'IEEE13Nodeckt.dss'
OUTPUT_DIR = BASE_DIR/'src'/'data'/'13Bus'
OUTPUT_IRRAD_CSV = OUTPUT_DIR/'ieee13_shape_pv_5min.csv'
OUTPUT_TEMP_CSV = OUTPUT_DIR/'ieee13_temperature_5min.csv'
OUTPUT_DSS_FILE = OUTPUT_DIR/'ieee13_pv.dss'

# --- Paths And Files Validation ---
print("")
logger.info("--- STARTING PATHS AND FILES VALIDATION ---")
print("")
logger.info("Validating project structure and workspace paths...")

# Validate Critical Input Files
if not INFO_PV_FILE.is_file():
    raise FileNotFoundError(f"Critical input file missing: '{INFO_PV_FILE}'\n"
                            f"Check the database or metadata path.")
if not SCRIPT_DSS.is_file():
    raise FileNotFoundError(f"Circuit baseline script missing: '{SCRIPT_DSS}'\n"
                            f"OpenDSS simulation cannot compile without this file.")
# Validate Input Directory
if not SOLAR_STATION_FILES.is_dir():
    raise FileNotFoundError(f"Solar curves directory missing: '{SOLAR_STATION_FILES}'\n"
                            f"Verify if the weather station database was correctly placed.")
# Validate Output Directory Existence
if not OUTPUT_DIR.exists():
    raise FileNotFoundError(f"Required output directory does not exist: '{OUTPUT_DIR}'\n"
                            f"Indicate the correct directory before running.")

logger.info("Success! All critical files and directories validated.")

# --- Global Data Loading And Validation ---
logger.info("Loading and verifying metadata database...")

try:
    # Try to read the CSV file
    PV_LIST_METADATA = pd.read_csv(INFO_PV_FILE)
    
    # Check if the file is structurally empty (e.g., only headers or completely blank)
    if PV_LIST_METADATA.empty:
        raise ValueError(
            f"The metadata file '{INFO_PV_FILE.name}' is empty or contains no data rows."
        )
except FileNotFoundError:
    raise FileNotFoundError(
        f"Critical Error: The file '{INFO_PV_FILE}' was not found.\n"
    )
except pd.errors.EmptyDataError:
    raise EOFError(
        f"Critical Error: The file '{INFO_PV_FILE}' is completely empty (0 bytes) or has no valid headers."
    )
except pd.errors.ParserError:
    raise TypeError(
        f"Critical Error: The file '{INFO_PV_FILE}' is corrupted or poorly formatted.\n"
    )
except Exception as val_err:
    raise RuntimeError(f"Unexpected error while loading metadata: {val_err}")

logger.info(f"Success! Metadata loaded successfully.")

# ==============================================================================
# PV GENERATOR ENTITY (DATA & PROCESSING MODEL)
# ==============================================================================
class PVGenerator:
    """
    Represent and manage time-series curves and electrical parameters for a PV system.

    This class handles loading weather profiles (irradiance and temperature), 
    processing data slicing and normalization, and formatting them for 
    direct injection into OpenDSS simulation scripts.
    """

    # Cache shared across all instances to avoid redundant file loading if multiple PVs use the same curve_id
    _solar_cache = {}

    def __init__(
            self,  
            PV_kv, 
            PV_kva,
            PV_bus:str,
            PV_phases:int,
            PV_id:int, 
            PV_curve_id:int, 
            npts_origin:int, 
            PV_list:pd.DataFrame, 
            start:int=96
            ):
        
        """
        Initializes the PV generator by mapping technical parameters to the solar dataset.

        Args:
            PV_kv (float): Phase voltage at the connection bus.
            PV_kva (float): Installed PV capacity (kVA).
            PV_bus (str): Bus identifier for connection.
            PV_phases (int): Number of phases for the connection.
            PV_id (int): Unique integer ID for generator naming.
            PV_curve_id (int): ID for curve file selection (range 1-51).
            npts_origin (int): Original number of points (15-min resolution).
            PV_list (pd.DataFrame): Metadata DataFrame containing plant information.
            start (int): Starting index for data slicing, skipping previous points.
        """

        # --- CURVE ID CONFIGURATION & VALIDATION ---
        # Set curve_id using PV_id as fallback if curve_id is NaN
        self.curve_id = PV_id if pd.isna(PV_curve_id) else PV_curve_id
        
        # Ensure curve_id remains within the valid dataset range (1 to 51)
        if self.curve_id > 51:
            self.curve_id = int((float(self.curve_id - 1) % 51) + 1)
        elif self.curve_id <= 0:
            logger.warning(f"Input PV id was {PV_curve_id}. Must be >= 1. Defaulting to 1.")
            self.curve_id = 1

        # --- SOLAR CURVE FILE LOADING ---
        # Locate and load the CSV file corresponding to the defined curve_id
        self.curve = PV_list.iloc[self.curve_id-1]['id']
        self.FILE_CSV = self.curve + '.csv'
        self.SOLAR_STATION_FILE = SOLAR_STATION_FILES/self.FILE_CSV

        # Verify if the curve data for this specific curve_id is already loaded in the class cache to avoid redundant file reads
        if self.FILE_CSV not in PVGenerator._solar_cache:
            try:
                PVGenerator._solar_cache[self.FILE_CSV] = pd.read_csv(self.SOLAR_STATION_FILE)
            except FileNotFoundError:
                raise FileNotFoundError(f"Error: Dataset file {self.SOLAR_STATION_FILE} not found.")
        
        # Copy the loaded curve data from the class cache to the instance variable for processing
        self.solar_station_curves = PVGenerator._solar_cache[self.FILE_CSV].copy()

        # --- BASIC PV ATTRIBUTES ---
        # Naming, phase count, bus connection, voltage, and capacity
        self.name = 'PV'+str(PV_id)
        self.phases = PV_phases
        self.bus = PV_bus
        self.kv = PV_kv
        
        inversores_1f_BT = pd.Series([1, 1.5, 2, 2.5, 3, 3.6, 4, 5, 6, 7, 7.5, 8, 9, 10])
        inversores_3f_BT = pd.Series([4, 5, 6, 8, 10, 12, 15, 17, 20, 25, 27, 30, 33, 36, 40, 45, 50, 60, 75])
        inversores_3f_MT = pd.Series([12, 15, 17, 20, 25, 27, 30, 33, 36, 40, 50, 75, 100, 110, 125, 150, 220, 250, 330, 350])

        if pd.isna(PV_kva):
            match (self.phases):
                case (1) if self.kv <= 1.0:
                    self.kva = (choice(inversores_1f_BT.tolist()))
                case (1) if self.kv > 1.0:
                    self.kva = (choice(inversores_1f_BT.tolist()))
                case (3) if self.kv <= 1.0:
                    self.kva = (choice(inversores_3f_BT.tolist()))
                case (3) if self.kv > 1.0:
                    self.kva = (choice(inversores_3f_MT.tolist()))
                case _:
                    raise ValueError(f"Número de fases inválido ({self.phases}) para o PV {self.name}. Deve ser 1 ou 3.")
        else:
            match (self.phases):
                case (1) if self.kv <= 1.0:
                    valor_comercial = inversores_1f_BT.iloc[(inversores_1f_BT - PV_kva).abs().idxmin()]
                    self.kva = valor_comercial  
                case (1) if self.kv > 1.0:
                    valor_comercial = inversores_1f_BT.iloc[(inversores_1f_BT - PV_kva).abs().idxmin()]
                    self.kva = valor_comercial      
                case (3) if self.kv <= 1.0:
                    valor_comercial = inversores_3f_BT.iloc[(inversores_3f_BT - PV_kva).abs().idxmin()]
                    self.kva = valor_comercial   
                case (3) if self.kv > 1.0:
                    valor_comercial = inversores_3f_MT.iloc[(inversores_3f_MT - PV_kva).abs().idxmin()]
                    self.kva = valor_comercial
                case _:
                    raise ValueError(f"Número de fases inválido ({self.phases}) para o PV {self.name}. Deve ser 1 ou 3.")
    
        self.irrad = 0.8 * 1000
        self.pmpp = self.kva
        self.temperature = 25
        self.pf = 1
        self.vminpu = 0.001
        self.model = 1

        # --- EFFICIENCY & POWER CORRECTION CURVES ---
        # Define characteristic curves for inverter efficiency and PV temperature correction
        self.effcurve = 'New XYCurve.MyEff npts=4 xarray=[0.1, 0.2, 0.4, 1.0] yarray=[0.86, 0.90, 0.93, 0.97]'
        self.ptcurve = 'New XYCurve.MyPvsT npts=4 xarray=[0, 25, 75, 100] yarray=[1.2, 1.0, 0.8, 0.6]'

        # --- CURVES PROCESSING ---
        self.npts = npts_origin
        data_slice = slice(start, self.npts + start + 1)
        
        # 1. Process Irradiance (Normalize, clip negatives, fill NaNs)
        self.irrad_curve = (self.solar_station_curves['poa_irradiance_wm2'].iloc[data_slice] / self.irrad).reset_index(drop=True)
        self.irrad_curve = self.irrad_curve.clip(lower=0).fillna(0)
        self.irrad_curve.name = f'my_shape{PV_id}_irrad'

        # 2. Process Temperature (Normalize, fill NaNs)
        self.temperature_curve = (self.solar_station_curves['panel_temperature_celsius'].iloc[data_slice] / self.temperature).reset_index(drop=True)
        self.temperature_curve = self.temperature_curve.fillna(1)
        self.temperature_curve.name = f'my_shape{PV_id}_temperature'

        # 3. Handle Datetime & Indexing
        # Convert timestamp strings to datetime objects and reset index to align (0-based)
        self.datetime = pd.to_datetime(self.solar_station_curves['datetime'].iloc[data_slice]).reset_index(drop=True)

        # Concatenate the datetime column with the curves
        self.irrad_curve = pd.concat([self.datetime, self.irrad_curve], axis=1)
        self.temperature_curve = pd.concat([self.datetime, self.temperature_curve], axis=1)

        # Set 'datetime' as the index. 
        self.irrad_curve = self.irrad_curve.set_index('datetime')
        self.temperature_curve = self.temperature_curve.set_index('datetime')

    def CurveLinearInterpolation(self, new_rate=step, npts_base_15min=npts_origin, start_date=start_date):
        """
        Resamples a time-series curve to a new time frequency using linear interpolation.
    
        Args:
            new_rate (str): Pandas offset alias for the target frequency (e.g., '5s', '5min', '2h').
            npts_base_15min (int): Number of points in the original 15-minute resolution time series.
            start_date (str): Start date/time for the new interpolated timeline (format e.g., "2026-01-01 00:00:00").
        """

        # Define Timedelta parameters natively to handle any scale (seconds, minutes, hours)
        base_delta = pd.Timedelta('15min')
        new_delta = pd.Timedelta(new_rate)
        
        # Calculate expected array size dynamically
        expected_points = ceil(npts_base_15min * (base_delta / new_delta))

        # --- RESAMPLING & LINEAR INTERPOLATION ---
        # 1. resample: Groups data into the new time interval (new_rate)
        # 2. mean: Aggregates clustered points (downsampling) or preserves timestamp anchors (upsampling)
        # 3. interpolate: Fills gaps using time-proportional linear connection
        self.irrad_curve = (self.irrad_curve.resample(new_rate).mean().interpolate(method='time')).round(6)
        self.temperature_curve = (self.temperature_curve.resample(new_rate).mean().interpolate(method='time')).round(6)
        
        # Discard the temporary anchor points using structural slicing
        self.irrad_curve = self.irrad_curve.iloc[:expected_points]
        self.temperature_curve = self.temperature_curve.iloc[:expected_points]

        # Generate a clean sequential timeline starting exactly at START_DATE matching the required points
        new_timeline = pd.date_range(start=start_date, periods=expected_points, freq=new_rate)
        
        # Assign the new timeline back as the dataframe index
        self.irrad_curve.index = new_timeline
        self.temperature_curve.index = new_timeline

        # Reset index to restore numerical indexing and rename 'index' to 'Date'
        self.irrad_curve = self.irrad_curve.reset_index().rename(columns={'index': 'Date'})
        self.temperature_curve = self.temperature_curve.reset_index().rename(columns={'index': 'Date'})

        # ==============================================================================
        # INTERPOLATED DATA INTEGRITY CHECK
        # ==============================================================================
        # Validate expected array sizing
        if len(self.irrad_curve) != expected_points or len(self.temperature_curve) != expected_points:
            raise ValueError(
                f"Data corruption detected in {self.name}: Interpolated array size mismatch.\n"
                f"Expected: {expected_points} points. Got: {len(self.irrad_curve)} (irrad) "
                f"and {len(self.temperature_curve)} (temp)."
            )

        # Validate for unexpected remaining NaN values (e.g., if the original data had trailing NaNs)
        if self.irrad_curve.iloc[:, 1].isna().any() or self.temperature_curve.iloc[:, 1].isna().any():
            raise ValueError(
                f"Data corruption detected in {self.name}: Unresolved NaN values found post-interpolation.\n"
                f"Verify the source database file '{self.FILE_CSV}' for unfillable data blocks."
            )

    @staticmethod
    def GenerateCSV(PVGen, OUTPUT_DIR = OUTPUT_DIR):
        """
        Consolidates and exports irradiance and temperature curves from all PV generators to CSV.
        
        Args:
            PVGen (list): List of PVGenerator instances.
            OUTPUT_DIR (Path/str): Destination directory. Defaults to global OUTPUT_DIR.
        """

        logger.info("Consolidating curves into CSV files...")
        # 1. Consolidate Irradiance Curves
            # Combine the first generator (serving as a time-base 'locomotive' with datetime) 
            # with only the data columns (iloc[:, 1]) from all remaining generators. 
            # This list-based approach is memory-efficient for large-scale grid simulations.
        if not PVGen:
            raise ValueError("At least one PVGenerator is required to generate outputs.")
        irrad_list = [PVGen[0].irrad_curve] + \
                    [pv.irrad_curve.iloc[:, 1] for pv in PVGen[1:]]

        # 2. Consolidate Temperature Curves
        temp_list = [PVGen[0].temperature_curve] + \
                    [pv.temperature_curve.iloc[:, 1] for pv in PVGen[1:]]

        # 3. Export to CSV
        pd.concat(irrad_list, axis=1).to_csv(OUTPUT_IRRAD_CSV, index=False)
        pd.concat(temp_list, axis=1).to_csv(OUTPUT_TEMP_CSV, index=False)
        logger.info(f"Success! CSV files saved to {OUTPUT_DIR}")

    @staticmethod
    def GenerateDSS(PVGen, OUTPUT_DIR=OUTPUT_DIR):
        """
        Generates an OpenDSS script file defining all PVSystems.
        
        Args:
            PVGen (list): List of PVGenerator instances.
            OUTPUT_DIR (Path/str): Destination directory for the .dss file.
        """

        logger.info("Generating OpenDSS script...")

        # Validate that there is at least one PVGenerator instance to process before attempting to build the DSS file
        if not PVGen:
            raise ValueError("At least one PVGenerator is required to generate outputs.")
        
        # We use a list to collect lines for better performance (string building)
        dss_lines = []

        # 1. Add base curves shared by all PV units (from the first generator)
        # Using f-strings without excessive (+) concatenation for clarity
        dss_lines.append(f"{PVGen[0].ptcurve}")
        dss_lines.append(f"{PVGen[0].effcurve}\n")

        # 2. Build commands for each PV generator
        for i, pv in enumerate(PVGen):
            pv_id = i + 1
            
            # Constructing the multi-line OpenDSS command using a single f-string
            # Note: ~ is the OpenDSS line continuation character
            pv_command = (
                f"New PVSystem.{pv.name} phases={pv.phases} Bus1={pv.bus} "
                f"kV={pv.kv} kVA={pv.kva} irrad={pv.irrad/1000} Pmpp={pv.pmpp}\n"
                f"~ temperature={pv.temperature} PF={pv.pf} EffCurve=MyEff P-TCurve=MyPvsT\n"
                f"~ Daily=my_shape{pv_id}_irrad TDaily=my_shape{pv_id}_temperature\n"
                f"~ Vminpu={pv.vminpu} Model={pv.model}\n"
            )
            dss_lines.append(pv_command)

        # 3. Write the file using pathlib
        with open(OUTPUT_DSS_FILE, "w") as f:
            # Join all lines with a newline separator
            f.write("\n".join(dss_lines))
        logger.info(f"Success! '{OUTPUT_DSS_FILE.name}' saved to {OUTPUT_DIR}")


# ==============================================================================
# NETWORK ALLOCATION AND AUTOMATION FUNCTIONS
# ==============================================================================
def PVCreator(QtdPVs,
              SCRIPT_DSS = SCRIPT_DSS,
              PV_list = PV_LIST_METADATA,
              step = step,
              PV_dictionaries_list = None,
              my_seed = my_seed,
              bus_multi_PV: bool = False,
              npts_origin:int = npts_origin,
              ignore_buses: list = None):
    """
    Automates bus selection and creation of Photovoltaic (PV) systems in an OpenDSS circuit.

    The function identifies compatible buses, randomly selects connection points, 
    and instantiates PVGenerator objects for data curve processing.

    Args:
        QtdPVs (int): Number of PV systems to be randomly installed.
        SCRIPT_DSS (str/Path, optional): Path to the .dss circuit script.
        PV_list (pd.DataFrame, optional): PV plant metadata (BR-PVGen dataset).
        step (str, optional): Time step for linear interpolation (e.g., '5min').
        PV_dictionaries_list (list, optional): Manual pre-definitions for PV units, provided as a list
            of dictionaries. Each dictionary may contain keys 'PV_phases', 'PV_bus', 'PV_kv', 'PV_kva',
            and 'PV_curve_id'. These units are installed first; any remaining slots (QtdPVs) are filled
            randomly from the circuit buses.
        my_seed (int, optional): Seed for reproducible random bus sampling.
        npts_origin (int, optional): Number of points in the original time series.
        bus_multi_PV (bool): If False, prevents the random sampler from selecting 
            buses already occupied by manual inputs or prior samples.
        ignore_buses (str/list): Specific bus identifiers (e.g., '650') to be completely 
            purged from the random allocation candidate pool.
    Returns:
        list: A list of configured and interpolated PVGenerator objects.
    Note:
        If 'PV_kv' or 'PV_kva' are missing from a manual dictionary, a warning is printed
        and the value is set automatically later (bus voltage or default metadata).
    """

    # Initialize OpenDSS interface and compile the target circuit
    dss = py_dss_interface.DSS()

    try:
        dss.text(f"compile '{SCRIPT_DSS}'")

        # Check for compilation success using the OpenDSS error code
        if dss.errorinterface.error_code == 0:
            logger.info("Success! Circuit compiled.")
        else:
            # Raise an exception to stop execution immediately
            raise RuntimeError(f"OpenDSS Compilation Failed: {dss.errorinterface.error_desc}")

        # Set internal seed for reproducibility
        seed(my_seed)

        # Initialize PV dictionaries list and handle bus mapping logic
        # If no list is provided, start with an empty one
        if  PV_dictionaries_list is None:
            PV_Dictionaries = []
            Existent_PV_buses = pd.DataFrame(columns=['bus'])
        else:
            PV_Dictionaries = list(PV_dictionaries_list)
            
            # If multiple PVs per bus are not allowed, extract already occupied buses
            if not bus_multi_PV:
                # Using list comprehension to extract the 'PV_bus' attribute from each dictionary
                Existent_PV_buses = pd.DataFrame({'bus': [dictionary['PV_bus'] for dictionary in PV_Dictionaries]})
            else:
                Existent_PV_buses = pd.DataFrame(columns=['bus'])

        # Initialize support lists for mapping available buses from the circuit
        PV_buses = []
        PV_buses_kv = []
        PV_buses_phases = []
        allbuses_mapping = []

        # Iterate through circuit buses to identify eligible connection points
        logger.info("Mapping available buses...")
        for i in dss.circuit.buses_names:
            dss.circuit.set_active_bus(i)
            if dss.bus.name.isdigit():
                # Define connection and phase count based on bus topology (nodes)
                allbuses_mapping.append(
                    f"{dss.bus.name}." + ".".join(map(str, dss.bus.nodes))
                )
                if len(dss.bus.nodes) == 1:
                    PV_buses.append(f"{dss.bus.name}.{dss.bus.nodes[0]}")
                    PV_buses_phases.append(1)
                elif len(dss.bus.nodes) == 2:
                    # Randomly select one of the available nodes for single-phase connection
                    PV_buses.append(f"{dss.bus.name}.{choice(dss.bus.nodes)}")
                    PV_buses_phases.append(1)
                elif len(dss.bus.nodes) >= 3:
                    PV_buses.append(f"{dss.bus.name}." + ".".join(map(str, dss.bus.nodes)))
                    PV_buses_phases.append(3)
                PV_buses_kv.append(round(dss.bus.kv_base, 2))
        
        # Create candidate DataFrame and perform random bus sampling
        allbuses = pd.DataFrame({'bus': PV_buses, 'L-N kv': PV_buses_kv, 'phases': PV_buses_phases})

        # Create a separate DataFrame for the full bus mapping to validate manual PV configurations against circuit reality
        allbuses_mapping = pd.DataFrame({'bus': allbuses_mapping})

        # Extract base bus names for existence check
        buses_index = allbuses_mapping["bus"].str.split(".").str[0]

        # ==============================================================================
        # PV DICTIONARY VALIDATION
        # ==============================================================================
        # Validate each PV dictionary entry against circuit reality
        for val_idx, val_dict in enumerate(PV_Dictionaries):
            # Verify that each provided dictionary contains the minimum required keys and that PV_phases matches the number of nodes in PV_bus
            try:
                # Structural Check: Ensure minimum keys exist and match types
                val_pv_phases = int(val_dict['PV_phases'])
                val_pv_bus = str(val_dict['PV_bus'])

                # --- Random phase selection for manually defined 2-phase buses ---
                if val_pv_phases == 2:
                    # Extract nodes from bus string
                    val_bus_parts = val_pv_bus.split(".")
                    if len(val_bus_parts) - 1 != 2:  # base + exactly 2 nodes?
                        raise ValueError(
                            f"PV_bus '{val_pv_bus}' at index {val_idx} has {len(val_bus_parts)-1} nodes "
                            f"but PV_phases=2. A 2-phase bus must have exactly two nodes."
                        )
                    val_chosen_node = choice(val_bus_parts[1:]) 

                    # Original values for logging
                    val_original_bus = val_pv_bus
                    val_original_kv = val_dict.get('PV_kv', None)

                    # Update the dictionary to reflect single-phase connection
                    val_new_bus = val_bus_parts[0] + '.' + val_chosen_node
                    val_dict['PV_bus'] = val_new_bus
                    val_dict['PV_phases'] = 1

                    # Recalculate PV_kv: line-to-neutral voltage from the circuit
                    dss.circuit.set_active_bus(val_bus_parts[0])
                    ln_kv = round(dss.bus.kv_base, 2)
                    val_dict['PV_kv'] = ln_kv

                    # Log the conversion
                    logger.warning(
                        "Manually defined 2-phase bus '%s' (index %d) converted to 1-phase: "
                        "randomly selected node '%s'. Provided PV_kv%s ignored; using L-N voltage %.2f kV.",
                        val_original_bus, val_idx, val_chosen_node,
                        f" ({val_original_kv} kV)" if val_original_kv is not None else "",
                        ln_kv
                    )

                # Extract nodes from dictionary
                val_bus_nodes = val_pv_bus.split(".")[1:] if "." in val_pv_bus else ["1", "2", "3"]

                if len(val_bus_nodes) != val_pv_phases:
                    raise ValueError(f"PV_phases ({val_pv_phases}) does not match the number of nodes in PV_bus ({val_pv_bus}).")
                if len(set(val_bus_nodes)) != len(val_bus_nodes):
                    raise ValueError(f"Duplicate nodes detected in PV_bus '{val_pv_bus}'. Each phase node must be unique.")
            except KeyError as e:
                raise KeyError(f"Missing key {e} in PV_Dictionaries at index {val_idx}. "
                                f"Each dictionary must contain at least 'PV_phases' and 'PV_bus'."
                )
            except ValueError as e:
                raise ValueError(
                    f"Validation failed in PV_Dictionaries at index {val_idx}: {e}"
                    f" Ensure 'PV_phases' matches the number of nodes in 'PV_bus'."
                )                
            val_pv_kv = val_dict.get('PV_kv', None)
            if val_pv_kv is None:
                logger.warning(f"Warning: 'PV_kv' not provided for PV at index {val_idx}. It will be calculated based on the bus voltage during PVGenerator instantiation.")    

            val_pv_kva = val_dict.get('PV_kva', None)
            if val_pv_kva is None:
                logger.warning(f"Warning: 'PV_kva' not provided for PV at index {val_idx}. It will be set to a default value during PVGenerator instantiation.")

            val_pv_bus = str(val_dict["PV_bus"])
            val_base_bus = val_pv_bus.split(".")[0]

            # Structural Check: Does the base bus exist in the circuit?
            if val_base_bus not in buses_index.values:
                raise ValueError(
                    f"Manually defined PV_bus '{val_pv_bus}' at index {val_idx} "
                    f"does not match any existent bus in the circuit."
                )


            # Extract actual circuit bus string and its real nodes from DataFrame
            val_ckt_bus = allbuses_mapping.loc[buses_index == val_base_bus, "bus"].values[0]
            val_ckt_nodes = (
                val_ckt_bus.split(".")[1:] if "." in val_ckt_bus else ["1", "2", "3"]
            )

            # Circuit Reality Check: Do these nodes exist in the OpenDSS bus?
            for val_single_node in val_bus_nodes:
                if val_single_node not in val_ckt_nodes:
                    raise ValueError(
                        f"Node '{val_single_node}' defined in PV_bus '{val_pv_bus}' "
                        f"at index {val_idx} does not exist in the actual "
                        f"circuit bus '{val_ckt_bus}'."
                    )
                
        if ignore_buses is not None:
            # If the user passed a single string (e.g., ignore_buses='150'), convert it to a list
            if isinstance(ignore_buses, str):
                ignore_buses = [ignore_buses]
                
            # Extract the pure bus name (before the dot) and filter out the ignored ones
            # e.g., '150.1.2.3' becomes '150' and matches the ignore list
            allbuses = allbuses[~allbuses['bus'].str.split('.').str[0].isin(ignore_buses)]
            logger.info(f"Applied filter - Excluded {len(ignore_buses)} bus(es) from the candidate pool.")

        # Perform unique bus filtering if multi-PV is disabled
        available_buses = allbuses[~allbuses['bus'].isin(Existent_PV_buses['bus'])] if not bus_multi_PV else allbuses
        available_buses = available_buses.reset_index(drop=True)

        if len(available_buses) < QtdPVs:
            raise ValueError(f"Error: Not enough available buses to allocate {QtdPVs} PV systems. Only {len(available_buses)} buses are available.")

        PVbuses = available_buses.sample(n=QtdPVs, random_state=my_seed)

        # Check if manual PV configurations were provided
        if PV_Dictionaries:
            manual_count = len(PV_Dictionaries)
            logger.info(f"Manually defined {manual_count} PV generators from input list.")
        else:
            logger.info("No manual PV configurations detected. Proceeding with random allocation only.")

        logger.info(f"Randomly selected {QtdPVs} buses for PV installation.")

        logger.info(f"{((QtdPVs + len(PV_Dictionaries))/len(available_buses))*100:.2f}% of available buses allocated for PV systems.")
        logger.info(f"{(QtdPVs + len(PV_Dictionaries))} buses occupied out of {len(available_buses)} total available buses.")

        # Populate technical configurations for each PV generator based on the sampled buses
        for bus in PVbuses.index:
            PV_Dictionaries.append({
                'PV_phases': (int(PVbuses.loc[bus, 'phases'])),
                'PV_bus': (PVbuses.loc[bus, 'bus']),
                # Voltage: kV base for 1-phase, kV L-L (base * sqrt(3)) for 3-phase
                'PV_kv': float(((PVbuses.loc[bus, 'L-N kv']) if (PVbuses.loc[bus, 'phases']) == 1 else round(((PVbuses.loc[bus, 'L-N kv'])*(3**(1/2))), 2))),
                'PV_kva': None,
                'PV_curve_id':None})
        
        # Initialize the list for generator objects
        PVGen = []

        # Instantiate converters and apply temporal resampling (interpolation)
        logger.info(f"Starting PV generation and {step} interpolation...")
        for PV, PV_data in enumerate(PV_Dictionaries):
            new_pv = PVGenerator(
                PV_id = PV+1,
                PV_phases = PV_data['PV_phases'],
                PV_bus = PV_data['PV_bus'],
                PV_kv = PV_data['PV_kv'],
                PV_kva = PV_data['PV_kva'],
                PV_curve_id = PV_data['PV_curve_id'],
                npts_origin = npts_origin,
                PV_list = PV_list
            )
            # Resample curves to the simulation time step (step)
            new_pv.CurveLinearInterpolation(step)
            PVGen.append(new_pv)
            logger.info(f"   > {new_pv.name} configured at bus {new_pv.bus} ({new_pv.kva/1000} kVA)")
        print("")
        logger.info("--- STARTING DSS AND CSV FILES CREATION ---")
        print("")
        return PVGen
    finally:
        dss.text("exit")

# ==============================================================================
# SIMULATION RUNTIME (MAIN EXECUTION BLOCK)
# ==============================================================================

if __name__ == "__main__":

    # Model of list of PVs to be created, with the possibility of predefining some parameters
    # and letting the function fill in the rest. This is useful for testing and for cases where
    # we want to ensure certain configurations are included.

    # Dictionary Parameters:
    # - PV_phases: Integer defining the number of phases (e.g., 1 for single-phase, 3 for three-phase).
    # - PV_bus: String representing the bus name and its nodes (e.g., '29.1.2.3').
    # - PV_kv: Float specifying the nominal connection voltage (kV). Following OpenDSS conventions, 
    #   use Line-to-Line (L-L) voltage for 3-phase/2-phase systems, and Line-to-Neutral (L-N) 
    #   voltage for 1-phase systems.
    # - PV_kva: Float defining the rated power capacity (kVA) of the PV inverter.
    # - PV_curve_id: String or None; identifies a specific irradiance/temperature curve to be assigned.
    # - npts_origin: Integer indicating the number of points in the original time series data.
    print("")
    logger.info("--- STARTING POWER SYSTEM PV ALLOCATION PIPELINE ---")
    print("")
    
    # Define Explicit Input Conditions
    PV_Dictionaries = [
        {'PV_phases': 2, 'PV_bus': '646.2.3', 'PV_kv': 4.16, 'PV_kva': 5, 'PV_curve_id': None}
    ]
    
    # Run the Allocation Engine
    PVGen = PVCreator(QtdPVs=4, PV_dictionaries_list=PV_Dictionaries, ignore_buses=['650', '670'])

    # Trigger Outputs Generation
    PVGenerator.GenerateCSV(PVGen)
    PVGenerator.GenerateDSS(PVGen)

    print("")
    logger.info("--- PIPELINE EXECUTION COMPLETED SUCCESSFULLY ---")
    print("")
