"""
Validation routines for the PV allocation pipeline.

This module centralises all error checking and structural validation that was
previously scattered throughout pv_creator.py, keeping the main module focused
on data-processing and OpenDSS scripting logic.
"""

import logging
import pandas as pd

logger = logging.getLogger(__name__)


# ==============================================================================
# PATH & FILE VALIDATION
# ==============================================================================

def validate_paths(INFO_PV_FILE, SCRIPT_DSS, SOLAR_STATION_FILES, OUTPUT_DIR):
    """
    Verifies the existence of all critical input files and directories.

    Args:
        INFO_PV_FILE (Path): Path to the PV metadata CSV file.
        SCRIPT_DSS (Path): Path to the OpenDSS circuit master script.
        SOLAR_STATION_FILES (Path): Path to the solar station CSV directory.
        OUTPUT_DIR (Path): Path to the output directory.

    Raises:
        FileNotFoundError: If any required path is missing.
    """
    print("")
    logger.info("--- STARTING PATHS AND FILES VALIDATION ---")
    print("")
    logger.info("Validating project structure and workspace paths...")

    if not INFO_PV_FILE.is_file():
        raise FileNotFoundError(
            f"Critical input file missing: '{INFO_PV_FILE}'\n"
            f"Check the database or metadata path."
        )
    if not SCRIPT_DSS.is_file():
        raise FileNotFoundError(
            f"Circuit baseline script missing: '{SCRIPT_DSS}'\n"
            f"OpenDSS simulation cannot compile without this file."
        )
    if not SOLAR_STATION_FILES.is_dir():
        raise FileNotFoundError(
            f"Solar curves directory missing: '{SOLAR_STATION_FILES}'\n"
            f"Verify if the weather station database was correctly placed."
        )
    if not OUTPUT_DIR.exists():
        raise FileNotFoundError(
            f"Required output directory does not exist: '{OUTPUT_DIR}'\n"
            f"Indicate the correct directory before running."
        )

    logger.info("Success! All critical files and directories validated.")


# ==============================================================================
# METADATA LOADING & VALIDATION
# ==============================================================================

def load_and_validate_metadata(INFO_PV_FILE):
    """
    Loads the PV metadata CSV and validates its structure and content.

    Args:
        INFO_PV_FILE (Path): Path to the metadata CSV file.

    Returns:
        pd.DataFrame: Loaded metadata DataFrame.

    Raises:
        FileNotFoundError: If the file is not found.
        EOFError: If the file is completely empty (0 bytes or no headers).
        TypeError: If the file is corrupted or poorly formatted.
        ValueError: If the file contains no data rows.
        RuntimeError: For any other unexpected loading error.
    """
    logger.info("Loading and verifying metadata database...")

    try:
        metadata = pd.read_csv(INFO_PV_FILE)

        if metadata.empty:
            raise ValueError(
                f"The metadata file '{INFO_PV_FILE.name}' is empty or contains no data rows."
            )
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Critical Error: The file '{INFO_PV_FILE}' was not found.\n"
        )
    except pd.errors.EmptyDataError:
        raise EOFError(
            f"Critical Error: The file '{INFO_PV_FILE}' is completely empty "
            f"(0 bytes) or has no valid headers."
        )
    except pd.errors.ParserError:
        raise TypeError(
            f"Critical Error: The file '{INFO_PV_FILE}' is corrupted or poorly formatted.\n"
        )
    except Exception as val_err:
        raise RuntimeError(f"Unexpected error while loading metadata: {val_err}")

    logger.info("Success! Metadata loaded successfully.")
    return metadata


# ==============================================================================
# CURVE ID VALIDATION
# ==============================================================================

def validate_curve_id(PV_id, PV_curve_id):
    """
    Resolves and normalises the solar curve ID for a PV generator.

    Falls back to *PV_id* when *PV_curve_id* is NaN and wraps out-of-range
    values into the valid [1, 51] interval.

    Args:
        PV_id (int): Unique integer identifier for the PV generator (used as fallback).
        PV_curve_id (int | float | None): Requested curve ID; may be NaN.

    Returns:
        int: A validated curve ID in the range [1, 51].
    """
    curve_id = PV_id if pd.isna(PV_curve_id) else PV_curve_id

    if curve_id > 51:
        curve_id = int((float(curve_id - 1) % 51) + 1)
    elif curve_id <= 0:
        logger.warning(f"Input PV id was {PV_curve_id}. Must be >= 1. Defaulting to 1.")
        curve_id = 1

    return curve_id


