import py_dss_interface
import os
import pathlib

#Encontrar caminho do arquivo .dss principal
script_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

dss_file = pathlib.Path(script_path).joinpath("data", "13bus", "IEEE13Nodeckt_w_loadcurve.dss")

#print(f"\nPasta resultante:{dss_file}")
dss = py_dss_interface.DSS()

dss.text(f"compile [{dss_file}]")

dss.text("redirect LoadShapePV.dss")
dss.text("redirect LoadShape.dss")

dss.text("redirect IEEE13PVsystem.dss")

dss.text("Set Controlmode=OFF")

dss.text("set mode=daily")  
dss.text("set stepsize=10m")        
dss.text("set number=280")          

dss.text("New Monitor.V_barra680 element=PVSystem.PV_680 terminal=1 mode=0")
dss.text("New Monitor.pot_barra680 element=PVSystem.PV_680 terminal=1 mode=1")

dss.text("Solve")

dss.text("Export monitors V_barra680")
dss.text("Export monitors pot_barra680")


