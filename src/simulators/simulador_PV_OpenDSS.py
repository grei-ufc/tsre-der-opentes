import py_dss_interface
import os
import pathlib
import pandas as pd

#Encontrar caminho do arquivo .dss principal
script_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

dss_file = pathlib.Path(script_path).joinpath("data", "13bus", "IEEE13Nodeckt_w_loadcurve.dss")

#print(f"\nPasta resultante:{dss_file}")
dss = py_dss_interface.DSS()

dss.text(f"compile [{dss_file}]")

#dss.text("redirect LoadShapePV.dss")
#dss.text("redirect LoadShape.dss")

#dss.text("redirect IEEE13PVsystem.dss")

dss.text("set mode=daily")  
dss.text("set stepsize=15m")        
dss.text("set number=384")          

#dss.circuit.set_active_bus("680")
#bus_voltages = dss.bus.vmag_angle
#dss.text("New Monitor.V_barra680 element=Line.671680 terminal=1 mode=0")
#dss.text("New Monitor.pot_barra680 element=Line.671680 terminal=1 mode=1")

dss.text("Solve")

dss.text("Export monitors V_barra671")
dss.text("Export monitors PV_variables")

df1 = pd.read_csv(pathlib.Path(script_path).joinpath("data", "13bus", "IEEE13Nodeckt_Mon_v_barra671_1.csv"))
df2 = pd.read_csv(pathlib.Path(script_path).joinpath("data", "13bus", "IEEE13Nodeckt_Mon_pv_variables_1.csv"))

#hora = (df1['hour'])%24
#minuto = (df1[' t(sec)'])/60
#print(minuto)

col1 = df2['PanelkW']

tensao_base_V = 2400  

col2 = df1[' V1'] / tensao_base_V
col3 = df1[' V2'] / tensao_base_V
col4 = df1[' V3'] / tensao_base_V

conteudo_csv = pd.concat([col1, col2, col3, col4], axis=1)

minutos_por_linha = int(((df1.loc[1, ' t(sec)']) - (df1.loc[0, ' t(sec)']))/60)

data_inicial = pd.to_datetime('2016-01-01 00:00:00')
conteudo_csv[' Hora'] = data_inicial + pd.to_timedelta(conteudo_csv.index * minutos_por_linha, unit='m')

nome_arquivo = pathlib.Path(script_path).joinpath("output", "resultados.csv")

conteudo_csv.to_csv(nome_arquivo, index=False)