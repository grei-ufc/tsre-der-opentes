import math

class OpenDSSBattery:
    """
    Implementação Python fiel ao modelo 'Storage' do OpenDSS (Storage.pas).
    
    Convenção de Sinais (Gerador/OpenDSS):
    - kW > 0: Discharging (Injetando na rede)
    - kW < 0: Charging (Absorvendo da rede)
    """
    
    # Constantes de Estado baseadas no Storage.pas
    STATE_IDLING = 0
    STATE_DISCHARGING = 1
    STATE_CHARGING = -1

    def __init__(self, name, 
                 kw_rated, 
                 kwh_rated, 
                 kwh_stored, 
                 kwh_reserve=0.0,
                 eff_charge=0.90, 
                 eff_discharge=0.90, 
                 idling_kw=0.0,
                 kva_rated=None,
                 max_charge_kw=None,
                 max_discharge_kw=None):
        
        self.name = name
        
        # Parâmetros Nominais
        self.kw_rated = float(kw_rated)
        self.kwh_rated = float(kwh_rated)
        self.kwh_reserve = float(kwh_reserve) # Nível mínimo antes de parar descarga
        
        # Estado InicialP
        self.kwh_stored = float(kwh_stored)
        self.state = self.STATE_IDLING
        
        # Eficiências e Perdas
        self.eff_charge = float(eff_charge)
        self.eff_discharge = float(eff_discharge)
        self.idling_kw = float(idling_kw)
        
        # Limites do Inversor
        self.kva_rated = float(kva_rated) if kva_rated else self.kw_rated * 1.0 # Default PF=1
        
        # Limites explícitos de carga/descarga (se diferentes do nominal)
        self.max_charge_kw = max_charge_kw if max_charge_kw else self.kw_rated
        self.max_discharge_kw = max_discharge_kw if max_discharge_kw else self.kw_rated

        # Saídas para o passo atual
        self.p_out_kw = 0.0
        self.q_out_kvar = 0.0

    def calculate_step(self, p_request, q_request, dt_seconds):
        """
        Executa a lógica de despacho e atualização de estado para um passo de tempo.
        
        Args:
            p_request (float): Potência ativa solicitada (+ Descarrega, - Carrega)
            q_request (float): Potência reativa solicitada
            dt_hours (float): Passo de tempo em horas
            
        Returns:
            dict: Estado atualizado e potências efetivas.
        """

        dt_hours = dt_seconds / 3600.0
        
        # 1. Limitação pelo Inversor (Círculo de Potência Aparente)
        # Prioridade para Potência Ativa (P) típica em Grid-Following
        p_limited = p_request
        q_limited = q_request
        
        # Clamp P nos limites nominais de carga/descarga
        if p_limited > self.max_discharge_kw:
            p_limited = self.max_discharge_kw
        elif p_limited < -self.max_charge_kw:
            p_limited = -self.max_charge_kw
            
        # Verifica violação de kVA
        s_sq = p_limited**2 + q_limited**2
        if s_sq > self.kva_rated**2:
            # Se exceder kVA, reduz Q primeiro (Prioridade P)
            available_q = math.sqrt(max(0, self.kva_rated**2 - p_limited**2))
            if q_limited > 0:
                q_limited = available_q
            else:
                q_limited = -available_q
                
            # Se mesmo com Q=0 o P for muito alto (raro se kw_rated <= kva_rated), clamp P
            if abs(p_limited) > self.kva_rated:
                 p_limited = math.copysign(self.kva_rated, p_limited)

        # 2. Determinação do Estado e Cálculo da Energia Química
        # Baseado na lógica do Storage.pas
        
        delta_energy_kwh = 0.0
        next_state = self.STATE_IDLING
        
        # --- MODO CHARGING (P < 0) ---
        if p_limited < -1e-6: # Tolerância numérica
            # Lógica: A rede fornece P_grid. Parte se perde no inversor e idling.
            # O resto carrega o químico.
            # Energia armazenada AUMENTA (sinal + no balanço do químico)
            
            # Potência vinda da rede (magnitude positiva)
            p_grid_mag = abs(p_limited)
            
            # P_quimico = (P_grid - P_idling) * Eficiencia
            p_chem = (p_grid_mag - self.idling_kw) * self.eff_charge
            
            if p_chem > 0:
                next_state = self.STATE_CHARGING
                # Verifica se cabe no armazenamento
                energy_to_store = p_chem * dt_hours
                if (self.kwh_stored + energy_to_store) > self.kwh_rated:
                    # Bateria cheia: Reduz a potência para caber exatamente
                    energy_to_store = max(0, self.kwh_rated - self.kwh_stored)
                    p_chem = energy_to_store / dt_hours
                    # Recalcula P_grid reverso: P_grid = (P_chem / Eff) + P_idling
                    p_grid_mag = (p_chem / self.eff_charge) + self.idling_kw
                    p_limited = -p_grid_mag # Ajusta o output real
                    
                delta_energy_kwh = energy_to_store # Positivo (incrementa kWh)
            else:
                # Perdas maiores que a carga -> Bateria drena (Idling efetivo)
                next_state = self.STATE_IDLING
                # Drena a diferença da bateria
                loss_deficit = abs(p_chem) 
                delta_energy_kwh = -loss_deficit * dt_hours

        # --- MODO DISCHARGING (P > 0) ---
        elif p_limited > 1e-6:
            # Lógica: Químico fornece energia para cobrir Saída + Perdas + Idling
            # Energia armazenada DIMINUI
            
            # P_quimico = (P_out + P_idling) / Eficiencia
            p_chem = (p_limited + self.idling_kw) / self.eff_discharge
            
            next_state = self.STATE_DISCHARGING
            energy_required = p_chem * dt_hours
            
            # Verifica se tem energia suficiente (respeitando Reserva)
            available_energy = self.kwh_stored - self.kwh_reserve
            
            if available_energy < 0: available_energy = 0
            
            if energy_required > available_energy:
                # Bateria vazia (ou atingiu reserva): Entrega o que pode
                energy_required = available_energy
                if energy_required <= 0:
                    p_limited = 0
                    next_state = self.STATE_IDLING
                    delta_energy_kwh = - (self.idling_kw * dt_hours) # Apenas perdas de vazio
                else:
                    # Recalcula P_out possível
                    p_chem = energy_required / dt_hours
                    # P_out = (P_chem * Eff) - P_idling
                    p_limited = (p_chem * self.eff_discharge) - self.idling_kw
                    if p_limited < 0: p_limited = 0
                    delta_energy_kwh = -energy_required
            else:
                delta_energy_kwh = -energy_required # Negativo (decrementa kWh)

        # --- MODO IDLING (P ~ 0) ---
        else:
            next_state = self.STATE_IDLING
            p_limited = 0
            # Em Idling, consome perdas constantes
            delta_energy_kwh = - (self.idling_kw * dt_hours)

        # 3. Atualização Final do Estado
        self.kwh_stored += delta_energy_kwh
        
        # Clamp de segurança (erros numéricos)
        if self.kwh_stored < 0: self.kwh_stored = 0
        if self.kwh_stored > self.kwh_rated: self.kwh_stored = self.kwh_rated
            
        self.state = next_state
        self.p_out_kw = p_limited
        self.q_out_kvar = q_limited

        return {
            'p_kw': self.p_out_kw,
            'q_kvar': self.q_out_kvar,
            'soc_pct': (self.kwh_stored / self.kwh_rated) * 100,
            'state': self.get_state_str()
        }

    def get_state_str(self):
        if self.state == self.STATE_CHARGING: return "Charging"
        if self.state == self.STATE_DISCHARGING: return "Discharging"
        return "Idling"