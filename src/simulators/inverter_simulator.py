import mosaik_api_v3
import numpy as np
import math

META = {
    'api_version': '3.0',
    'type': 'time-based',
    'models': {
        'Inverter': {
            'public': True,
            'params': [
                'kVA',         # Capacidade do Inversor
                'priority',    # 'Active' ou 'Reactive'
                'eff_curve_x', # Array de P_dc / kVA (pu) (ex: [0.1, 0.2, ..., 1.0])
                'eff_curve_y',  # Array de Eficiências pu (ex: [0.86, 0.9, ..., 0.98])
                'pct_cutin',
                'pct_cutout'
            ],
            'attrs': ['P_dc', 'Q_des', 'P_ac', 'Q_ac'],
        },
    },
}

class InverterSim(mosaik_api_v3.Simulator):
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
                'kVA': model_params.get('kVA', 1000.0),
                'priority': model_params.get('priority', 'Active'), # Padrão OpenDSS
                # Curva de eficiência padrão (Inversor Ideal / 100% se não passada)
                'eff_curve_x': model_params.get('eff_curve_x', [0.0, 1.0]),
                'eff_curve_y': model_params.get('eff_curve_y', [1.0, 1.0]),
                'pct_cutin': model_params.get('pct_cutin', 20.0),
                'pct_cutout': model_params.get('pct_cutout', 20.0),
                'is_on': False,
                'P_dc': 0.0,
                'Q_des': 0.0, # Q requisitado por controladores externos (ex: Volt-Var)
                'P_ac': 0.0,
                'Q_ac': 0.0
            }
            entities.append({'eid': eid, 'type': model})
        return entities

    def step(self, time, inputs, max_advance):
        for eid, attrs in inputs.items():
            if 'P_dc' in attrs: self.entities[eid]['P_dc'] = list(attrs['P_dc'].values())[0]
            if 'Q_des' in attrs: self.entities[eid]['Q_des'] = list(attrs['Q_des'].values())[0]

        for eid, state in self.entities.items():
            p_dc = state['P_dc']
            q_des = state['Q_des']
            kva = state['kVA']
            priority = state['priority']
            
            p_ac = 0.0
            q_ac = 0.0
            
            if kva > 0:
                # 1. Lógica de Cut-in / Cut-out baseada na potência CC entrante
                p_dc_pct = (p_dc / kva) * 100
                
                # Histerese do Inversor
                if not state['is_on']:
                    if p_dc_pct >= state['pct_cutin']:
                        state['is_on'] = True
                else:
                    if p_dc_pct <= state['pct_cutout']:
                        state['is_on'] = False

                # 2. Se estiver ON, prossegue com os cálculos de CA
                if state['is_on']:
                    p_pu = p_dc / kva
                    eff = np.interp(p_pu, state['eff_curve_x'], state['eff_curve_y'])
                    p_ac_uncapped = p_dc * eff
                    
                    if priority == 'Active':
                        p_ac = min(p_ac_uncapped, kva) 
                        q_max_avail = math.sqrt(kva**2 - p_ac**2)
                        q_ac = math.copysign(min(abs(q_des), q_max_avail), q_des) if q_des != 0 else 0.0
                        
                    elif priority == 'Reactive':
                        q_ac = math.copysign(min(abs(q_des), kva), q_des) if q_des != 0 else 0.0
                        p_max_avail = math.sqrt(kva**2 - q_ac**2)
                        p_ac = min(p_ac_uncapped, p_max_avail)
            
            state['P_ac'] = p_ac
            state['Q_ac'] = q_ac

        return time + int(self.step_size)

    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            data[eid] = {attr: self.entities[eid][attr] for attr in attrs}
        return data

if __name__ == '__main__':
    mosaik_api_v3.start_simulation(InverterSim())