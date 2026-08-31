"""
Allocate photovoltaic generators on a distribution network.

Generates interpolated irradiance/temperature profiles from weather station data
and produces a corresponding OpenDSS script file for time-series power flow.
"""

__version__ = "1.1.1"
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

import pandas as pd                             # Data manipulation and CSV file handling
import py_dss_interface                         # Python interface for OpenDSS (EPRI)
import logging                                  # Logging for debugging and information output
from pathlib import Path                        # Object-oriented filesystem paths
from math import ceil                           # Ceiling function to calculate total simulation points
from random import choice, seed                 # Random node selection and reproducibility seeding
from scipy.interpolate import PchipInterpolator # Piecewise Cubic Hermite Interpolating Polynomial for smooth curve fitting
import pv_validator as val                      # Centralised validation and error-checking routines
import topology_builder as tb                   # Topology building and bus classification routines

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
SCRIPT_DSS = BASE_DIR/'src'/'data'/'LVTestCase'/'Master.dss'
OUTPUT_DIR = BASE_DIR/'src'/'data'/'LVTestCase'
OUTPUT_IRRAD_CSV = OUTPUT_DIR/'LVTestCase_shape_pv_5min.csv'
OUTPUT_TEMP_CSV = OUTPUT_DIR/'LVTestCase_temperature_5min.csv'
OUTPUT_DSS_FILE = OUTPUT_DIR/'LVTestCase_pv.dss'

# --- Paths And Files Validation ---
val.validate_paths(INFO_PV_FILE, SCRIPT_DSS, SOLAR_STATION_FILES, OUTPUT_DIR)

