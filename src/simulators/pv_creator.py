# --- Library Imports ---
import pandas as pd              # Data manipulation and CSV file handling
import py_dss_interface          # Python interface for OpenDSS (EPRI)
from pathlib import Path         # Object-oriented filesystem paths
from math import ceil            # Ceiling function to calculate total simulation points
from random import choice, seed  # Random node selection and reproducibility seeding

# --- Environment and Path Configurations ---
BASE_DIR = Path(".").resolve()
INFO_PV_FILE = BASE_DIR/'src'/'data'/'InfoPV'/'power_station_metadata.csv'
SOLAR_STATION_FILES = BASE_DIR/'src'/'data'/'InfoPV'/'solar_station'
OUTPUT_DIR = BASE_DIR/'src'/'output'
SCRIPT_DSS = BASE_DIR/'src'/'data'/'123Bus'/'run_ieee123_cosim_pv_5min.dss'
PV_list = pd.read_csv(INFO_PV_FILE)

# --- Simulation Control Variables ---
t_simulation = 24*60*1              # Total simulation time in minutes
npts_origin = ceil(t_simulation/15) # Original data points (15-min base)
step = '5min'                       # Target simulation time step
my_seed = 25

def PVCreator(QtdPVs,
              SCRIPT_DSS = SCRIPT_DSS,
              PV_list = PV_list,
              step = step,
              PV_Dictionaries = None,
              seed = my_seed,
              npts_origin:int = npts_origin):
    """
    Automates bus selection and creation of Photovoltaic (PV) systems in an OpenDSS circuit.

    The function identifies compatible buses, randomly selects connection points, 
    and instantiates PVGenerator objects for data curve processing.

    Args:
        QtdPVs (int): Number of PV systems to be randomly installed.
        SCRIPT_DSS (str/Path, optional): Path to the .dss circuit script.
        PV_list (pd.DataFrame, optional): PV plant metadata (BR-PVGen dataset).
        step (str, optional): Time step for linear interpolation (e.g., '5min').
        PV_Dictionaries (list, optional): Base list for PV configuration dictionaries.
        seed (int, optional): Seed for reproducible random bus sampling.
        npts_origin (int, optional): Number of points in the original time series.

    Returns:
        PVGen: A list of configured and interpolated PVGenerator objects.
    """
    
    # Initialize OpenDSS interface and compile the target circuit
    dss = py_dss_interface.DSS()
    dss.text(f"compile '{SCRIPT_DSS}'")

    # Check for compilation success using the OpenDSS error code
    if dss.errorinterface.error_code == 0:
        print("Success: Circuit compiled.")
    else:
        # Raise an exception to stop execution immediately
        raise RuntimeError(f"OpenDSS Compilation Failed: {dss.errorinterface.error_desc}")

    # Set internal seed for reproducibility
    seed(seed)

    # Initialize support lists for bus mapping 
    PV_Dictionaries = [] if PV_Dictionaries is None else PV_Dictionaries
    PV_buses = []
    PV_buses_kv = []
    PV_buses_phases = []

    # Iterate through circuit buses to identify eligible connection points
    for i in dss.circuit.buses_names:
        dss.circuit.set_active_bus(i)
        if dss.bus.name.isdigit():
            # Define connection and phase count based on bus topology (nodes)
            if len(dss.bus.nodes) == 1:
                PV_buses.append(str(dss.bus.name)+'.'+str(dss.bus.nodes[0]))
                PV_buses_phases.append(1)
            elif len(dss.bus.nodes) == 2:
                # Randomly select one of the available nodes for single-phase connection
                PV_buses.append(str(dss.bus.name)+'.'+str(choice(dss.bus.nodes)))
                PV_buses_phases.append(1)
            elif len(dss.bus.nodes) == 3:
                PV_buses.append(str(dss.bus.name)+'.'+str(dss.bus.nodes[0])+'.'+str(dss.bus.nodes[1])+'.'+str(dss.bus.nodes[2]))
                PV_buses_phases.append(3)
            PV_buses_kv.append(round(dss.bus.kv_base, 2))
    
    # Create candidate DataFrame and perform random bus sampling
    allbuses = pd.DataFrame({'bus': PV_buses, 'kv': PV_buses_kv, 'phases': PV_buses_phases})
    PVbuses = allbuses.sample(n=QtdPVs, random_state=seed)

    # Populate technical configurations for each PV generator based on the sampled buses
    for bus in PVbuses.index:
        PV_Dictionaries.append({
            'PV_phases': (int(allbuses.loc[bus, 'phases'])),
            'PV_bus': (allbuses.loc[bus, 'bus']),
            # Voltage: kV base for 1-phase, kV L-L (base * sqrt(3)) for 3-phase
            'PV_kv': float(((allbuses.loc[bus, 'kv']) if (allbuses.loc[bus, 'phases']) == 1 else round(((allbuses.loc[bus, 'kv'])*(3**(1/2))), 2))),
            'PV_kva': None,
            'PV_curve_id':None,
            'npts_origin': npts_origin})
    
    # Initialize the list for generator objects
    PVGen = []

    # Instantiate converters and apply temporal resampling (interpolation)
    for PV, PV_data in enumerate(PV_Dictionaries):
        PVGen.append(PVGenerator(
            PV_id = PV+1,                              # ID sequencial começando em 1
            PV_phases = PV_data['PV_phases'],          # Número de fases (1 ou 3)
            PV_bus = PV_data['PV_bus'],                # Barra de conexão
            PV_kv = PV_data['PV_kv'],                  # Tensão nominal (kV)
            PV_kva = PV_data['PV_kva'],                # Potência (None = usa dataset)
            PV_curve_id = PV_data['PV_curve_id'],      # ID da curva (None = usa PV_id)
            npts_origin = PV_data['npts_origin'],      # Número de pontos originais
            PV_list = PV_list                          # DataFrame com metadados
        ))
        # Resample curves to the simulation time step (step)
        PVGen[PV].CurveLinearInterpolation(step)
    return PVGen

