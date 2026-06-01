import mosaik_api_v3
import numpy as np
import math
import statistics
from opender import DER_PV

# ==============================================================================
# 1. MODELO FÍSICO DO INVERSOR (Domínio)
# ==============================================================================
class InverterModel:
    """
    Classe que emula o comportamento elétrico e as lógicas de proteção 
    (cut-in/cut-out, eficiência e limites) de um inversor (Potência Total).
    """
    def __init__(self, kVA, priority, eff_curve_x, eff_curve_y, pct_cutin, pct_cutout, ctrl_config=None):
        self.kVA = kVA
        self.priority = priority
        self.eff_curve_x = eff_curve_x
        self.eff_curve_y = eff_curve_y
        self.pct_cutin = pct_cutin
        self.pct_cutout = pct_cutout
        self.ctrl_config = ctrl_config or {}
        
        self.is_on = False
        self.P_dc = 0.0
        self.Q_des = 0.0 # Setpoint manual (usado se as funções de rede estiverem desligadas)
        self.V_meas = [None, None, None] # Novo: Tensão lida da rede
        
        self.P_ac = 0.0
        self.Q_ac = 0.0

        # --- Instanciando e configurando o OpenDER ---
        self.der_obj = DER_PV()
        self.der_obj.der_file.NP_VA_MAX = kVA * 1000.0  
        self.der_obj.der_file.NP_P_MAX = kVA * 1000.0

        self._apply_control_configurations()

    def _apply_control_configurations(self):
        """
        Lê o dicionário ctrl_config e injeta os parâmetros no OpenDER.
        Se o valor for True, ativa a função com curvas default.
        Se o valor for um Dicionário, ativa a função e subscreve os pontos.
        """
        
        # 1. VOLT-VAR
        if 'volt_var' in self.ctrl_config:
            vv_config = self.ctrl_config['volt_var']
            
            # Habilita a função
            if vv_config:
                self.der_obj.der_file.QV_MODE_ENABLE = True

                
            # Se for um dicionário, aplica as configurações de curva
            if isinstance(vv_config, dict):
                if 'vref' in vv_config: self.der_obj.der_file.QV_VREF = vv_config['vref']
                if 'v1' in vv_config: self.der_obj.der_file.QV_CURVE_V1 = vv_config['v1']
                if 'q1' in vv_config: self.der_obj.der_file.QV_CURVE_Q1 = vv_config['q1']
                if 'v2' in vv_config: self.der_obj.der_file.QV_CURVE_V2 = vv_config['v2']
                if 'q2' in vv_config: self.der_obj.der_file.QV_CURVE_Q2 = vv_config['q2']
                if 'v3' in vv_config: self.der_obj.der_file.QV_CURVE_V3 = vv_config['v3']
                if 'q3' in vv_config: self.der_obj.der_file.QV_CURVE_Q3 = vv_config['q3']
                if 'v4' in vv_config: self.der_obj.der_file.QV_CURVE_V4 = vv_config['v4']
                if 'q4' in vv_config: self.der_obj.der_file.QV_CURVE_Q4 = vv_config['q4']

        # 2. VOLT-WATT
        if 'volt_watt' in self.ctrl_config:
            vw_config = self.ctrl_config['volt_watt']
            
            # Habilita a função
            if vw_config:
                self.der_obj.der_file.PV_MODE_ENABLE = True
                
            # Se for um dicionário, aplica as configurações de curva
            if isinstance(vw_config, dict):
                if 'v1' in vw_config: self.der_obj.der_file.PV_CURVE_V1 = vw_config['v1']
                if 'p1' in vw_config: self.der_obj.der_file.PV_CURVE_P1 = vw_config['p1']
                if 'v2' in vw_config: self.der_obj.der_file.PV_CURVE_V2 = vw_config['v2']
                if 'p2' in vw_config: self.der_obj.der_file.PV_CURVE_P2 = vw_config['p2']

            # ctrl_config = {
            #     'volt_var': {
            #         'v1': 0.95,
            #         'q1': 1.0,
            #         'v2': 1.05,
            #         'q2': -1.0,
            #         'v3': 1.05,
            #         'q3': -1.0,
            #         'v4': 1.05,
            #         'q4': -1.0
            #     }
            # }

            # ctrl_config = {
            #     'volt_watt': {
            #         'v1': 0.95,
            #         'p1': 1.0,
            #         'v2': 1.05,
            #         'p2': -1.0
            #     }
            # }


    def calculate_step(self):
        p_ac = 0.0
        q_ac = 0.0
        
        if self.kVA > 0:
            # Lógica de Cut-in / Cut-out original mantida
            p_dc_pct = (self.P_dc / self.kVA) * 100
            
            if not self.is_on:
                if p_dc_pct >= self.pct_cutin:
                    self.is_on = True
            else:
                if p_dc_pct <= self.pct_cutout:
                    self.is_on = False

            # Se estiver LIGADO, prossegue com os cálculos CA totais
            if self.is_on:
                # 1. Aplica sua curva de eficiência para achar a potência ativa "Bruta" disponível
                p_pu = self.P_dc / self.kVA
                eff = np.interp(p_pu, self.eff_curve_x, self.eff_curve_y)
                p_ac_uncapped = self.P_dc * eff
                
                # 2. Avaliar tensão da rede para o IEEE 1547 (Média das fases conectadas)
                valid_v = [v for v in self.V_meas if v is not (None or 0.0)]
                v_eval = statistics.mean(valid_v) if valid_v else 1.0
                
                # 3. Alimentar e Rodar o controlador OpenDER (em Watts)
                # Passamos o p_ac_uncapped pois o OpenDER precisa saber qual a potência CC disponível 
                # (já descontando sua eficiência interna) para calcular o Volt-Watt e prioridades
                self.der_obj.update_der_input(v_pu=v_eval, f=60.0, p_dc_w=p_ac_uncapped * 1000.0)
                
                p_opender_w, q_opender_var = self.der_obj.run()
                
                # 4. Coletar os valores sugeridos pelo IEEE 1547
                P_des = p_opender_w / 1000.0
                
                # Se as funções de Reativo do IEEE não estiverem ativas, respeitamos o seu setpoint manual (self.Q_des)
                if self.ctrl_config.get('Volt_Var', False) or self.ctrl_config.get('Const_PF', False):
                    Q_des = q_opender_var / 1000.0
                else:
                    Q_des = self.Q_des
                
                # 5. Sua matemática exata de Prioridade atuando como "Post-Filter"
                if self.priority == 'Active':
                    p_ac = min(P_des, self.kVA) 
                    q_max_avail = math.sqrt(self.kVA**2 - p_ac**2)
                    q_ac = math.copysign(min(abs(Q_des), q_max_avail), Q_des) if Q_des != 0 else 0.0
                    
                elif self.priority == 'Reactive':
                    q_ac = math.copysign(min(abs(Q_des), self.kVA), Q_des) if Q_des != 0 else 0.0
                    p_max_avail = math.sqrt(self.kVA**2 - q_ac**2)
                    p_ac = min(P_des, p_max_avail)
        
        self.P_ac = p_ac
        self.Q_ac = q_ac

