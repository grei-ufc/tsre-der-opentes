import mosaik_api_v3
import numpy as np

META = {
    'api_version': '3.0',
    'type': 'time-based',
    'models': {
        'PVPanel': {
            'public': True,
            'params': [
                'P_mpp',           # Potência nominal CC em kW
                'irradiance_base', # Irradiância base (normalmente 1.0 kW/m2)
                'pt_curve_x',      # Array de temperaturas (ex: [0, 25, 75, 100])
                'pt_curve_y'       # Array de fatores (ex: [1.2, 1.0, 0.8, 0.6])
            ],
            'attrs': ['irradiance', 'temperature', 'P_dc'],
        },
    },
}

class PVPanelSim(mosaik_api_v3.Simulator):
    def __init__(self):
        super().__init__(META)
        self.entities = {}
        self.step_size = 1

    def init(self, sid, time_resolution=1.0, step_size=1.0):
        self.step_size = step_size
        return self.meta

    def create(self, num, model, **model_params):
        entities = []
        for i in range(num):
            eid = f'{model}_{len(self.entities) + i}'
            self.entities[eid] = {
                'P_mpp': model_params.get('P_mpp', 1000.0),
                'irradiance_base': model_params.get('irradiance_base', 1.0),
                # Curva PT padrão se não fornecida
                'pt_curve_x': model_params.get('pt_curve_x', [0, 25, 75, 100]),
                'pt_curve_y': model_params.get('pt_curve_y', [1.15, 1.0, 0.8, 0.6]),
                'irradiance': 0.0, # Input temporal
                'temperature': 25.0, # Input temporal
                'P_dc': 0.0
            }
            entities.append({'eid': eid, 'type': model})
        return entities

    def step(self, time, inputs, max_advance):
        # 1. Receber inputs climáticos (irradiância e temperatura)
        for eid, attrs in inputs.items():
            for attr, values in attrs.items():
                self.entities[eid][attr] = float(list(values.values())[0])

        # 2. Calcular Equação 1 do comportamento_pv.md
        for eid, state in self.entities.items():
            irr_t = state['irradiance']
            temp_t = state['temperature']
            pmpp = state['P_mpp']
            irr_base = state['irradiance_base']
            
            # Avalia a Curva PT (Correção por Temperatura)
            pt_factor = np.interp(temp_t, state['pt_curve_x'], state['pt_curve_y'])
            
            # P_dc[t] = Pmpp * irradiance_base * irradiance[t] * PTCurve(Temp[t])
            # Nota: irr_t vindo do arquivo CSV já costuma ser pu ou (irradiance_base * irr_t)
            p_dc = pmpp * irr_base * irr_t * pt_factor
            
            state['P_dc'] = max(0.0, p_dc) 

            print(f"[PVPanel Debug] Tempo: {time}s | Irr: {irr_t} | Temp: {temp_t} | P_dc: {state['P_dc']}")

        return time + self.step_size

    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            data[eid] = {attr: self.entities[eid][attr] for attr in attrs}
        return data

if __name__ == '__main__':
    mosaik_api_v3.start_simulation(PVPanelSim())