class PVGenerator:
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
            self.curve_id = PV_curve_id % 51 
        elif self.curve_id <= 0:
            print(f'\nWARNING: Input PV id was {PV_curve_id}. Must be >= 1. Defaulting to 1.')
            self.curve_id = 1

        # --- SOLAR CURVE FILE LOADING ---
        # Locate and load the CSV file corresponding to the defined curve_id
        self.curve = PV_list.iloc[self.curve_id-1, 1]
        self.FILE_CSV = self.curve + '.csv'
        self.SOLAR_STATION_FILE = SOLAR_STATION_FILES/self.FILE_CSV

        try:
            self.solar_station_curves = pd.read_csv(self.SOLAR_STATION_FILE)
        except FileNotFoundError:
            raise FileNotFoundError(f"Error: Dataset file {self.SOLAR_STATION_FILE} not found.")

        # --- BASIC PV ATTRIBUTES ---
        # Naming, phase count, bus connection, voltage, and capacity
        self.name = 'PV'+str(PV_id)
        self.phases = PV_phases
        self.bus = PV_bus
        self.kv = PV_kv
        
        # KVA Setup: Use metadata if PV_kva is NaN. Scale by 3 for 3-phase systems.
        base_kva = int(PV_list.iloc[self.curve_id-1, 3]) * 1000 if pd.isna(PV_kva) else int(PV_kva)
        self.kva = base_kva * 3 if PV_phases == 3 else base_kva

        # --- ELECTRICAL & THERMAL PANEL PARAMETERS ---
        # Base irradiance, max power (Pmpp), reference temperature, and power factor
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
        data_slice = slice(start, self.npts + start)
        
        # 1. Process Irradiance (Normalize, clip negatives, fill NaNs)
        self.irrad_curve = (self.solar_station_curves['poa_irradiance_wm2'].iloc[data_slice] / self.irrad)
        self.irrad_curve = self.irrad_curve.clip(lower=0).fillna(0)
        self.irrad_curve.name = f'my_shape{PV_id}_irrad'

        # 2. Process Temperature (Normalize, fill NaNs)
        self.temperature_curve = (self.solar_station_curves['panel_temperature_celsius'].iloc[data_slice] / self.temperature)
        self.temperature_curve = self.temperature_curve.fillna(1)
        self.temperature_curve.name = f'my_shape{PV_id}_temperature'

        # 3. Handle Datetime & Indexing
        # Convert timestamp strings to datetime objects for time-based operations
        self.datetime = pd.to_datetime(self.solar_station_curves['datetime'].iloc[data_slice])

        # Concatenate curves with time column and set as index for resampling
        self.irrad_curve = pd.concat([self.datetime, self.irrad_curve], axis=1).set_index('datetime', inplace=True)
        self.temperature_curve = pd.concat([self.datetime, self.temperature_curve], axis=1).set_index('datetime', inplace=True)

    def CurveLinearInterpolation(self, new_rate):
        """
        Resamples a time-series curve to a new time frequency using linear interpolation.
        
        Args:
            new_rate (str): Pandas offset alias for frequency (e.g., '5s', '1h', '15min').
        """
        # --- RESAMPLING & LINEAR INTERPOLATION ---
        # 1. resample: Groups data into the new time interval (new_rate)
        # 2. mean: Aggregates points for downsampling or creates NaNs for upsampling
        # 3. interpolate: Fills gaps using time-proportional linear connection
        
        self.irrad_curve = (self.irrad_curve.resample(new_rate).mean().interpolate(method='time')).round(6)
        
        self.temperature_curve = (self.temperature_curve.resample(new_rate).mean().interpolate(method='time')).round(6)
        
        # Reset index to restore numerical indexing and convert time back to a column
        self.irrad_curve = self.irrad_curve.reset_index()
        self.temperature_curve = self.temperature_curve.reset_index()