# ==============================================================================
# 2. WRAPPER DO SIMULADOR (API Mosaik)
# ==============================================================================
META = {
    'api_version': '3.0',
    'type': 'time-based',
    'models': {
        'Inverter': {
            'public': True,
            'params': [
                'kVA',         
                'priority',    
                'eff_curve_x', 
                'eff_curve_y', 
                'pct_cutin',
                'pct_cutout',
                'ctrl_config'   # Novo: Dict para ativar/desativar lógicas
            ],
            'attrs': [
                'P_dc', 'Q_des', 
                'V_meas_1', 'V_meas_2', 'V_meas_3', # Novo: Necessário para Volt-Var/Volt-Watt
                'P_ac', 'Q_ac'
            ],
        },
    },
}

class InverterSim(mosaik_api_v3.Simulator):
    def __init__(self):
        super().__init__(META)
        self.entities = {} 
        self.step_size = 1

    def init(self, sid, time_resolution=1.0, step_size=1.0):
        self.step_size = int(step_size)
        return self.meta
        
    def create(self, num, model, **model_params):
        entities = []
        for i in range(num):
            eid = f'{model}_{len(self.entities) + i}'
            
            inv_model = InverterModel(
                kVA=model_params.get('kVA', 1000.0),
                priority=model_params.get('priority', 'Active'),
                eff_curve_x=model_params.get('eff_curve_x', [0.0, 1.0]),
                eff_curve_y=model_params.get('eff_curve_y', [1.0, 1.0]),
                pct_cutin=model_params.get('pct_cutin', 20.0),
                pct_cutout=model_params.get('pct_cutout', 20.0),
                ctrl_config=model_params.get('ctrl_config', {})
            )
            
            self.entities[eid] = inv_model
            entities.append({'eid': eid, 'type': model})
            
        return entities

    def step(self, time, inputs, max_advance):
        for eid, attrs in inputs.items():
            inv = self.entities[eid]
            if 'P_dc' in attrs: 
                inv.P_dc = float(list(attrs['P_dc'].values())[0])
            if 'Q_des' in attrs: 
                inv.Q_des = float(list(attrs['Q_des'].values())[0])
                
            # Zera o buffer de tensões do step para ler as novas
            inv.V_meas = [None, None, None]
            if 'V_meas_1' in attrs: inv.V_meas[0] = float(list(attrs['V_meas_1'].values())[0])
            if 'V_meas_2' in attrs: inv.V_meas[1] = float(list(attrs['V_meas_2'].values())[0])
            if 'V_meas_3' in attrs: inv.V_meas[2] = float(list(attrs['V_meas_3'].values())[0])

        for eid, inv in self.entities.items():
            inv.calculate_step()

        return time + self.step_size

    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            inv = self.entities[eid]
            data[eid] = {}
            for attr in attrs:
                if hasattr(inv, attr):
                    data[eid][attr] = getattr(inv, attr)
        return data

if __name__ == '__main__':
    mosaik_api_v3.start_simulation(InverterSim())