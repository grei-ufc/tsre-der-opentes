"""Interface Python para o Motor Eletroquímico Caldera ICM (C++)
================================================================

Encapsula as chamadas aos módulos compilados em C++ do simulador Caldera
(Idaho National Laboratory) para geração de perfis de recarga com resolução
minutal, contemplando características elétricas de carregadores (EVSE) e
baterias (fases de Corrente Constante / Tensão Constante - CC/CV e tapering).
"""

import sys
from pathlib import Path
from typing import ClassVar

# Adiciona o diretório atual ao sys.path para carregar os módulos C++ (.so)
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.append(str(CURRENT_DIR))

try:
    import Caldera_ICM_Aux

    CALDERA_AVAILABLE = True
except (ImportError, OSError):
    Caldera_ICM_Aux = None  # type: ignore
    CALDERA_AVAILABLE = False


class CalderaWrapper:
    """Encapsula a interface com as bibliotecas C++ do Caldera.

    Responsável por:
    - Carregar o inventário de veículos e estações de recarga (EV_inputs.csv e EVSE_inputs.csv);
    - Inicializar a fábrica de perfis com passo temporal de 60 segundos;
    - Mapear cada modelo de veículo ao carregador correspondente;
    - Gerar curvas dinâmicas de recarga em função dos estados de carga inicial e final (SoC).
    """

    CHARGER_MAP: ClassVar[dict[str, str]] = {
        "BYD": "BYD_Wallbox_7kW",
        "GWM": "GWM_Wallbox_Serie_G",
        "HAVAL": "GWM_Wallbox_Serie_G",
        "GEELY": "Geely_Padrao_6p6kW",
    }
    DEFAULT_CHARGER = "BYD_Wallbox_7kW"

    def __init__(self, inputs_dir: str | None = None, timestep_sec: float = 60.0):
        if not CALDERA_AVAILABLE:
            raise RuntimeError(
                f"O motor Caldera ICM (C++) não está disponível neste ambiente ({sys.platform}). "
                "Os módulos compilados (.so) requerem Linux x86_64 e Python 3.12."
            )

        if inputs_dir is None:
            project_root = CURRENT_DIR.parent.parent.parent
            inputs_dir = str(project_root / "data" / "datasets" / "veiculos-eletricos")

        self.inputs_dir = inputs_dir
        self.timestep_sec = float(timestep_sec)
        self._profile_cache: dict[tuple[str, str, float, float], list[float]] = {}

        # Inicializa a interface C++ com discretização temporal uniforme
        self._cp_interface = Caldera_ICM_Aux.CP_interface_v2(
            self.inputs_dir,
            self.timestep_sec,  # Passo temporal L1 (segundos)
            self.timestep_sec,  # Passo temporal L2 (segundos)
            self.timestep_sec,  # Passo temporal HPC (segundos)
        )

    def get_charger_for_vehicle(self, vehicle_model: str) -> str:
        """Determina a Wallbox oficial associada à montadora do veículo."""
        model_upper = vehicle_model.upper()
        for brand, charger in self.CHARGER_MAP.items():
            if brand in model_upper:
                return charger
        return self.DEFAULT_CHARGER

    def get_charge_profile(
        self,
        vehicle_model: str,
        initial_soc: float,
        target_soc: float,
        charger_model: str | None = None,
    ) -> list[float]:
        """
        Calcula a curva física de potência ativa (kW) minuto a minuto.

        Args:
            vehicle_model: Nome do modelo (ex: 'BYD DOLPHIN MINI GS5EV')
            initial_soc: SoC inicial (aceita escala 0.0 - 1.0 ou 0 - 100)
            target_soc: SoC alvo final (aceita escala 0.0 - 1.0 ou 0 - 100)
            charger_model: Nome do EVSE (se None, auto-detecta pela montadora)

        Returns:
            Lista de potências ativas em kW para cada minuto de recarga.
        """
        # Normaliza escala de SoC para o padrão do Caldera (0 a 100)
        soc_in = float(initial_soc) * 100.0 if initial_soc <= 1.0 else float(initial_soc)
        soc_out = float(target_soc) * 100.0 if target_soc <= 1.0 else float(target_soc)

        # Trata casos limites (bateria já cheia ou variação de recarga desprezível)
        if soc_out <= soc_in or soc_in >= 99.5 or (soc_out - soc_in) < 0.5:
            return []

        # Limite físico seguro para evitar transbordo de índice no C++
        soc_in = max(0.0, min(soc_in, 99.0))
        soc_out = max(soc_in + 0.1, min(soc_out, 100.0))

        if charger_model is None:
            charger_model = self.get_charger_for_vehicle(vehicle_model)

        cache_key = (vehicle_model, charger_model, round(soc_in, 2), round(soc_out, 2))
        if cache_key in self._profile_cache:
            return self._profile_cache[cache_key]

        try:
            profile = self._cp_interface.get_P3kW_charge_profile(
                soc_in, soc_out, vehicle_model, charger_model
            )
            self._profile_cache[cache_key] = profile
            return profile
        except Exception as e:
            print(
                f"[CalderaWrapper ERROR] Falha ao calcular curva: {vehicle_model} + {charger_model} ({soc_in}% -> {soc_out}%): {e}"
            )
            return []


