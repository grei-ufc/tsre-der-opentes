import pandapower as pp
import simbench as sb
import os
# Criar o arquivo .json da rede 1-LV-rural2--0-sw
#net = sb.get_simbench_net('1-LV-rural2--0-sw')
#output_file = 'rede_1-LV-rural2--0-sw.json'

# Criar o arquivo .json da rede 1-LV-urban6--0-sw
net = sb.get_simbench_net('1-LV-urban6--0-sw')
output_file = '1-LV-urban6--0-sw.json'

# 2. Aumentar MUITO a impedância do transformador
#net.trafo.at[0, 'vk_percent'] = 20.0  # Impedância extremamente alta
#net.trafo.at[0, 'vkr_percent'] = 4
#net.trafo.at[0, 'tap_pos'] = 0
print(f"Impedância do transformador: {net.trafo.at[0, 'vk_percent']}%")
print(f"Impedância do transformador: {net.trafo.at[0, 'vkr_percent']}%")

#pp.runpp(net)


# # # Salvar a rede em JSON
pp.to_json(net, output_file)