# --- Global Data Loading And Validation ---
PV_LIST_METADATA = val.load_and_validate_metadata(INFO_PV_FILE)

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
        # Resolve and normalise the curve ID (falls back to PV_id, wraps [1,51])
        self.curve_id = val.validate_curve_id(PV_id, PV_curve_id)

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
    
        self.irrad = 1000
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

        # 2. Process Temperature (Raw values, fill NaNs)
        self.temperature_curve = self.solar_station_curves['panel_temperature_celsius'].iloc[data_slice].reset_index(drop=True)
        self.temperature_curve = self.temperature_curve.fillna(25)
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
        val.validate_interpolated_curves(
            self.name, self.irrad_curve, self.temperature_curve, expected_points, self.FILE_CSV
        )

    def CurvePCHIPInterpolation(self, new_rate=step, npts_base_15min=npts_origin, start_date=start_date):
        """
        Resamples a time-series curve to a new time frequency using PCHIP interpolation.
    
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

        # --- RESAMPLING & PCHIP INTERPOLATION ---
        # 1. resample: Groups data into the new time interval (new_rate)
        # 2. mean: Aggregates clustered points
        # 3. interpolate: Fills gaps using PCHIP
        irrad_res = self.irrad_curve.resample(new_rate).mean()
        temp_res = self.temperature_curve.resample(new_rate).mean()
        
        # PCHIP interpolation works best with numeric indexes in pandas
        self.irrad_curve = irrad_res.reset_index(drop=True).interpolate(method='pchip').round(6)
        self.temperature_curve = temp_res.reset_index(drop=True).interpolate(method='pchip').round(6)
        
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
        val.validate_interpolated_curves(
            self.name, self.irrad_curve, self.temperature_curve, expected_points, self.FILE_CSV
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
        val.validate_pvgen_list(PVGen)
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
        val.validate_pvgen_list(PVGen)
        
        # We use a list to collect lines for better performance (string building)
        dss_lines = []
        irrad_shape_lines = []
        temp_shape_lines = []

        # 1. Determine number of points and interval
        npts = len(PVGen[0].irrad_curve)
        # Calculate interval in minutes from the time delta of the first two steps
        try:
            delta = PVGen[0].irrad_curve['Date'].iloc[1] - PVGen[0].irrad_curve['Date'].iloc[0]
            minterval = delta.total_seconds() / 60.0
        except Exception:
            minterval = 5 # fallback if calculation fails

        irrad_shape_file_name = OUTPUT_DSS_FILE.with_name(OUTPUT_DSS_FILE.stem + "_irrad_shapes.dss")
        temp_shape_file_name = OUTPUT_DSS_FILE.with_name(OUTPUT_DSS_FILE.stem + "_temp_shapes.dss")

        # 2. Build commands for each PV generator
        for i, pv in enumerate(PVGen):
            pv_id = i + 1
            
            # Extract multipliers for LoadShapes
            irrad_mults = pv.irrad_curve.iloc[:, 1].tolist()
            temp_mults = pv.temperature_curve.iloc[:, 1].tolist()
            
            irrad_str = " ".join([f"{x:.4f}" for x in irrad_mults])
            temp_str = " ".join([f"{x:.4f}" for x in temp_mults])
            
            irrad_shape_lines.append(f"New LoadShape.my_shape{pv_id}_irrad npts={npts} minterval={minterval} mult=[{irrad_str}]")
            temp_shape_lines.append(f"New Tshape.my_shape{pv_id}_temperature npts={npts} minterval={minterval} temp=[{temp_str}]")
            
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

        # 3. Add base curves and the shapes redirect shared by all PV units (at the beginning)
        dss_lines.insert(0, f"Redirect {irrad_shape_file_name.name}\n")
        dss_lines.insert(1, f"Redirect {temp_shape_file_name.name}\n")
        dss_lines.insert(2, f"{PVGen[0].ptcurve}")
        dss_lines.insert(3, f"{PVGen[0].effcurve}\n")

        # 4. Write the files using pathlib
        with open(irrad_shape_file_name, "w") as f:
            f.write("\n".join(irrad_shape_lines))
        logger.info(f"Success! '{irrad_shape_file_name.name}' saved to {OUTPUT_DIR}")

        with open(temp_shape_file_name, "w") as f:
            f.write("\n".join(temp_shape_lines))
        logger.info(f"Success! '{temp_shape_file_name.name}' saved to {OUTPUT_DIR}")

        with open(OUTPUT_DSS_FILE, "w") as f:
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

        logger.info("Classifying buses using topology builder...")
        load_buses = tb.get_load_buses(dss)
        pv_buses_exist = tb.get_pv_buses(dss)
        transformer_buses = tb.get_transformer_buses(dss)
        
        # We exclude reference, virtual and regulator buses from being selected for PV installation.
        excluded_node_types = {"refbus", "virtual_bus", "regulator_bus"}

        # Iterate through circuit buses to identify eligible connection points
        logger.info("Mapping available buses...")
        for i in dss.circuit.buses_names:
            dss.circuit.set_active_bus(i)
            
            node_type = tb.get_node_type(
                dss.bus.name.lower(),
                load_buses,
                pv_buses_exist,
                transformer_buses
            )
            
            if node_type not in excluded_node_types:
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
        PV_Dictionaries = val.validate_pv_dictionaries(PV_Dictionaries, allbuses_mapping, dss)
                
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

        val.validate_bus_availability(available_buses, QtdPVs)

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
            new_pv.CurvePCHIPInterpolation(step)
            PVGen.append(new_pv)
            logger.info(f"   > {new_pv.name} configured at bus {new_pv.bus} ({new_pv.kva} kVA)")
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
    # PV_Dictionaries = [
    #     {'PV_phases': 2, 'PV_bus': '646.2.3', 'PV_kv': 4.16, 'PV_kva': 5, 'PV_curve_id': None}
    # ]
    #ignore_buses = None

    # Run the Allocation Engine
    PVGen = PVCreator(QtdPVs=45)

    # Trigger Outputs Generation
    PVGenerator.GenerateCSV(PVGen)
    PVGenerator.GenerateDSS(PVGen)

    print("")
    logger.info("--- PIPELINE EXECUTION COMPLETED SUCCESSFULLY ---")
    print("")
