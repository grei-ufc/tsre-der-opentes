"""Simulador Mosaik para Veículos Elétricos com Motor Físico Caldera (C++)
========================================================================

Interface de co-simulação Mosaik para modelagem detalhada da recarga de Veículos
Elétricos (VEs). Utiliza as curvas físicas calculadas pelo módulo compilado C++
Caldera ICM (Idaho National Laboratory), contemplando a dinâmica eletroquímica de
baterias Li-ion (etapas CC/CV, tapering) e fator de potência estocástico (IEC 61000).
"""

import math
from pathlib import Path

import mosaik_api_v3
import numpy as np
import pandas as pd

try:
    from .caldera_wrapper import CalderaWrapper
except ImportError:
    from caldera_wrapper import CalderaWrapper  # type: ignore

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent.parent
DEFAULT_SESSIONS_CSV = (
    PROJECT_ROOT / "data" / "datasets" / "veiculos-eletricos" / "ev_sessions_caldera.csv"
)

META = {
    "api_version": "3.0",
    "type": "time-based",
    "models": {
        "CalderaEV": {
            "public": True,
            "params": [
                "profile_name",  # Identificador do perfil semanal no catálogo (ex: User_12_semana_1_7p2kW)
                "csv_path",  # Caminho opcional para o arquivo de sessões de recarga
            ],
            "attrs": [
                "P_kw",  # Potência ativa demandada da rede AC (kW)
                "Q_kvar",  # Potência reativa consumida pelo carregador (kvar)
                "fp",  # Fator de potência do carregador [0.98 a 1.00]
                "is_charging",  # Sinalizador de estado de recarga ativa (True/False)
            ],
        },
    },
}


class CalderaEVModel:
    """Modelo de veículo elétrico para co-simulação temporal no Mosaik.

    Armazena a série temporal pré-calculada de recarga (resolução de 1 minuto ao
    longo de 10.080 minutos / 7 dias) e calcula em cada passo a potência ativa
    injetada e a respectiva potência reativa indutiva decorrente do fator de potência.
    """

    def __init__(self, eid: str, profile_name: str, power_series: np.ndarray, fp: float = 1.0):
        self.eid = eid
        self.profile_name = profile_name
        self.power_series = power_series  # Série temporal em minutos (10.080 minutos por semana)
        self.total_minutes = len(power_series)
        self.fp = float(fp)

        # Cálculo da tangente do ângulo de fase: tan(phi) = sqrt(1 - fp^2) / fp
        if 0.0 < self.fp < 1.0:
            self.tan_phi = math.sqrt(1.0 - self.fp**2) / self.fp
        else:
            self.tan_phi = 0.0

        # Estados elétricos instantâneos expostos ao Mosaik
        self.P_kw = 0.0
        self.Q_kvar = 0.0
        self.is_charging = False

    def update_step(self, current_minute: int):
        """Atualiza a potência ativa e reativa para o minuto corrente da simulação."""
        idx = current_minute % self.total_minutes
        self.P_kw = float(self.power_series[idx])
        self.is_charging = self.P_kw > 0.05
        # Reativo indutivo conforme normas IEC 61000-3-2 e IEC 61000-3-12
        if self.is_charging:
            self.Q_kvar = round(float(self.P_kw * self.tan_phi), 4)
        else:
            self.Q_kvar = 0.0


class CalderaEVSim(mosaik_api_v3.Simulator):
    """Simulador Mosaik para despacho de cargas de Veículos Elétricos com física Caldera."""

    def __init__(self):
        super().__init__(META)
        self.sid = None
        self.step_size = None
        self.entities: dict[str, CalderaEVModel] = {}
        self.wrapper: CalderaWrapper = None
        self.events_df: pd.DataFrame = None

    def init(self, sid, time_resolution=1.0, step_size=600, inputs_dir=None, **kwargs):
        """Inicializa o simulador e carrega a interface com os módulos C++ do Caldera."""
        self.sid = sid
        self.step_size = step_size
        self.wrapper = CalderaWrapper(inputs_dir=inputs_dir)
        return self.meta

    def create(self, num, model, **model_params):
        """Instancia entidades de VE a partir de perfis de recarga especificados."""
        if model != "CalderaEV":
            raise ValueError(f"Modelo desconhecido: {model}. Esperado: 'CalderaEV'")

        # Carrega o CSV de sessões físicas na primeira chamada
        if self.events_df is None:
            csv_path = model_params.get("csv_path", DEFAULT_SESSIONS_CSV)
            if not Path(csv_path).exists():
                raise FileNotFoundError(f"Arquivo de sessões não encontrado em: {csv_path}")
            self.events_df = pd.read_csv(csv_path)

        entities_info = []

        for i in range(num):
            eid = f"{model}_{len(self.entities) + i}"
            profile_name = model_params.get("profile_name")

            if not profile_name:
                raise ValueError(f"Parâmetro obrigatório 'profile_name' ausente para {eid}")

            # Filtra todas as sessões de recarga desta curva/usuário
            df_perfil = self.events_df[self.events_df["Profile_Name"] == profile_name]

            # Vetor de 7 dias * 24 horas * 60 minutos = 10.080 minutos
            power_series = np.zeros(10080, dtype=np.float64)

            # Para cada sessão do perfil, calcula a física exata do Caldera
            for _, sessao in df_perfil.iterrows():
                start_min = int(sessao["Start_Min"])
                end_min = int(sessao["End_Min"])
                soc_in = float(sessao["Initial_SoC"])
                soc_out = float(sessao["Target_SoC"])
                modelo_veiculo = str(sessao.get("Modelo_Veiculo", "BYD DOLPHIN MINI GS5EV"))

                # Consulta a física do C++ com tapering CC/CV e eficiência de inversor
                curva_p = self.wrapper.get_charge_profile(
                    vehicle_model=modelo_veiculo,
                    initial_soc=soc_in,
                    target_soc=soc_out,
                )

                duracao_fisica = len(curva_p)
                duracao_sessao = max(1, end_min - start_min)

                # Preenche a série temporal
                # Se o carro completou a recarga antes de desempilhar (t_idle > 0), a potência vai a zero
                for m_rel in range(duracao_sessao):
                    min_abs = start_min + m_rel
                    if min_abs < 10080:
                        if m_rel < duracao_fisica:
                            power_series[min_abs] = curva_p[m_rel]
                        else:
                            power_series[min_abs] = 0.0  # Concluído e ocioso na tomada

            # Sorteio do fator de potência estocástico por veículo constante durante a semana
            # FP ~ U(0.98, 1.00) conforme normas IEC 61000-3-2 e IEC 61000-3-12
            fp_ev = round(float(np.random.uniform(0.98, 1.00)), 4)

            # Instancia o modelo da entidade
            ev_model = CalderaEVModel(eid, profile_name, power_series, fp=fp_ev)
            self.entities[eid] = ev_model
            entities_info.append({"eid": eid, "type": model})

        return entities_info

    def step(self, time, inputs, max_advance):
        # time é dado em segundos pelo Mosaik
        current_minute = int(time // 60)

        for _eid, ev_model in self.entities.items():
            ev_model.update_step(current_minute)

        return time + self.step_size

    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            ev_model = self.entities[eid]
            data[eid] = {}
            for attr in attrs:
                if hasattr(ev_model, attr):
                    data[eid][attr] = getattr(ev_model, attr)
        return data


def main():
    return mosaik_api_v3.start_simulation(CalderaEVSim())


if __name__ == "__main__":
    main()