if __name__ == "__main__":
    import matplotlib.pyplot as plt

    print("\n=== TESTE DO CALDERA WRAPPER COM PLOTAGEM ===")
    wrapper = CalderaWrapper()

    veiculos_teste = [
        ("BYD DOLPHIN MINI GS5EV", "38.88 kWh (BEV)"),
        ("BYD DOLPHIN GS 180EV", "44.90 kWh (BEV)"),
        ("GWM HAVAL H6 PHEV 19", "19.00 kWh (PHEV)"),
        ("GEELY EX2 MAX", "39.40 kWh (BEV)"),
    ]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8.5), dpi=150)

    for modelo, desc in veiculos_teste:
        evse = wrapper.get_charger_for_vehicle(modelo)
        curva = wrapper.get_charge_profile(modelo, initial_soc=0.20, target_soc=1.0)

        duracao_min = len(curva)
        tempo_horas = [m / 60.0 for m in range(duracao_min)]
        p_pico = max(curva) if curva else 0.0
        p_fim = curva[-1] if curva else 0.0

        print(f"-> Veículo: {modelo} ({desc})")
        print(f"   Carregador: {evse}")
        print(f"   Duração: {duracao_min} min ({duracao_min / 60:.2f} h)")
        print(f"   Potência pico: {p_pico:.2f} kW | Final (tapering): {p_fim:.4f} kW\n")

        rotulo = f"{modelo} ({desc}) — {evse} [Pico: {p_pico:.2f} kW]"

        # Subplot 1: Visão Geral (Tempo Absoluto)
        ax1.plot(tempo_horas, curva, linewidth=2.0, label=rotulo)

        # Subplot 2: Zoom nos Últimos 15 Minutos (Tapering / Desaceleração)
        n_tapering = min(15, duracao_min)
        curva_fim = curva[-n_tapering:]
        minutos_restantes = list(range(-n_tapering + 1, 1))  # -14 min até 0 min
        ax2.plot(
            minutos_restantes, curva_fim, linewidth=2.0, marker="o", markersize=3.5, label=rotulo
        )

    # Configurações do Subplot 1 (Geral)
    ax1.set_title(
        "Visão Geral: Ciclo Completo de Recarga Residencial (20% a 100% SoC)",
        fontsize=11,
        fontweight="bold",
    )
    ax1.set_xlabel("Tempo Decorrido de Recarga (Horas)", fontsize=10)
    ax1.set_ylabel("Demanda de Potência AC (kW)", fontsize=10)
    ax1.grid(True, linestyle="--", alpha=0.5)

    # Configurações do Subplot 2 (Tapering)
    ax2.set_title(
        "Detalhamento da Fase de Tapering (Últimos 15 Minutos até Carga Completa)",
        fontsize=11,
        fontweight="bold",
    )
    ax2.set_xlabel("Tempo até o Término da Recarga (Minutos)", fontsize=10)
    ax2.set_ylabel("Demanda de Potência AC (kW)", fontsize=10)
    ax2.grid(True, linestyle="--", alpha=0.5)

    # Legenda única externa no topo da figura (sem cobrir nenhum traço)
    handles, labels = ax1.get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.99),
        ncol=2,
        fontsize=8.5,
        framealpha=0.9,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.92])

    # Cria diretório de output se não existir e salva
    output_dir = CURRENT_DIR.parent.parent.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    caminho_fig = output_dir / "teste_curvas_caldera.png"
    plt.savefig(caminho_fig)
    print(f"Gráfico gerado e salvo com sucesso em: {caminho_fig}")
