import mosaik_api_v3
import numpy as np

# ==============================================================================
# 1. MODELO FÍSICO DO PAINEL SOLAR (Domínio)
# ==============================================================================
class PVPanelModel:
    """
    Classe que emula o comportamento físico e elétrico de um painel solar.
    Totalmente independente do Mosaik.
    """
    def __init__(self, p_mpp, irradiance_base, pt_curve_x, pt_curve_y):
        # Parâmetros construtivos
        self.p_mpp = p_mpp
        self.irradiance_base = irradiance_base
        self.pt_curve_x = pt_curve_x
        self.pt_curve_y = pt_curve_y
        
        # Variáveis de Estado (Inputs e Outputs)
        self.irradiance = 0.0
        self.temperature = 25.0
        self.P_dc = 0.0 # <--- P MAIÚSCULO

    def calculate_step(self):
        """
        Calcula as grandezas elétricas baseadas no clima atual.
        Equação 1 do comportamento_pv.md
        """
        # Avalia a Curva PT (Correção por Temperatura)
        pt_factor = np.interp(self.temperature, self.pt_curve_x, self.pt_curve_y)
        
        # P_dc[t] = Pmpp * irradiance_base * irradiance[t] * PTCurve(Temp[t])
        p_dc_calc = self.p_mpp * self.irradiance_base * self.irradiance * pt_factor
        self.P_dc = max(0.0, p_dc_calc)

# ==============================================================================
# 2. WRAPPER DO SIMULADOR (API Mosaik)
# ==============================================================================
META = {
    'api_version': '3.0',
    'type': 'time-based',
    'models': {
        'PVPanel': {
            'public': True,
            'params': [
                'P_mpp',           # Potência nominal CC em kW
                'irradiance_base', # Irradiância base (normalmente 1.0 kW/m2 ou 0.8)
                'pt_curve_x',      # Array de temperaturas (ex: [0, 25, 75, 100])
                'pt_curve_y'       # Array de fatores (ex: [1.2, 1.0, 0.8, 0.6])
            ],
            # CORREÇÃO: I_dc removido da lista de atributos
            'attrs': ['irradiance', 'temperature', 'P_dc'],
        },
    },
}

class PVPanelSim(mosaik_api_v3.Simulator):
    def __init__(self):
        super().__init__(META)
        self.entities = {} # Aqui guardaremos instâncias de PVPanelModel
        self.step_size = 1

    def init(self, sid, time_resolution=1.0, step_size=1.0):
        self.step_size = int(step_size)
        return self.meta

    def create(self, num, model, **model_params):
        entities = []
        for i in range(num):
            eid = f'{model}_{len(self.entities) + i}'
            
            # Instancia o modelo físico real usando a nova classe
            panel_model = PVPanelModel(
                p_mpp=model_params.get('P_mpp', 1000.0),
                irradiance_base=model_params.get('irradiance_base', 1.0),
                pt_curve_x=model_params.get('pt_curve_x', [0, 25, 75, 100]),
                pt_curve_y=model_params.get('pt_curve_y', [1.15, 1.0, 0.8, 0.6]),
            )
            
            # Salva o objeto na lista de entidades do Mosaik
            self.entities[eid] = panel_model
            entities.append({'eid': eid, 'type': model})
            
        return entities

    def step(self, time, inputs, max_advance):
        # 1. Receber e atualizar inputs climáticos
        for eid, attrs in inputs.items():
            panel = self.entities[eid]
            
            if 'irradiance' in attrs:
                panel.irradiance = float(list(attrs['irradiance'].values())[0])
            if 'temperature' in attrs:
                panel.temperature = float(list(attrs['temperature'].values())[0])

        # 2. Executar a física para todos os painéis
        for eid, panel in self.entities.items():
            panel.calculate_step()
            
            # CORREÇÃO: Alterado de panel.p_dc para panel.P_dc
            print(f"[PVPanel Debug] Tempo: {time}s | Irr: {panel.irradiance:.2f} | Temp: {panel.temperature:.1f}°C | P_dc: {panel.P_dc:.2f} kW")

        return time + self.step_size

    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            panel = self.entities[eid]
            data[eid] = {}
            for attr in attrs:
                # O Python busca o valor da variável de mesmo nome dentro da classe PVPanelModel
                if hasattr(panel, attr):
                    data[eid][attr] = getattr(panel, attr)
        return data

if __name__ == '__main__':
    mosaik_api_v3.start_simulation(PVPanelSim())