# ==============================================================================
# INTERPOLATED CURVE INTEGRITY CHECK
# ==============================================================================

def validate_interpolated_curves(pv_name, irrad_curve, temperature_curve, expected_points, file_csv):
    """
    Checks that interpolated irradiance and temperature curves have the expected
    number of points and contain no residual NaN values.

    Args:
        pv_name (str): Name of the PV generator (used in error messages).
        irrad_curve (pd.DataFrame): Interpolated irradiance curve.
        temperature_curve (pd.DataFrame): Interpolated temperature curve.
        expected_points (int): Number of rows expected in each curve.
        file_csv (str): Source CSV filename (used in error messages).

    Raises:
        ValueError: If size or NaN checks fail.
    """
    if len(irrad_curve) != expected_points or len(temperature_curve) != expected_points:
        raise ValueError(
            f"Data corruption detected in {pv_name}: Interpolated array size mismatch.\n"
            f"Expected: {expected_points} points. Got: {len(irrad_curve)} (irrad) "
            f"and {len(temperature_curve)} (temp)."
        )

    if irrad_curve.iloc[:, 1].isna().any() or temperature_curve.iloc[:, 1].isna().any():
        raise ValueError(
            f"Data corruption detected in {pv_name}: Unresolved NaN values found post-interpolation.\n"
            f"Verify the source database file '{file_csv}' for unfillable data blocks."
        )


# ==============================================================================
# PV DICTIONARY VALIDATION
# ==============================================================================

