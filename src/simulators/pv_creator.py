#Importação das bibliotecas
import pandas as pd
import py_dss_interface
from pathlib import Path
from math import ceil # arredondar pra cima
from random import choice, seed

# Configura os diretórios base, de entrada (metadados e dados das estações solares) e de saída,
# utilizando pathlib para construir caminhos relativos ao diretório pai do script.
# Em seguida, carrega o arquivo CSV de metadados das usinas em um DataFrame pandas.

BASE_DIR = Path(".").resolve()
INFO_PV_FILE = BASE_DIR/'src'/'data'/'InfoPV'/'power_station_metadata.csv'
SOLAR_STATION_FILES = BASE_DIR/'src'/'data'/'InfoPV'/'solar_station'
OUTPUT_DIR = BASE_DIR/'src'/'output'
SCRIPT_DSS = BASE_DIR/'src'/'data'/'123Bus'/'run_ieee123_cosim_pv_5min.dss'
PV_list = pd.read_csv(INFO_PV_FILE)

# Configura variáveis importantes

t_simulation = 24*60*1 #tempo total de simulação em minutos
npts_origin = ceil(t_simulation/15) #quantidade total de passos da simulação
step = '5min'
my_seed = 25
seed(my_seed)

class PVShapeConverter:
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
        Recebe os dados do PV e relaciona aos arquivos do dataset.

        Parâmetros: 
        - PV_kv: Tensão de fase da barra de instalação do PV.
        - PV_kva: Potência instalada do PV.
        - PV_bus: Barra em que o PV será conectado.
        - PV_phases: Número de fases da barra que o PV será conectado.
        - PV_id: Número inteiro associado ao nome que será atribuído ao gerador.
        - PV_curve_id: Número inteiro associado ao arquivo com as curvas que será atribuído ao gerador, vai de 1 a 51.
        - npts_origin: Número de pontos que as curvas têm no arquivo original, com passo de simulação de 15 minutos.
        - PV_list: Dataframe que recebe os dados do arquivo de metadados.
        - start: Argumento que define a partir de que pontos os dados originais serão utilizados, ignorando os pontos anteriores ao definido.
        """

        # ===== CONFIGURAÇÃO DO ID DA CURVA E VALIDAÇÃO =====
        # Define o curve_id (priorizando o fornecido ou usando o PV_id como fallback)
        # Garante que o valor fique entre 1 e 51 (faixa válida dos arquivos de curva)
        if pd.isna(PV_curve_id):
           self.curve_id = PV_id #Atribui o valor do id da curva igual ao id painel se não for fornecido
        else:
            self.curve_id = PV_curve_id
        #   Garante que o valor do id da curva vai estar entre 1 e 51 (correspondente aos arquivos)
        if self.curve_id > 51:
            self.curve_id = PV_curve_id % 51 
        elif self.curve_id <= 0:
            print('\nWARNING: O número de id de entrada do PV foi {PV_curve_id}.')
            print('O número de id de entrada do  PV deve ser igual ou maior que 1, portanto foi atribuído a ele o valor default.')
            self.curve_id=1

        # ===== CARREGAMENTO DO ARQUIVO DE CURVA SOLAR =====
        # Localiza e carrega o CSV correspondente ao curve_id definido
        self.curve = PV_list.iloc[self.curve_id-1, 1]
        self.FILE_CSV = self.curve + '.csv'
        self.SOLAR_STATION_FILE = SOLAR_STATION_FILES/self.FILE_CSV
        self.solar_station_curves = pd.read_csv(self.SOLAR_STATION_FILE)

        # ===== ATRIBUTOS BÁSICOS DO PV =====
        # Nome, número de fases, barra, tensão e potência instalada
        self.name = 'PV'+str(PV_id)
        self.phases = PV_phases
        self.bus = PV_bus
        self.kv = PV_kv

        if pd.isna(PV_kva): #Atribui o valor do dataset se não for declarada
            self.kva = int(PV_list.iloc[self.curve_id-1, 3])*1000
        else:
            self.kva = int(PV_kva)
        if PV_phases == 3:
            self.kva = int(self.kva*3)

        # ===== PARÂMETROS ELÉTRICOS E TÉRMICOS DO PAINEL =====
        # Irradiância base, potência máxima (Pmpp), temperatura base, fator de potência
        self.irrad = 0.8 * 1000
        self.pmpp = self.kva
        self.temperature = 25
        self.pf = 1

        # ===== CURVAS DE EFICIÊNCIA E POTÊNCIA =====
        # Define curvas características do inversor e do painel fotovoltaico
        self.effcurve = 'New XYCurve.MyEff npts=4 xarray=[0.1, 0.2, 0.4, 1.0] yarray=[0.86, 0.90, 0.93, 0.97]'
        self.ptcurve = 'New XYCurve.MyPvsT npts=4 xarray=[0, 25, 75, 100] yarray=[1.2, 1.0, 0.8, 0.6]'

        # ===== PROCESSAMENTO DA CURVA DE IRRADIÂNCIA =====
        # Extrai, normaliza, limpa e renomeia os dados de irradiância do arquivo original
        self.npts = npts_origin
        #   Pega os valores de irradiância incidente no plano dos paineis (poa = plane of array).
        self.irrad_curve = ((self.solar_station_curves['poa_irradiance_wm2'].iloc[start:self.npts+start])/self.irrad)
        for i in range(len(self.irrad_curve)):
            if pd.isna(self.irrad_curve.iloc[i]) or self.irrad_curve.iloc[i] < 0:
                self.irrad_curve.iloc[i] = 0
        self.column_name = 'my_shape' + str(PV_id) + '_irrad'
        #self.irrad_curve.rename(columns={'poa_irradiance_wm2':self.column_name}, inplace=True)
        self.irrad_curve.rename(self.column_name, inplace=True)

        # ===== PROCESSAMENTO DA CURVA DE TEMPERATURA =====
        # Extrai, normaliza, limpa e renomeia os dados de temperatura ambiente
        self.temperature_curve = (self.solar_station_curves['panel_temperature_celsius'].iloc[start:self.npts+start])/self.temperature
        for i in range(len(self.temperature_curve)):
            if pd.isna(self.temperature_curve.iloc[i]) or self.temperature_curve.iloc[i] < 0:
                self.temperature_curve.iloc[i] = 0
        self.column_name = 'my_shape' + str(PV_id) + '_temperature'
        #self.temperature_curve.rename(columns={'ambient_temperature_celsius':self.column_name}, inplace=True)
        self.temperature_curve.rename(self.column_name, inplace=True)

        # ===== CONFIGURAÇÕES FINAIS DO OBJETO E CURVAS =====
        # Tensão mínima, modelo do objeto PV e carimbo de tempo
        self.vminpu = 0.001
        self.model = 1
        self.datetime = self.solar_station_curves['datetime'].iloc[start:self.npts+start]
        self.datetime = pd.to_datetime(self.datetime)

        # ===== CONCATENAÇÃO E INDEXAÇÃO DAS CURVAS =====
        # Une as curvas com a coluna de tempo e define o tempo como índice
        self.irrad_curve = pd.concat([self.datetime, self.irrad_curve], axis=1)
        self.temperature_curve = pd.concat([self.datetime, self.temperature_curve], axis=1)
        self.irrad_curve.set_index('datetime', inplace=True)
        self.temperature_curve.set_index('datetime', inplace=True)

    def CurveLinearInterpolation(self, nova_taxa):
        """
        Reamostra uma curva de série temporal (Pandas Series) para qualquer intervalo.
        
        Parâmetros:
        - curva: A variável com os dados (Pandas Series com índice de tempo).
        - nova_taxa: String do Pandas para tempo. Ex: '5s' (5 segundos), '1h' (1 hora), '15min'.
        """
        # ===== REAMOSTRAGEM E INTERPOLAÇÃO LINEAR =====
        # 1. resample(nova_taxa): Agrupa os dados no novo intervalo
        # 2. mean(): Se for subamostragem (1h), calcula a média dos pontos. 
        #            Se for sobreamostragem (5s), coloca o valor original no ponto exato e NaN (vazio) no resto.
        # 3. interpolate(method='time'): Se houver buracos (sobreamostragem), preenche ligando os pontos proporcionalmente ao tempo.
        
        self.irrad_curve = (self.irrad_curve.resample(nova_taxa).mean().interpolate(method='time'))
        self.temperature_curve = self.temperature_curve.resample(nova_taxa).mean().interpolate(method='time')
        
        # ===== ARREDONDAMENTO E RESET DO ÍNDICE =====
        # Arredonda os valores para 6 casas decimais e restaura o índice numérico (converte o tempo de volta para coluna)
        self.irrad_curve = self.irrad_curve.round(6)
        self.temperature_curve = self.temperature_curve.round(6)
        self.irrad_curve = self.irrad_curve.reset_index()
        self.temperature_curve = self.temperature_curve.reset_index()

    @staticmethod
    def GeneratePVDictionaries(
        QtdPVs,
        PV_Dictionaries = None,
        seed = None):

        # Cria a instância para controlar o OpenDSS, depois compila o script do circuito .dss existente.
        dss = py_dss_interface.DSS()

        # Compilação do circuito usando o script .dss.
        dss.text(f"compile '{SCRIPT_DSS}'")

        # Verificação baseada no componente ErrorOpenDSS listado no seu arquivo
        if dss.errorinterface.error_code == 0:
            print("Sucesso: Circuito compilado.")
        else:
            print(f"Erro detectado: {dss.errorinterface.error_desc}")

        PV_Dictionaries = [] if PV_Dictionaries is None else PV_Dictionaries
        PV_buses = []
        PV_buses_kv = []
        PV_buses_phases = []
        for i in dss.circuit.buses_names:
            dss.circuit.set_active_bus(i)
            if dss.bus.name.isdigit():
                if len(dss.bus.nodes) == 1:
                    PV_buses.append(str(dss.bus.name)+'.'+str(dss.bus.nodes[0]))
                    PV_buses_phases.append(1)
                elif len(dss.bus.nodes) == 2:
                    PV_buses.append(str(dss.bus.name)+'.'+str(choice(dss.bus.nodes)))
                    PV_buses_phases.append(1)
                elif len(dss.bus.nodes) == 3:
                    PV_buses.append(str(dss.bus.name)+'.'+str(dss.bus.nodes[0])+'.'+str(dss.bus.nodes[1])+'.'+str(dss.bus.nodes[2]))
                    PV_buses_phases.append(3)
                PV_buses_kv.append(round(dss.bus.kv_base, 2))
        allbuses = pd.DataFrame({'bus': PV_buses, 'kv': PV_buses_kv, 'phases': PV_buses_phases})

        PVbuses = allbuses.sample(n=QtdPVs, random_state=seed)

        for bus in PVbuses.index:
            PV_Dictionaries.append({
                'PV_phases': (int(allbuses.loc[bus, 'phases'])),
                'PV_bus': (allbuses.loc[bus, 'bus']),
                'PV_kv': float(((allbuses.loc[bus, 'kv']) if (allbuses.loc[bus, 'phases']) == 1 else round(((allbuses.loc[bus, 'kv'])*(3**(1/2))), 2))),
                'PV_kva': None,
                'PV_curve_id':None,
                'npts_origin': npts_origin})
        
        return PV_Dictionaries

    @staticmethod
    def GenerateCSV():
        """
        Gera arquivos CSV consolidados com todas as curvas de irradiância e temperatura dos geradores PV.
        
        A função percorre a lista de geradores PV, extrai suas curvas individuais e as concatena
        em DataFrames únicos, que são então salvos como arquivos CSV no diretório de saída.
        
        Arquivos gerados:
        - data_irrad.csv: Contém todas as curvas de irradiância de todos os PVs
        - data_temperature.csv: Contém todas as curvas de temperatura de todos os PVs
        """
        # ===== INICIALIZA AS VARIÁVEIS E PERCORRE TODOS OS GERADORES PV =====
        
        # Inicializa DataFrames vazios para armazenar todas as curvas de temperatura e irradiância
        # que serão consolidadas posteriormente a partir dos múltiplos geradores PV
        all_temperature_curves = pd.DataFrame()
        all_irrad_curves = pd.DataFrame()

        # Itera sobre cada PV na lista global PVDictionaries, enumerando para obter o índice
        for PV, PV_data in enumerate(PV_Dictionaries):
            PV_id = str(PV+1) # ID do PV começando em 1

            # ===== CONCATENAÇÃO DA CURVA DE IRRADIÂNCIA =====
            # Nome da coluna específica de cada PV no formato 'my_shapeX_irrad'
            column_name = 'my_shape' + PV_id + '_irrad'

            # Para o primeiro PV (índice 0), apenas atribui a curva
            # Para os demais, concatena horizontalmente (axis=1) com as curvas existentes
            if PV > 0:
                all_irrad_curves = pd.concat([all_irrad_curves, PVGenerators[PV].irrad_curve[column_name]], axis=1)
            else:
                
                all_irrad_curves = PVGenerators[PV].irrad_curve
            
            # ===== CONCATENAÇÃO DA CURVA DE TEMPERATURA =====
            # Nome da coluna específica de cada PV no formato 'my_shapeX_temperature'
            column_name = 'my_shape' + PV_id + '_temperature'

            if PV > 0:
                all_temperature_curves = pd.concat([all_temperature_curves, PVGenerators[PV].temperature_curve[column_name]], axis=1)
            else:
                all_temperature_curves = PVGenerators[PV].temperature_curve

        # ===== EXPORTAÇÃO DOS ARQUIVOS CSV =====
        # Salva as curvas consolidadas no diretório de saída, sem incluir o índice das linhas
        all_irrad_curves.to_csv((str(OUTPUT_DIR) + '/data_irrad.csv'), index=False)
        all_temperature_curves.to_csv((str(OUTPUT_DIR) + '/data_temperature.csv'), index=False)
    
    @staticmethod
    def GenerateDSS():
        """
        Gera um arquivo de script no formato DSS (OpenDSS) para definir todos os sistemas fotovoltaicos (PVSystems).
        
        O arquivo gerado contém as definições de curvas e parâmetros de cada gerador PV,
        permitindo sua simulação no software OpenDSS.
        
        Arquivo gerado:
        - data_pv.dss: Script com todos os comandos 'New PVSystem' para cada PV cadastrado.
        """

        # ===== INICIALIZAÇÃO DO SCRIPT COM AS CURVAS BASE =====
        # Adiciona as definições das curvas de potência vs temperatura e eficiência
        # que serão compartilhadas por todos os geradores PV
        string_pv = (
            f'{PVGenerators[0].ptcurve}\n'
            + f'{PVGenerators[0].effcurve}\n\n')
        
        # ===== CRIAÇÃO DOS COMANDOS PARA CADA GERADOR PV =====
        # Percorre todos os PVs na lista global PV_Dictionaries
        for PV, PV_data in enumerate(PV_Dictionaries):
            string_pv = string_pv + (
                # Cria o PVSystem com nome, fases, barra, tensão, potência, irradiância e potência máxima
                f'New PVSystem.{str(PVGenerators[PV].name)} phases={str(PVGenerators[PV].phases)} Bus1={str(PVGenerators[PV].bus)} kV={str(PVGenerators[PV].kv)} kVA={str(PVGenerators[PV].kva)} irrad={str((PVGenerators[PV].irrad)/1000)} Pmpp={str(PVGenerators[PV].pmpp)}\n'
                # Linha com parâmetros de temperatura, fator de potência e curvas associadas
                + f'~ temperature={str(PVGenerators[PV].temperature)} PF={str(PVGenerators[PV].pf)} EffCurve=MyEff P-TCurve=MyPvsT\n'
                # Define as curvas diárias de irradiância e temperatura (formato 'my_shapeX_irrad' e 'my_shapeX_temperature')
                + f'~ Daily={'my_shape' + str(PV+1) + '_irrad'} TDaily={'my_shape' + str(PV+1) + '_temperature'}\n'
                # Tensão mínima em pu
                + f'~ Vminpu={str(PVGenerators[PV].vminpu)}\n'
                # Modelo do gerador (1 = modelo de potência constante)
                +f'~ Model={str(PVGenerators[PV].model)}\n\n'
        ) 
        
        # ===== ESCRITA DO ARQUIVO =====
        # Salva o script gerado como arquivo .dss no diretório de saída
        with open((str(OUTPUT_DIR) + '/data_pv.dss'), "w") as f:
            f.write(string_pv)