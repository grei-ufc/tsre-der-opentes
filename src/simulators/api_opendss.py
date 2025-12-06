import mosaik_api_v3
import datetime
import math
from simulators.opendss_wrapper import OpenDSS, OpenDSSException

META = {
    'api_version': '3.0',
    'type': 'time-based',
    'models': {
        'Grid': {
            'public': True,
            'params': ['topofile'],
            'attrs': []},
        'Load': {
            'public': False,
            'params': [],
            'attrs': ['P_mw', 'Q_mvar', 'P_out_mw', 'Q_out_mvar']},
        'Line': {
            'public': False,
            'params': [],
            'attrs': ['is_open',
                      'I1_A', 'I1_ang',
                      'I2_A', 'I2_ang',
                      'I3_A', 'I3_ang']},
        'Bus': {
            'public': False,
            'params': [],
            'attrs': ['V1_pu', 'V1_ang',
                      'V2_pu', 'V2_ang',
                      'V3_pu', 'V3_ang']
        },
    },
    'extra_methods': ['get_dss_wrapper'],
}

class OpenDSSSimulator(mosaik_api_v3.Simulator):
    def __init__(self):
        super().__init__(META)
        self.sid = None
        self.dss_wrapper = None
        self.step_size = None
        self.entity_map = {}
        self.loads_with_profiles = {}
        self.shape_data_cache = {}
        self.time_resolution = 1.0

    def init(self, sid, time_resolution, topofile, step_size=900, **sim_params):
        self.sid = sid
        self.time_resolution = time_resolution
        self.step_size = step_size
        self.dss_wrapper = OpenDSS(
            redirects=topofile,
            time_step=datetime.timedelta(seconds=self.step_size),
            start_time=datetime.datetime(2025, 1, 1)
        )
        return self.meta

    def create(self, num, model, **model_params):
        if model != 'Grid': raise ValueError(f"Use 'Grid'")
        child_entities = []
        
        # --- Cargas ---
        loads_df = self.dss_wrapper.get_all_elements('Load')
        if not loads_df.empty:
            for full_name in loads_df.index:
                name = full_name.split('.')[1]
                eid = f"Load-{name}"
                self.entity_map[eid] = name
                child_entities.append({'eid': eid, 'type': 'Load'})

                shape_name = None
                try:
                    yearly = self.dss_wrapper.get_property(name, 'yearly', 'Load')
                    daily = self.dss_wrapper.get_property(name, 'daily', 'Load')
                    if isinstance(yearly, str) and yearly.lower() not in ['none', 'constant', '']: shape_name = yearly
                    elif isinstance(daily, str) and daily.lower() not in ['none', 'constant', '']: shape_name = daily
                except: pass

                if shape_name:
                    base_kw = float(self.dss_wrapper.get_property(name, 'kW', 'Load') or 0.0)
                    base_kvar = float(self.dss_wrapper.get_property(name, 'kvar', 'Load') or 0.0)
                    self.loads_with_profiles[eid] = {'shape_name': shape_name, 'base_kw': base_kw, 'base_kvar': base_kvar}
                    
                    if shape_name not in self.shape_data_cache:
                        try:
                            self.dss_wrapper.dss.loadshapes.name = shape_name
                            p_mult = list(self.dss_wrapper.dss.loadshapes.p_mult)
                            q_mult = list(self.dss_wrapper.dss.loadshapes.q_mult)
                            npts = self.dss_wrapper.dss.loadshapes.npts
                            
                            # Se q_mult estiver vazio ou for menor que p_mult, usa p_mult (fator de potência constante)
                            if not q_mult or len(q_mult) < npts:
                                q_mult = p_mult
                            # --------------------------------------------------

                            interval = self.dss_wrapper.dss.loadshapes.s_interval
                            if interval == 0: interval = self.dss_wrapper.dss.loadshapes.min_interval * 60
                            if interval == 0: interval = self.dss_wrapper.dss.loadshapes.hr_interval * 3600
                            if interval == 0: interval = self.step_size
                            
                            self.shape_data_cache[shape_name] = {
                                'p_mult': p_mult,
                                'q_mult': q_mult,
                                'interval_s': interval,
                                'npts': npts,
                                'use_actual': bool(self.dss_wrapper.dss.loadshapes.use_actual)
                            }
                            print(f"[DEBUG] LoadShape '{shape_name}' cacheada com {npts} pontos.")
                        except Exception as e:
                            print(f"[ERRO] Erro ao ler LoadShape '{shape_name}': {e}")
                            del self.loads_with_profiles[eid]

        # --- Linhas ---
        lines_df = self.dss_wrapper.get_all_elements('Line')
        if not lines_df.empty:
            for full_name in lines_df.index:
                name = full_name.split('.')[1]
                eid = f"Line-{name}"
                self.entity_map[eid] = name
                child_entities.append({'eid': eid, 'type': 'Line'})

        buses = self.dss_wrapper.get_all_buses()
        for name in buses:
            eid = f"Bus-{name}"
            self.entity_map[eid] = name
            child_entities.append({'eid': eid, 'type': 'Bus'})

        return [{'eid': 'Grid-0', 'type': 'Grid', 'children': child_entities}]

    def step(self, time, inputs, max_advance):
        # 1. ATUALIZAÇÃO MANUAL DAS CARGAS
        for eid, profile in self.loads_with_profiles.items():
            shape_name = profile['shape_name']
            if shape_name not in self.shape_data_cache: continue
            
            data = self.shape_data_cache[shape_name]
            idx = math.floor(time / data['interval_s']) % data['npts']
            
            # Acesso seguro ao índice ---
            try:
                pmult = data['p_mult'][idx]
                qmult = data['q_mult'][idx]
            except IndexError:
                # Fallback seguro caso algo muito estranho aconteça com os índices
                pmult = data['p_mult'][0]
                qmult = data['q_mult'][0]
            # -------------------------------------------
            
            if data['use_actual']:
                p_set = pmult
                q_set = qmult
            else:
                p_set = profile['base_kw'] * pmult
                q_set = profile['base_kvar'] * qmult
            
            load_name = self.entity_map[eid]
            self.dss_wrapper.set_power(load_name, p=p_set, q=q_set, element='Load')
            
            if eid == 'Load-671' and time < 1200: 
                print(f"[STEP {time}] Atualizando {load_name}: Multiplicador={pmult:.3f} -> Definindo kW={p_set:.2f}")

        # 2. RESOLVER FLUXO DE POTÊNCIA (SNAPSHOT)
        self.dss_wrapper.run_dss()

        return time + self.step_size

    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            if eid not in self.entity_map: continue
            name = self.entity_map[eid]
            model_type = eid.split('-')[0]
            data[eid] = {}
            
            if model_type == 'Load':
                p_kw, q_kvar = self.dss_wrapper.get_power(name, element='Load')
                if 'P_out_mw' in attrs: data[eid]['P_out_mw'] = p_kw / 1000.0
            
            elif model_type == 'Line':
                curr_mag, curr_ang = self.dss_wrapper.get_current(name, element='Line', polar=True, mag_only=False, line_bus=1)
                mags = [curr_mag] if not isinstance(curr_mag, (list, tuple)) else list(curr_mag)
                angs = [curr_ang] if not isinstance(curr_ang, (list, tuple)) else list(curr_ang)
                while len(mags) < 3: mags.append(0.0)
                while len(angs) < 3: angs.append(0.0)

                for attr in attrs:
                    if attr == 'I1_A': data[eid][attr] = mags[0]
                    elif attr == 'I1_ang': data[eid][attr] = angs[0]
                    elif attr == 'I2_A': data[eid][attr] = mags[1]
                    elif attr == 'I2_ang': data[eid][attr] = angs[1]
                    elif attr == 'I3_A': data[eid][attr] = mags[2]
                    elif attr == 'I3_ang': data[eid][attr] = angs[2]

            elif model_type == 'Bus':
                volt_mag, volt_ang = self.dss_wrapper.get_bus_voltage(bus=name, pu=True, mag_only=False, polar=True)
                mags = [volt_mag] if not isinstance(volt_mag, (list, tuple)) else list(volt_mag)
                angs = [volt_ang] if not isinstance(volt_ang, (list, tuple)) else list(volt_ang)
                while len(mags) < 3: mags.append(0.0)
                while len(angs) < 3: angs.append(0.0)

                for attr in attrs:
                    if attr == 'V1_pu': data[eid][attr] = mags[0]
                    elif attr == 'V1_ang': data[eid][attr] = angs[0]
                    elif attr == 'V2_pu': data[eid][attr] = mags[1]
                    elif attr == 'V2_ang': data[eid][attr] = angs[1]
                    elif attr == 'V3_pu': data[eid][attr] = mags[2]
                    elif attr == 'V3_ang': data[eid][attr] = angs[2]

        return data

    def get_dss_wrapper(self):
        return self.dss_wrapper