def validate_pv_dictionaries(PV_Dictionaries, allbuses_mapping, dss):
    """
    Validates each manually defined PV dictionary entry against circuit reality.

    Checks performed for every entry:
    - Required keys ('PV_phases', 'PV_bus') are present.
    - The number of nodes in 'PV_bus' matches 'PV_phases'.
    - No duplicate nodes are specified.
    - The base bus exists in the compiled OpenDSS circuit.
    - Each declared node exists in the actual circuit bus topology.
    - 2-phase entries are automatically converted to 1-phase (random node selection).
    - Warns when 'PV_kv' or 'PV_kva' are absent.

    Args:
        PV_Dictionaries (list[dict]): List of manually defined PV configurations.
        allbuses_mapping (pd.DataFrame): DataFrame with column 'bus' containing
            full bus strings (e.g., '650.1.2.3') for every bus in the circuit.
        dss: Active py_dss_interface.DSS instance used to query bus voltages.

    Returns:
        list[dict]: The (potentially modified) list of PV dictionaries after
            applying 2-phase conversion and voltage recalculation.

    Raises:
        KeyError: If a required key is missing from a dictionary.
        ValueError: If any structural or circuit-reality check fails.
    """
    from random import choice

    buses_index = allbuses_mapping["bus"].str.split(".").str[0]

    for val_idx, val_dict in enumerate(PV_Dictionaries):
        try:
            val_pv_phases = int(val_dict['PV_phases'])
            val_pv_bus = str(val_dict['PV_bus'])

            # --- 2-phase -> 1-phase automatic conversion ---
            if val_pv_phases == 2:
                val_bus_parts = val_pv_bus.split(".")
                if len(val_bus_parts) - 1 != 2:
                    raise ValueError(
                        f"PV_bus '{val_pv_bus}' at index {val_idx} has "
                        f"{len(val_bus_parts) - 1} nodes but PV_phases=2. "
                        f"A 2-phase bus must have exactly two nodes."
                    )
                val_chosen_node = choice(val_bus_parts[1:])

                val_original_bus = val_pv_bus
                val_original_kv = val_dict.get('PV_kv', None)

                val_new_bus = val_bus_parts[0] + '.' + val_chosen_node
                val_dict['PV_bus'] = val_new_bus
                val_dict['PV_phases'] = 1

                dss.circuit.set_active_bus(val_bus_parts[0])
                ln_kv = round(dss.bus.kv_base, 2)
                val_dict['PV_kv'] = ln_kv

                logger.warning(
                    "Manually defined 2-phase bus '%s' (index %d) converted to 1-phase: "
                    "randomly selected node '%s'. Provided PV_kv%s ignored; using L-N voltage %.2f kV.",
                    val_original_bus, val_idx, val_chosen_node,
                    f" ({val_original_kv} kV)" if val_original_kv is not None else "",
                    ln_kv
                )

            # Re-read possibly modified values
            val_pv_phases = int(val_dict['PV_phases'])
            val_pv_bus = str(val_dict['PV_bus'])

            # --- Phase / node count consistency ---
            val_bus_nodes = val_pv_bus.split(".")[1:] if "." in val_pv_bus else ["1", "2", "3"]

            if len(val_bus_nodes) != val_pv_phases:
                raise ValueError(
                    f"PV_phases ({val_pv_phases}) does not match the number of "
                    f"nodes in PV_bus ({val_pv_bus})."
                )
            if len(set(val_bus_nodes)) != len(val_bus_nodes):
                raise ValueError(
                    f"Duplicate nodes detected in PV_bus '{val_pv_bus}'. "
                    f"Each phase node must be unique."
                )

        except KeyError as e:
            raise KeyError(
                f"Missing key {e} in PV_Dictionaries at index {val_idx}. "
                f"Each dictionary must contain at least 'PV_phases' and 'PV_bus'."
            )
        except ValueError as e:
            raise ValueError(
                f"Validation failed in PV_Dictionaries at index {val_idx}: {e}"
                f" Ensure 'PV_phases' matches the number of nodes in 'PV_bus'."
            )

        # --- Optional key warnings ---
        if val_dict.get('PV_kv') is None:
            logger.warning(
                f"Warning: 'PV_kv' not provided for PV at index {val_idx}. "
                f"It will be calculated based on the bus voltage during PVGenerator instantiation."
            )
        if val_dict.get('PV_kva') is None:
            logger.warning(
                f"Warning: 'PV_kva' not provided for PV at index {val_idx}. "
                f"It will be set to a default value during PVGenerator instantiation."
            )

        # --- Bus existence check ---
        val_pv_bus = str(val_dict["PV_bus"])
        val_base_bus = val_pv_bus.split(".")[0]

        if val_base_bus not in buses_index.values:
            raise ValueError(
                f"Manually defined PV_bus '{val_pv_bus}' at index {val_idx} "
                f"does not match any existent bus in the circuit."
            )

        # --- Node reality check against circuit topology ---
        val_ckt_bus = allbuses_mapping.loc[buses_index == val_base_bus, "bus"].values[0]
        val_ckt_nodes = (
            val_ckt_bus.split(".")[1:] if "." in val_ckt_bus else ["1", "2", "3"]
        )
        val_bus_nodes = val_pv_bus.split(".")[1:] if "." in val_pv_bus else ["1", "2", "3"]

        for val_single_node in val_bus_nodes:
            if val_single_node not in val_ckt_nodes:
                raise ValueError(
                    f"Node '{val_single_node}' defined in PV_bus '{val_pv_bus}' "
                    f"at index {val_idx} does not exist in the actual "
                    f"circuit bus '{val_ckt_bus}'."
                )

    return PV_Dictionaries


# ==============================================================================
# OUTPUT LIST VALIDATION
# ==============================================================================

def validate_pvgen_list(PVGen):
    """
    Ensures that the PVGenerator list is non-empty before generating outputs.

    Args:
        PVGen (list): List of PVGenerator instances.

    Raises:
        ValueError: If the list is empty.
    """
    if not PVGen:
        raise ValueError("At least one PVGenerator is required to generate outputs.")


# ==============================================================================
# BUS AVAILABILITY VALIDATION
# ==============================================================================

def validate_bus_availability(available_buses, QtdPVs):
    """
    Checks that there are enough available buses to satisfy the requested
    random PV count.

    Args:
        available_buses (pd.DataFrame): DataFrame of candidate buses after
            applying exclusion filters.
        QtdPVs (int): Number of PV systems to install randomly.

    Raises:
        ValueError: If the candidate pool is smaller than *QtdPVs*.
    """
    if len(available_buses) < QtdPVs:
        raise ValueError(
            f"Error: Not enough available buses to allocate {QtdPVs} PV systems. "
            f"Only {len(available_buses)} buses are available."
        )
